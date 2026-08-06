# --- data_processing.py ---
"""
ARGO NetCDF -> PostgreSQL/PostGIS + ChromaDB ingestion pipeline.

Public interface (relied on by dashboard.py and data_processing_verbose.py):

    ArgoDataProcessor(data_dir=None)
        .db_manager   : DatabaseManager
        .vector_store : VectorStoreManager
        .process_netcdf_file(path) -> list[(DataFrame, metadata_dict)]
        .process_directory(max_files=None, reset=True) -> dict stats

IMPORTANT: a single ARGO *_prof.nc file contains many DIFFERENT floats
(typically 60-75 profiles from 60-75 distinct platforms). Records are grouped
per platform so every measurement carries its own float_id.
"""

import glob
import logging
import os

import numpy as np
import pandas as pd
import xarray as xr

from config import DATA_PROCESSING_CONFIG
from database_manager import DatabaseManager
from rag_system import VectorStoreManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ARGO reference epoch for the JULD variable.
ARGO_EPOCH = pd.Timestamp("1950-01-01")

# Optional biogeochemical variables. Core Argo files do not contain them.
OPTIONAL_VARS = {
    "doxy": ["DOXY_ADJUSTED", "DOXY"],
    "chla": ["CHLA_ADJUSTED", "CHLA"],
    "ph": ["PH_IN_SITU_TOTAL_ADJUSTED", "PH_IN_SITU_TOTAL"],
    "bbp": ["BBP700_ADJUSTED", "BBP700"],
}


