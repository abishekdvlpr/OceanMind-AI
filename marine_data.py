# --- marine_data.py ---
"""
OceanMind AI - Fisheries and Molecular Biodiversity domains (SIH25041).

DESIGN CONTRACT - read before modifying:

1. This module is PURELY ADDITIVE. It never imports from, modifies, or drops
   anything owned by database_manager.Base. The ARGO pipeline is untouched.

2. It declares its own DeclarativeBase (MarineBase). This is deliberate and
   load-bearing: DatabaseManager.reset_database() calls Base.metadata.drop_all(),
   so registering these tables on the ARGO Base would mean every ARGO re-ingest
   silently wiped the fisheries and eDNA data.

3. Both tables carry a `data_source` column. Rows seeded here are marked
   'representative' so the provenance of every record is auditable in SQL and
   surfaced in the UI. Real CMLRE / OBIS extracts can be loaded alongside with
   data_source set accordingly - no schema change required.

Public interface:
    MarineDataManager()
        .initialize()            -> bool
        .reset()                 -> bool
        .seed(reset=True)        -> dict stats
        .tables_present()        -> dict[str, bool]
        .get_schema_description()-> str   (appended to the LLM prompt)
        .get_summary()           -> dict

CLI:
    python marine_data.py            # create tables and seed
    python marine_data.py --no-reset # append without wiping
"""

import argparse
import logging
import random
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import USE_SQLITE, get_db_url

# OBIS access lives in its own module so this file stays a persistence layer.
try:
    import obis_client
except Exception:  # pragma: no cover - degrades to fisheries-only
    obis_client = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Geometry column mirrors the ARGO convention so PostGIS joins behave identically.
if not USE_SQLITE:
    from geoalchemy2 import Geometry

    def _geom_column():
        return sa.Column(
            Geometry(geometry_type="POINT", srid=4326), index=True, nullable=True
        )
else:  # offline fallback
    def _geom_column():
        return sa.Column(sa.Text, nullable=True)


class MarineBase(DeclarativeBase):
    """Isolated metadata namespace - see design contract note 2."""
    pass


class FisheriesLanding(MarineBase):
    __tablename__ = "fisheries_landings"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    zone_name = sa.Column(sa.String, index=True)      # CMLRE-style fishing zone
    state = sa.Column(sa.String, index=True)
    lat = sa.Column(sa.Float)                          # zone centroid
    lon = sa.Column(sa.Float)
    landing_date = sa.Column(sa.Date, index=True)
    species_common = sa.Column(sa.String, index=True)
    species_scientific = sa.Column(sa.String)
    gear_type = sa.Column(sa.String, index=True)
    catch_tonnes = sa.Column(sa.Float)
    effort_hours = sa.Column(sa.Float)
    vessels = sa.Column(sa.Integer)
    data_source = sa.Column(sa.String, index=True)
    geom = _geom_column()


class BiodiversityOccurrence(MarineBase):
    """
    Real marine biodiversity occurrences harvested from the OBIS Occurrence API.

    Replaces the former representative `edna_samples` table. Every row here
    originates from a published OBIS dataset; nothing is generated. The eight
    required reporting fields are the first eight columns.
    """

    __tablename__ = "biodiversity_occurrences"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)

    # --- required reporting fields ---
    occurrence_id = sa.Column(sa.String, index=True)   # provider occurrenceID
    scientific_name = sa.Column(sa.String, index=True)
    accepted_name = sa.Column(sa.String, index=True)   # WoRMS-accepted species
    latitude = sa.Column(sa.Float)
    longitude = sa.Column(sa.Float)
    event_date = sa.Column(sa.Date, index=True)
    depth = sa.Column(sa.Float)                        # metres
    source = sa.Column(sa.String, index=True)          # institution / dataset

    # --- provenance ---
    obis_id = sa.Column(sa.String, index=True)         # OBIS record UUID
    dataset_id = sa.Column(sa.String)
    dataset_name = sa.Column(sa.String)
    license = sa.Column(sa.String)                     # per-record CC licence
    basis_of_record = sa.Column(sa.String)

    # --- taxonomy ---
    aphia_id = sa.Column(sa.Integer, index=True)
    taxon_rank = sa.Column(sa.String)
    kingdom = sa.Column(sa.String, index=True)
    phylum = sa.Column(sa.String, index=True)
    class_name = sa.Column(sa.String)
    order_name = sa.Column(sa.String)
    family = sa.Column(sa.String, index=True)
    genus = sa.Column(sa.String, index=True)
    vernacular_name = sa.Column(sa.String)             # common name if provided

    # --- molecular biodiversity (eDNA-derived records) ---
    is_dna_derived = sa.Column(sa.Boolean, index=True)
    marker_gene = sa.Column(sa.String, index=True)     # COI / 16S / 18S / 12S
    sequence_id = sa.Column(sa.String)                 # ENA / SRA accession
    read_count = sa.Column(sa.Integer)

    # --- OBIS environmental enrichment (independent of ARGO) ---
    sst = sa.Column(sa.Float)                          # satellite-derived SST
    sss = sa.Column(sa.Float)
    bathymetry = sa.Column(sa.Float)
    shore_distance_m = sa.Column(sa.Float)

    # --- housekeeping ---
    event_year = sa.Column(sa.Integer, index=True)
    region_label = sa.Column(sa.String, index=True)    # search area used
    ingested_at = sa.Column(sa.DateTime)

    geom = _geom_column()


# =========================================================================
# Representative seed data
# =========================================================================
# Zones deliberately overlap the ingested ARGO footprint (Arabian Sea and Bay of
# Bengal) so that cross-domain spatial joins return non-empty results.
FISHING_ZONES = [
    ("Kochi Offshore",       "Kerala",         9.95, 75.60),
    ("Mangaluru Shelf",      "Karnataka",     12.90, 74.20),
    ("Ratnagiri Bank",       "Maharashtra",   16.95, 72.60),
    ("Veraval Grounds",      "Gujarat",       20.60, 70.10),
    ("Lakshadweep Sea",      "Lakshadweep",   11.20, 72.00),
    ("Chennai Coastal",      "Tamil Nadu",    13.05, 80.50),
    ("Visakhapatnam Shelf",  "Andhra Pradesh",17.70, 83.60),
    ("Paradip Grounds",      "Odisha",        20.20, 86.90),
]

SPECIES = [
    ("Indian Oil Sardine",  "Sardinella longiceps", 0.30),
    ("Indian Mackerel",     "Rastrelliger kanagurta", 0.22),
    ("Bombay Duck",         "Harpadon nehereus", 0.10),
    ("Penaeid Shrimp",      "Penaeus indicus", 0.12),
    ("Yellowfin Tuna",      "Thunnus albacares", 0.08),
    ("Ribbonfish",          "Trichiurus lepturus", 0.10),
    ("Indian Squid",        "Uroteuthis duvaucelii", 0.08),
]

GEAR = ["Trawl Net", "Gillnet", "Purse Seine", "Hooks and Line", "Ring Seine"]

SEED_START = date(2024, 1, 1)   # aligned with the ingested ARGO window
SEED_DAYS = 5