class ArgoDataProcessor:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir or DATA_PROCESSING_CONFIG["data_dir"]
        self.db_manager = DatabaseManager()
        self.vector_store = VectorStoreManager()

    # ------------------------------------------------------------------
    # Low level helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_if_bytes(value):
        """Safely turn a NetCDF char/bytes value into a clean string."""
        try:
            if isinstance(value, np.ndarray):
                value = value.item() if value.ndim == 0 else value[0]
        except Exception:
            pass
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8").strip()
            except UnicodeDecodeError:
                return value.decode("latin-1").strip()
        return str(value).strip()

    @staticmethod
    def _convert_time(val):
        """
        Convert a scalar JULD value (days since 1950-01-01) to a Timestamp.

        Accepts python floats, numpy scalars and 0-d numpy arrays. The previous
        implementation checked type(val) which is ndarray for 0-d arrays and so
        silently produced NaT for every profile.
        """
        try:
            if isinstance(val, np.ndarray):
                if val.size != 1:
                    return pd.NaT
                val = val.item()
            if val is None:
                return pd.NaT
            numeric = float(val)
            if np.isnan(numeric):
                return pd.NaT
            return ARGO_EPOCH + pd.to_timedelta(numeric, unit="D")
        except (TypeError, ValueError):
            return pd.NaT

    @staticmethod
    def _first_available(ds, candidates):
        for name in candidates:
            if name in ds.variables:
                return ds[name].values
        return None

    def _extract_metadata(self, ds, float_id_str, profile_index=0):
        """Build the metadata row for one specific float inside the file."""
        try:
            params = sorted({str(var) for var in ds.data_vars if "_ADJUSTED" in str(var)})

            def _scalar(name):
                if name not in ds.variables:
                    return "Unknown"
                values = ds[name].values
                try:
                    return self._decode_if_bytes(values[profile_index])
                except (IndexError, TypeError):
                    return self._decode_if_bytes(values)

            metadata = {
                "float_id": float_id_str,
                "wmo_id": _scalar("WMO_INST_TYPE"),
                "project_name": _scalar("PROJECT_NAME"),
                "institution": str(ds.attrs.get("institution", "Unknown")).strip(),
                "date_launched": str(ds["LAUNCH_DATE"].values)
                if "LAUNCH_DATE" in ds.variables
                else "N/A",
                "parameters": params,
            }
            return metadata
        except Exception as e:
            logger.error(f"Could not extract metadata for float {float_id_str}: {e}")
            return None

    @staticmethod
    def _generate_metadata_summary(metadata):
        if not metadata:
            return None
        parameters = metadata.get("parameters") or []
        return (
            f"ARGO float ID {metadata['float_id']} from the "
            f"{metadata.get('project_name', 'Unknown')} project, managed by "
            f"{metadata.get('institution', 'Unknown')}. It measures parameters "
            f"including: {', '.join(parameters) if parameters else 'temperature, salinity, pressure'}."
        )

    # ------------------------------------------------------------------
    # File level processing
    # ------------------------------------------------------------------
    def process_netcdf_file(self, file_path):
        """
        Parse one *_prof.nc file.

        Returns a list of (DataFrame, metadata) pairs - one entry per distinct
        float found in the file. Returns [] when nothing usable is present.
        """
        try:
            with xr.open_dataset(file_path, decode_times=False) as ds:
                required = [
                    "PLATFORM_NUMBER",
                    "JULD",
                    "LATITUDE",
                    "LONGITUDE",
                    "PRES_ADJUSTED",
                    "TEMP_ADJUSTED",
                    "PSAL_ADJUSTED",
                ]
                missing = [name for name in required if name not in ds.variables]
                if missing:
                    logger.error(
                        f"{os.path.basename(file_path)} is missing variables: {missing}"
                    )
                    return []

                platform_numbers = ds["PLATFORM_NUMBER"].values
                juld_array = ds["JULD"].values
                lat_array = ds["LATITUDE"].values
                lon_array = ds["LONGITUDE"].values
                cycle_array = (
                    ds["CYCLE_NUMBER"].values
                    if "CYCLE_NUMBER" in ds.variables
                    else np.zeros(ds.sizes["N_PROF"])
                )

                pres_array = ds["PRES_ADJUSTED"].values
                temp_array = ds["TEMP_ADJUSTED"].values
                sal_array = ds["PSAL_ADJUSTED"].values

                # Real-time profiles often have empty *_ADJUSTED slices. Keep the
                # adjusted values as the preferred source but fall back to the raw
                # variables per profile so those floats are not silently dropped.
                pres_raw = ds["PRES"].values if "PRES" in ds.variables else None
                temp_raw = ds["TEMP"].values if "TEMP" in ds.variables else None
                sal_raw = ds["PSAL"].values if "PSAL" in ds.variables else None

                optional_arrays = {
                    key: self._first_available(ds, names)
                    for key, names in OPTIONAL_VARS.items()
                }

                # ds.sizes replaces the deprecated ds.dims mapping.
                num_profiles = ds.sizes["N_PROF"]
                num_levels = ds.sizes["N_LEVELS"]

                records = []
                for i in range(num_profiles):
                    profile_time = self._convert_time(juld_array[i])
                    if pd.isna(profile_time):
                        logger.debug(f"Skipping profile {i}: invalid timestamp.")
                        continue

                    # Each profile belongs to its own platform.
                    float_id = self._decode_if_bytes(platform_numbers[i])
                    if not float_id or float_id.lower() in ("nan", "none", ""):
                        continue

                    try:
                        lat_value = float(lat_array[i])
                        lon_value = float(lon_array[i])
                    except (TypeError, ValueError):
                        continue
                    if np.isnan(lat_value) or np.isnan(lon_value):
                        continue

                    try:
                        cycle_number = int(cycle_array[i])
                    except (TypeError, ValueError):
                        cycle_number = None

                    pres_slice = pres_array[i]
                    temp_slice = temp_array[i]
                    sal_slice = sal_array[i]

                    if (
                        np.all(np.isnan(temp_slice))
                        and temp_raw is not None
                        and pres_raw is not None
                        and sal_raw is not None
                    ):
                        pres_slice = pres_raw[i]
                        temp_slice = temp_raw[i]
                        sal_slice = sal_raw[i]

                    for j in range(num_levels):
                        pres_val = pres_slice[j]
                        temp_val = temp_slice[j]
                        sal_val = sal_slice[j]

                        if np.isnan(pres_val) or np.isnan(temp_val) or np.isnan(sal_val):
                            continue

                        record = {
                            "float_id": float_id,
                            "profile_number": cycle_number,
                            "time": profile_time,
                            "lat": lat_value,
                            "lon": lon_value,
                            "depth": float(pres_val),
                            "temperature": float(temp_val),
                            "salinity": float(sal_val),
                        }

                        for key, array in optional_arrays.items():
                            value = None
                            if array is not None and array.ndim == 2:
                                candidate = array[i, j]
                                if not np.isnan(candidate):
                                    value = float(candidate)
                            record[key] = value

                        records.append(record)

                if not records:
                    logger.warning(
                        f"No valid measurements in {os.path.basename(file_path)}."
                    )
                    return []

                df = pd.DataFrame(records)
                # JULD is a float day count, so round off sub-second noise.
                df["time"] = pd.to_datetime(df["time"]).dt.round("s")
                for optional_column in OPTIONAL_VARS:
                    df[optional_column] = pd.to_numeric(
                        df[optional_column], errors="coerce"
                    )

                decoded_platforms = [
                    self._decode_if_bytes(p) for p in platform_numbers
                ]

                results = []
                for float_id, group_df in df.groupby("float_id", sort=False):
                    try:
                        first_index = decoded_platforms.index(float_id)
                    except ValueError:
                        first_index = 0
                    metadata = self._extract_metadata(ds, float_id, first_index)
                    if metadata:
                        results.append((group_df.reset_index(drop=True), metadata))

                logger.info(
                    f"{os.path.basename(file_path)}: {len(df)} measurements "
                    f"across {len(results)} floats."
                )
                return results

        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            return []

    # ------------------------------------------------------------------
    # Directory level processing
    # ------------------------------------------------------------------
    def process_directory(self, max_files=None, reset=True):
        """
        Ingest every *.nc file in the data directory.

        reset=True (default) clears BOTH the SQL database and the Chroma vector
        store first, so the two never drift apart.
        """
        stats = {
            "files_found": 0,
            "files_processed": 0,
            "floats_inserted": 0,
            "records_inserted": 0,
            "errors": [],
        }

        if max_files is None:
            max_files = DATA_PROCESSING_CONFIG.get("max_files")

        if reset:
            logger.info("Preparing to process new data. Clearing old data first...")
            if not self.db_manager.reset_database():
                stats["errors"].append("SQL database reset failed.")
            if not self.vector_store.reset_vector_store():
                stats["errors"].append("Vector store reset failed.")
        else:
            self.db_manager.ensure_ready()

        pattern = os.path.join(self.data_dir, "*.nc")
        nc_files = sorted(glob.glob(pattern))
        stats["files_found"] = len(nc_files)

        if not nc_files:
            message = f"No NetCDF files found in {os.path.abspath(self.data_dir)}"
            logger.warning(message)
            stats["errors"].append(message)
            return stats

        if max_files:
            nc_files = nc_files[:max_files]

        logger.info(f"Found {stats['files_found']} NetCDF files, processing {len(nc_files)}.")

        for file_path in nc_files:
            results = self.process_netcdf_file(file_path)
            if not results:
                stats["errors"].append(
                    f"No usable data in {os.path.basename(file_path)}"
                )
                continue

            file_ok = False
            for df, metadata in results:
                if df is None or df.empty or not metadata:
                    continue

                if self.db_manager.insert_argo_data(df, metadata):
                    stats["floats_inserted"] += 1
                    stats["records_inserted"] += len(df)
                    file_ok = True

                    summary_text = self._generate_metadata_summary(metadata)
                    self.vector_store.add_document(
                        doc_id=metadata["float_id"],
                        document=summary_text,
                        metadata={
                            "float_id": metadata["float_id"],
                            "project_name": str(metadata.get("project_name", "")),
                            "institution": str(metadata.get("institution", "")),
                        },
                    )
                else:
                    stats["errors"].append(
                        f"Insert failed for float {metadata['float_id']}"
                    )

            if file_ok:
                stats["files_processed"] += 1

        logger.info(
            f"Processing complete. Files: {stats['files_processed']}/{len(nc_files)}, "
            f"floats: {stats['floats_inserted']}, rows: {stats['records_inserted']}."
        )
        return stats


if __name__ == "__main__":
    processor = ArgoDataProcessor()
    print(processor.process_directory())