class MarineDataManager:
    def __init__(self, db_url=None):
        self.db_url = db_url or get_db_url()
        self.engine = create_engine(self.db_url, pool_pre_ping=True, future=True)
        self.Session = sessionmaker(bind=self.engine)
        self.is_postgres = self.engine.dialect.name == "postgresql"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def initialize(self):
        try:
            if self.is_postgres:
                with self.engine.connect() as conn:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
                    conn.commit()
            MarineBase.metadata.create_all(self.engine)
            logger.info("Marine domain tables initialized.")
            return True
        except Exception as e:
            logger.error(f"Could not initialize marine tables: {e}")
            return False

    def reset(self, tables=None):
        """
        Drop marine domain tables. Never touches ARGO.

        `tables` limits the reset to a subset, so re-seeding fisheries cannot
        destroy harvested OBIS biodiversity records and vice versa.
        """
        try:
            logger.warning(f"--- RESETTING MARINE TABLES: {tables or 'all'} ---")
            if tables:
                targets = [MarineBase.metadata.tables[t]
                           for t in tables if t in MarineBase.metadata.tables]
                MarineBase.metadata.drop_all(self.engine, tables=targets,
                                             checkfirst=True)
            else:
                MarineBase.metadata.drop_all(self.engine, checkfirst=True)
            self.initialize()
            return True
        except Exception as e:
            logger.error(f"Marine reset failed: {e}")
            return False

    def tables_present(self):
        try:
            inspector = inspect(self.engine)
            return {
                "fisheries_landings": inspector.has_table("fisheries_landings"),
                "biodiversity_occurrences": inspector.has_table("biodiversity_occurrences"),
            }
        except Exception:
            return {"fisheries_landings": False, "biodiversity_occurrences": False}

    def ensure_ready(self):
        present = self.tables_present()
        if not all(present.values()):
            return self.initialize()
        return True

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------
    def _build_fisheries(self, rng):
        rows = []
        for day_offset in range(SEED_DAYS):
            landing_day = SEED_START + timedelta(days=day_offset)
            for zone, state, lat, lon in FISHING_ZONES:
                for common, scientific, share in SPECIES:
                    if rng.random() > 0.72:      # not every species lands daily
                        continue
                    # Warmer, shallower western shelf lands more pelagics
                    base = 42.0 * share * (1.25 if lon < 78 else 0.85)
                    catch = round(max(rng.gauss(base, base * 0.28), 0.4), 2)
                    effort = round(rng.uniform(60, 340), 1)
                    rows.append({
                        "zone_name": zone,
                        "state": state,
                        "lat": lat + rng.uniform(-0.12, 0.12),
                        "lon": lon + rng.uniform(-0.12, 0.12),
                        "landing_date": landing_day,
                        "species_common": common,
                        "species_scientific": scientific,
                        "gear_type": rng.choice(GEAR),
                        "catch_tonnes": catch,
                        "effort_hours": effort,
                        "vessels": rng.randint(4, 48),
                        "data_source": "representative",
                    })
        return pd.DataFrame(rows)

    def seed(self, reset=True, seed_value=20260101):
        """
        Seed the FISHERIES domain only.

        Biodiversity is no longer seeded here: it is harvested from the live
        OBIS API by ingest_biodiversity(). Fisheries behaviour is unchanged.
        """
        stats = {"fisheries_rows": 0, "errors": []}
        rng = random.Random(seed_value)

        if reset:
            if not self.reset(tables=["fisheries_landings"]):
                stats["errors"].append("Fisheries reset failed.")
                return stats
        else:
            self.ensure_ready()

        try:
            fisheries = self._build_fisheries(rng)
            fisheries.to_sql("fisheries_landings", self.engine,
                             if_exists="append", index=False, chunksize=2000)
            stats["fisheries_rows"] = len(fisheries)
            if self.is_postgres:
                self._populate_geometry(["fisheries_landings"])
            logger.info(f"Seeded {stats['fisheries_rows']} fisheries landings.")
        except Exception as e:
            logger.error(f"Fisheries seed failed: {e}")
            stats["errors"].append(str(e))
        return stats

    # ------------------------------------------------------------------
    # Biodiversity ingestion (real OBIS data)
    # ------------------------------------------------------------------
    def ingest_biodiversity(self, area=None, lat=None, lon=None,
                            radius_km=150.0, scientific_name=None,
                            polygon=None, float_positions=None,
                            max_records=None, replace=False, refresh=False):
        """
        Harvest real occurrences from OBIS and store them.

        Exactly one search mode should be supplied:
            area="Bay of Bengal" | "Tamil Nadu" | "Chennai"
            lat=13.08, lon=80.27, radius_km=150
            scientific_name="Sardinella longiceps"
            polygon="POLYGON ((...))"
            float_positions=[(lat, lon), ...]   # ARGO neighbourhood

        Returns a stats dict including `source`, which is 'live', 'cache' or
        'unavailable'. Nothing is written when no records are returned, so a
        failed fetch can never silently replace real data with nothing.
        """
        stats = {"requested": None, "fetched": 0, "inserted": 0,
                 "source": "unavailable", "error": None, "region_label": None,
                 "fetched_at": None, "total_available": None}

        if obis_client is None:
            stats["error"] = ("obis_client module is unavailable; install "
                              "requests and place obis_client.py in the project root.")
            return stats

        self.ensure_ready()
        client = obis_client.ObisClient()

        try:
            if float_positions:
                stats["requested"] = "argo_neighbourhood"
                records, meta = client.fetch_around_argo_floats(
                    float_positions, radius_km=radius_km, refresh=refresh)
            elif polygon:
                stats["requested"] = "polygon"
                records, meta = client.fetch_by_polygon(
                    polygon, max_records=max_records, refresh=refresh)
            elif scientific_name:
                stats["requested"] = f"species:{scientific_name}"
                geometry = None
                if area:
                    resolved = obis_client.resolve_area(area)
                    geometry = resolved[0] if resolved else None
                records, meta = client.fetch_by_scientific_name(
                    scientific_name, geometry=geometry,
                    max_records=max_records, refresh=refresh)
            elif lat is not None and lon is not None:
                stats["requested"] = f"point:{lat},{lon}"
                records, meta = client.fetch_by_point(
                    lat, lon, radius_km=radius_km,
                    max_records=max_records, refresh=refresh)
            elif area:
                stats["requested"] = f"area:{area}"
                records, meta = client.fetch_by_place(
                    area, max_records=max_records, refresh=refresh)
            else:
                stats["error"] = "Specify area, coordinates, species, polygon or float positions."
                return stats
        except Exception as e:
            logger.error(f"OBIS fetch failed: {e}")
            stats["error"] = str(e)
            return stats

        stats.update({
            "fetched": len(records),
            "source": meta.get("source", "unavailable"),
            "error": meta.get("error"),
            "region_label": meta.get("region_label"),
            "fetched_at": meta.get("fetched_at"),
            "total_available": meta.get("total_available"),
        })

        if not records:
            return stats

        try:
            frame = pd.DataFrame(records)
            for column in ("distance_km",):
                if column in frame.columns:
                    frame = frame.drop(columns=[column])
            frame["event_date"] = pd.to_datetime(
                frame["event_date"], errors="coerce").dt.date
            frame["ingested_at"] = datetime.utcnow()

            model_columns = {c.name for c in BiodiversityOccurrence.__table__.columns}
            frame = frame[[c for c in frame.columns if c in model_columns]]

            if replace:
                with self.engine.connect() as conn:
                    conn.execute(text("DELETE FROM biodiversity_occurrences"))
                    conn.commit()

            frame.to_sql("biodiversity_occurrences", self.engine,
                         if_exists="append", index=False, chunksize=2000)
            stats["inserted"] = len(frame)

            if self.is_postgres:
                self._populate_geometry(["biodiversity_occurrences"])
            logger.info(
                f"Inserted {stats['inserted']} OBIS occurrences "
                f"(source={stats['source']})."
            )
        except Exception as e:
            logger.error(f"Biodiversity insert failed: {e}")
            stats["error"] = str(e)
        return stats

    def _populate_geometry(self, tables=None):
        for table in (tables or ["fisheries_landings", "biodiversity_occurrences"]):
            try:
                with self.engine.connect() as conn:
                    lon_col, lat_col = (
                        ("longitude", "latitude")
                        if table == "biodiversity_occurrences" else ("lon", "lat")
                    )
                    conn.execute(text(
                        f"UPDATE {table} "
                        f"SET geom = ST_SetSRID(ST_MakePoint({lon_col}, {lat_col}), 4326) "
                        f"WHERE geom IS NULL AND {lon_col} IS NOT NULL "
                        f"AND {lat_col} IS NOT NULL;"
                    ))
                    conn.commit()
            except Exception as e:
                logger.error(f"Geometry population failed for {table}: {e}")

    # ------------------------------------------------------------------
    # Prompt support
    # ------------------------------------------------------------------
    def get_schema_description(self):
        """
        Returned only for tables that actually exist, so the LLM is never told
        about a table it cannot query.
        """
        present = self.tables_present()
        blocks = []

        if present.get("fisheries_landings"):
            blocks.append(
                "TABLE fisheries_landings(\n"
                "  id integer PRIMARY KEY,\n"
                "  zone_name text,          -- e.g. 'Kochi Offshore'\n"
                "  state text,              -- Indian coastal state\n"
                "  lat double precision, lon double precision,  -- zone centroid\n"
                "  landing_date date,\n"
                "  species_common text,     -- e.g. 'Indian Oil Sardine'\n"
                "  species_scientific text, -- e.g. 'Sardinella longiceps'\n"
                "  gear_type text,          -- Trawl Net, Gillnet, Purse Seine, ...\n"
                "  catch_tonnes double precision,\n"
                "  effort_hours double precision,\n"
                "  vessels integer,\n"
                "  data_source text,        -- 'representative' for seeded rows\n"
                "  geom geometry(Point,4326)\n"
                ")"
            )

        if present.get("biodiversity_occurrences"):
            blocks.append(
                "TABLE biodiversity_occurrences(   -- REAL data from the OBIS API\n"
                "  id integer PRIMARY KEY,\n"
                "  occurrence_id text,      -- provider occurrenceID\n"
                "  scientific_name text,    -- as recorded\n"
                "  accepted_name text,      -- WoRMS-accepted species name\n"
                "  latitude double precision, longitude double precision,\n"
                "  event_date date,         -- observation date, may be NULL\n"
                "  depth double precision,  -- metres, may be NULL\n"
                "  source text,             -- institution or dataset\n"
                "  dataset_name text, license text, basis_of_record text,\n"
                "  aphia_id integer, taxon_rank text,\n"
                "  kingdom text, phylum text, class_name text, order_name text,\n"
                "  family text, genus text,\n"
                "  vernacular_name text,    -- common name when provided\n"
                "  is_dna_derived boolean,  -- true for eDNA / sequence records\n"
                "  marker_gene text,        -- COI, 16S rRNA, 18S rRNA, 12S rRNA\n"
                "  sequence_id text, read_count integer,\n"
                "  sst double precision,    -- OBIS satellite SST at the record\n"
                "  sss double precision,\n"
                "  bathymetry double precision, shore_distance_m double precision,\n"
                "  event_year integer, region_label text,\n"
                "  geom geometry(Point,4326)\n"
                ")"
            )
        return "\n".join(blocks)

    def get_summary(self):
        summary = {
            "available": False, "fisheries_rows": 0, "biodiversity_rows": 0,
            "species_count": 0, "species_observed": 0, "dna_records": 0,
            "data_providers": 0, "year_min": None, "year_max": None,
            "total_catch_tonnes": 0.0, "zones": 0,
        }
        present = self.tables_present()
        if not any(present.values()):
            return summary
        try:
            with self.engine.connect() as conn:
                if present.get("fisheries_landings"):
                    row = conn.execute(text(
                        "SELECT COUNT(*) n, COUNT(DISTINCT species_common) s, "
                        "COUNT(DISTINCT zone_name) z, SUM(catch_tonnes) c "
                        "FROM fisheries_landings")).mappings().first()
                    summary["fisheries_rows"] = row["n"] or 0
                    summary["species_count"] = row["s"] or 0
                    summary["zones"] = row["z"] or 0
                    summary["total_catch_tonnes"] = float(row["c"] or 0)
                if present.get("biodiversity_occurrences"):
                    row = conn.execute(text(
                        "SELECT COUNT(*) n, COUNT(DISTINCT accepted_name) s, "
                        "COUNT(DISTINCT source) src, MIN(event_year) y0, "
                        "MAX(event_year) y1 FROM biodiversity_occurrences"
                    )).mappings().first()
                    summary["biodiversity_rows"] = row["n"] or 0
                    summary["species_observed"] = row["s"] or 0
                    summary["data_providers"] = row["src"] or 0
                    summary["year_min"] = row["y0"]
                    summary["year_max"] = row["y1"]
                    row = conn.execute(text(
                        "SELECT COUNT(*) d FROM biodiversity_occurrences "
                        "WHERE is_dna_derived = TRUE"
                    )).mappings().first()
                    summary["dna_records"] = row["d"] or 0
            summary["available"] = bool(
                summary["fisheries_rows"] or summary["biodiversity_rows"]
            )
        except Exception as e:
            logger.error(f"Marine summary failed: {e}")
        return summary


def main():
    parser = argparse.ArgumentParser(
        description="Seed fisheries and harvest real OBIS biodiversity records."
    )
    parser.add_argument("--no-reset", action="store_true",
                        help="Append instead of dropping the fisheries table first.")
    parser.add_argument("--skip-fisheries", action="store_true",
                        help="Do not touch the fisheries table.")
    parser.add_argument("--biodiversity", action="store_true",
                        help="Harvest biodiversity occurrences from OBIS.")
    parser.add_argument("--area", default="Bay of Bengal",
                        help="Place, state or region name (e.g. 'Chennai', 'Tamil Nadu').")
    parser.add_argument("--lat", type=float, help="Latitude for a point search.")
    parser.add_argument("--lon", type=float, help="Longitude for a point search.")
    parser.add_argument("--radius-km", type=float, default=150.0)
    parser.add_argument("--species", help="Scientific name filter.")
    parser.add_argument("--max-records", type=int, default=5000)
    parser.add_argument("--replace", action="store_true",
                        help="Clear biodiversity_occurrences before inserting.")
    parser.add_argument("--refresh", action="store_true",
                        help="Bypass the local cache and re-query OBIS.")
    parser.add_argument("--cache-status", action="store_true",
                        help="Show what is available offline, then exit.")
    args = parser.parse_args()

    print("=" * 62)
    print("   OceanMind AI - Marine Domain Loader (SIH25041)")
    print("=" * 62)

    if args.cache_status:
        if obis_client is None:
            print("   obis_client unavailable.")
            return 1
        status = obis_client.ObisClient().cache_status()
        print(f"   Cache directory : {status['cache_dir']}")
        print(f"   Cached records  : {status['total_records']:,}")
        for entry in status["entries"]:
            print(f"     - {entry['count']:>6,} records  {entry['fetched_at']}")
        return 0

    manager = MarineDataManager()

    if not args.skip_fisheries:
        stats = manager.seed(reset=not args.no_reset)
        print(f"   Fisheries landings : {stats['fisheries_rows']:,}")
        for problem in stats["errors"]:
            print(f"   ERROR: {problem}")

    if args.biodiversity:
        print("\n-> Harvesting biodiversity occurrences from OBIS...")
        bio = manager.ingest_biodiversity(
            area=None if (args.lat is not None and args.lon is not None) else args.area,
            lat=args.lat, lon=args.lon, radius_km=args.radius_km,
            scientific_name=args.species, max_records=args.max_records,
            replace=args.replace, refresh=args.refresh,
        )
        print(f"   Search           : {bio['requested']}")
        print(f"   Region           : {bio['region_label']}")
        print(f"   Data source      : {bio['source'].upper()}")
        if bio.get("total_available"):
            print(f"   Available in OBIS: {bio['total_available']:,}")
        print(f"   Records fetched  : {bio['fetched']:,}")
        print(f"   Records inserted : {bio['inserted']:,}")
        if bio["error"]:
            print(f"   NOTE: {bio['error']}")

    s = manager.get_summary()
    print("\n   DATABASE SUMMARY")
    print(f"     Fisheries rows     : {s['fisheries_rows']:,}")
    print(f"     Fisheries species  : {s['species_count']}   zones: {s['zones']}")
    print(f"     Biodiversity rows  : {s['biodiversity_rows']:,}")
    print(f"     Species observed   : {s['species_observed']:,}")
    print(f"     DNA-derived records: {s['dna_records']:,}")
    print(f"     Data providers     : {s['data_providers']:,}")
    if s.get("year_min"):
        print(f"     Observation years  : {s['year_min']} - {s['year_max']}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
