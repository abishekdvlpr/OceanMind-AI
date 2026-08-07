# --- obis_client.py ---
"""
OceanMind AI - client for the OBIS (Ocean Biodiversity Information System)
Occurrence API.

    https://api.obis.org/v3/occurrence

DESIGN CONTRACT
---------------
1. PURE DATA ACCESS. This module knows nothing about SQLAlchemy, Streamlit or
   the ARGO pipeline. It fetches, normalises and caches. Nothing else.
2. NEVER FABRICATES. If the network is unavailable and no cache exists, it
   returns an empty list and reports the reason. It never invents records.
3. CACHE-FIRST OFFLINE. Every successful response is written to disk keyed by a
   hash of the query. On a network failure the cache is served transparently so
   a live demo survives a dropped connection.
4. Field names below were verified against a real OBIS API response, not from
   documentation.

Search modes (requirement: place / coordinates / scientific name):
    fetch_by_place("Chennai")                  -> gazetteer -> radius polygon
    fetch_by_point(13.08, 80.27, radius_km=150)
    fetch_by_polygon("POLYGON ((...))")
    fetch_by_scientific_name("Sardinella longiceps")
    fetch_around_argo_floats([(lat, lon), ...])

Public interface:
    ObisClient(cache_dir=None, timeout=None)
        .fetch(...)                 -> (records, meta)
        .fetch_by_place(...)        -> (records, meta)
        .fetch_by_point(...)        -> (records, meta)
        .fetch_by_polygon(...)      -> (records, meta)
        .fetch_by_scientific_name() -> (records, meta)
        .fetch_around_argo_floats() -> (records, meta)
        .cache_status()             -> dict
    normalise_record(raw)           -> flat dict matching the DB schema
    REGIONS / PLACES                -> named search areas
"""

import hashlib
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

try:
    from config import OBIS_CONFIG
except Exception:  # config predates this module
    OBIS_CONFIG = {
        "base_url": "https://api.obis.org/v3",
        "cache_dir": "./obis_cache",
        "timeout": 60,
        "page_size": 5000,
        "max_records": 20000,
        "user_agent": "OceanMind-AI/1.0 (SIH25041; marine data platform)",
        "retries": 3,
    }

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0088


# =========================================================================
# Named search areas
# =========================================================================
# Coastal reference points used to turn a place NAME into a search polygon.
PLACES = {
    "chennai": (13.08, 80.27), "madras": (13.08, 80.27),
    "mumbai": (19.07, 72.87), "bombay": (19.07, 72.87),
    "kochi": (9.93, 76.27), "cochin": (9.93, 76.27),
    "kolkata": (21.80, 88.20), "visakhapatnam": (17.69, 83.22),
    "vizag": (17.69, 83.22), "goa": (15.30, 73.91),
    "mangaluru": (12.91, 74.86), "mangalore": (12.91, 74.86),
    "thiruvananthapuram": (8.52, 76.94), "trivandrum": (8.52, 76.94),
    "puducherry": (11.94, 79.83), "pondicherry": (11.94, 79.83),
    "tuticorin": (8.76, 78.13), "rameswaram": (9.29, 79.31),
    "kanyakumari": (8.09, 77.54), "paradip": (20.32, 86.61),
    "veraval": (20.90, 70.37), "porbandar": (21.64, 69.61),
    "ratnagiri": (16.99, 73.30), "karwar": (14.81, 74.13),
    "kozhikode": (11.25, 75.78), "calicut": (11.25, 75.78),
    "nagapattinam": (10.77, 79.84), "port blair": (11.62, 92.73),
    "kavaratti": (10.57, 72.64), "digha": (21.63, 87.51),
    "mandapam": (9.28, 79.12), "vizhinjam": (8.38, 76.99),
}

# State-level search boxes (minlon, minlat, maxlon, maxlat)
STATES = {
    "tamil nadu": (77.5, 8.0, 81.5, 13.6),
    "tamilnadu": (77.5, 8.0, 81.5, 13.6),
    "kerala": (74.5, 8.0, 77.5, 12.9),
    "karnataka": (73.5, 12.6, 75.5, 15.1),
    "goa": (73.0, 14.8, 74.4, 15.9),
    "maharashtra": (71.5, 15.6, 73.8, 20.2),
    "gujarat": (68.0, 20.0, 73.0, 23.7),
    "andhra pradesh": (79.5, 13.5, 85.2, 19.2),
    "odisha": (84.5, 17.8, 87.6, 21.7),
    "orissa": (84.5, 17.8, 87.6, 21.7),
    "west bengal": (86.8, 20.6, 89.2, 22.6),
    "lakshadweep": (71.0, 8.0, 74.0, 12.5),
    "andaman": (92.0, 6.5, 94.5, 14.0),
}

# Large marine regions (minlon, minlat, maxlon, maxlat)
REGIONS = {
    "bay of bengal": (78.0, 5.0, 95.0, 22.5),
    "arabian sea": (55.0, 5.0, 78.0, 25.0),
    "laccadive sea": (70.0, 5.0, 78.0, 14.0),
    "andaman sea": (92.0, 5.0, 99.0, 17.0),
    "indian eez": (66.0, 5.0, 95.0, 24.5),
    "indian ocean": (30.0, -40.0, 120.0, 25.0),
}


# =========================================================================
# Geometry helpers
# =========================================================================
def bbox_to_wkt(min_lon, min_lat, max_lon, max_lat):
    """Closed counter-clockwise ring, the form the OBIS API expects."""
    return (
        f"POLYGON (({min_lon} {min_lat}, {min_lon} {max_lat}, "
        f"{max_lon} {max_lat}, {max_lon} {min_lat}, {min_lon} {min_lat}))"
    )


def point_to_wkt(lat, lon, radius_km=150.0):
    """
    Square search envelope around a point.

    A box rather than a circle is deliberate: OBIS filters server-side on the
    polygon, and an exact radius filter is applied afterwards in
    filter_by_radius() so the returned set is genuinely within radius_km.
    """
    lat_delta = radius_km / 111.32
    lon_delta = radius_km / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    return bbox_to_wkt(
        round(lon - lon_delta, 4), round(max(lat - lat_delta, -89.9), 4),
        round(lon + lon_delta, 4), round(min(lat + lat_delta, 89.9), 4),
    )


def haversine_km(lat1, lon1, lat2, lon2):
    try:
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dphi = p2 - p1
        dlam = math.radians(float(lon2) - float(lon1))
        a = (math.sin(dphi / 2) ** 2
             + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2)
        return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))
    except (TypeError, ValueError):
        return float("nan")


def resolve_area(name):
    """
    Turn a free-text area name into (wkt, label, kind).

    Resolution order runs most specific first: region, then state, then city.
    Returns None when nothing matches, so the caller can fall back.
    """
    if not name:
        return None
    key = str(name).strip().lower()

    for region, box in REGIONS.items():
        if region in key:
            return bbox_to_wkt(*box), region.title(), "region"
    for state, box in STATES.items():
        if state in key:
            return bbox_to_wkt(*box), state.title(), "state"
    for place, (lat, lon) in PLACES.items():
        if place in key:
            return point_to_wkt(lat, lon, 150.0), place.title(), "place"
    return None


# =========================================================================
# Record normalisation
# =========================================================================
def _to_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_event_date(raw):
    """
    OBIS eventDate is highly irregular: '2021-03-29', '1937',
    '2018-09-28/2019-01-28', '2016-01-11 13:01:48', ISO with offsets.
    Take the first parseable date and return an ISO date string, else None.
    """
    if not raw:
        return None
    text = str(raw).split("/")[0].strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt).date().isoformat()
        except ValueError:
            continue
    # Fall back to the epoch-millis field OBIS computes
    return None


def _marker_gene(raw):
    """
    Extract the marker gene from samplingProtocol.

    Real values observed: 'eDNA metabarcoding; 16S rRNA gene',
    'eDNA metabarcoding; 18S rRNA gene', 'acoustic detection'.
    """
    protocol = str(raw.get("samplingProtocol") or "")
    for marker in ("COI", "16S rRNA", "18S rRNA", "12S rRNA", "ITS", "rbcL"):
        if marker.lower() in protocol.lower():
            return marker
    return None


def normalise_record(raw, region_label=None):
    """
    Flatten one OBIS occurrence into the platform's biodiversity schema.

    Guarantees the eight required fields are always present as keys (values may
    be None where OBIS itself has no value):
        scientific_name, accepted_name, latitude, longitude,
        event_date, depth, occurrence_id, source
    """
    if not isinstance(raw, dict):
        return None

    lat = _to_float(raw.get("decimalLatitude"))
    lon = _to_float(raw.get("decimalLongitude"))
    if lat is None or lon is None:
        return None  # unusable without coordinates

    quantity_type = str(raw.get("organismQuantityType") or "")
    is_dna = bool(
        raw.get("associatedSequences")
        or "dna sequence" in quantity_type.lower()
        or "edna" in str(raw.get("samplingProtocol") or "").lower()
    )

    source = (
        raw.get("institutionCode")
        or raw.get("datasetName")
        or raw.get("rightsHolder")
        or "OBIS"
    )

    return {
        # --- the eight required fields ---
        "occurrence_id": str(raw.get("occurrenceID") or raw.get("id") or "")[:400] or None,
        "scientific_name": raw.get("scientificName"),
        "accepted_name": raw.get("species") or raw.get("scientificName"),
        "latitude": lat,
        "longitude": lon,
        "event_date": _parse_event_date(raw.get("eventDate")),
        "depth": _to_float(raw.get("depth")),
        "source": str(source)[:300],
        # --- provenance ---
        "obis_id": raw.get("id"),
        "dataset_id": raw.get("dataset_id"),
        "dataset_name": (str(raw.get("datasetName"))[:400] if raw.get("datasetName") else None),
        "license": raw.get("license"),
        "basis_of_record": raw.get("basisOfRecord"),
        # --- taxonomy ---
        "aphia_id": _to_int(raw.get("aphiaID")),
        "taxon_rank": raw.get("taxonRank"),
        "kingdom": raw.get("kingdom"),
        "phylum": raw.get("phylum"),
        "class_name": raw.get("class"),
        "order_name": raw.get("order"),
        "family": raw.get("family"),
        "genus": raw.get("genus"),
        "vernacular_name": raw.get("vernacularName"),
        # --- molecular biodiversity ---
        "is_dna_derived": is_dna,
        "marker_gene": _marker_gene(raw),
        "sequence_id": (str(raw.get("associatedSequences"))[:400]
                        if raw.get("associatedSequences") else None),
        "read_count": _to_int(raw.get("organismQuantity")) if is_dna else None,
        # --- OBIS environmental enrichment: lets biodiversity be compared
        #     against independently measured ARGO temperature/salinity ---
        "sst": _to_float(raw.get("sst")),
        "sss": _to_float(raw.get("sss")),
        "bathymetry": _to_float(raw.get("bathymetry")),
        "shore_distance_m": _to_float(raw.get("shoredistance")),
        # --- housekeeping ---
        "event_year": _to_int(raw.get("date_year")),
        "region_label": region_label,
    }


# =========================================================================
# Client
# =========================================================================
class ObisClient:
    def __init__(self, cache_dir=None, timeout=None, base_url=None):
        self.base_url = (base_url or OBIS_CONFIG.get("base_url", "https://api.obis.org/v3")).rstrip("/")
        self.cache_dir = cache_dir or OBIS_CONFIG.get("cache_dir", "./obis_cache")
        self.timeout = timeout or OBIS_CONFIG.get("timeout", 60)
        self.page_size = int(OBIS_CONFIG.get("page_size", 5000))
        self.max_records = int(OBIS_CONFIG.get("max_records", 20000))
        self.retries = int(OBIS_CONFIG.get("retries", 3))
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": OBIS_CONFIG.get("user_agent", "OceanMind-AI/1.0"),
            "Accept": "application/json",
        })
        os.makedirs(self.cache_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------
    def _cache_path(self, params):
        key = json.dumps(params, sort_keys=True)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        return os.path.join(self.cache_dir, f"obis_{digest}.json")

    def _write_cache(self, params, records):
        path = self._cache_path(params)
        payload = {
            "query": params,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "count": len(records),
            "records": records,
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            logger.info(f"Cached {len(records)} OBIS records -> {path}")
        except OSError as e:
            logger.warning(f"Could not write OBIS cache: {e}")

    def _read_cache(self, params):
        path = self._cache_path(params)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            logger.info(
                f"Serving {payload.get('count', 0)} OBIS records from cache "
                f"({payload.get('fetched_at')})"
            )
            return payload
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Unreadable OBIS cache {path}: {e}")
            return None

    def cache_status(self):
        """Summary of what is available offline."""
        entries = []
        try:
            for name in sorted(os.listdir(self.cache_dir)):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(self.cache_dir, name)
                try:
                    with open(path, encoding="utf-8") as handle:
                        payload = json.load(handle)
                    entries.append({
                        "file": name,
                        "count": payload.get("count", 0),
                        "fetched_at": payload.get("fetched_at"),
                        "query": payload.get("query", {}),
                    })
                except Exception:
                    continue
        except OSError:
            pass
        return {
            "cache_dir": os.path.abspath(self.cache_dir),
            "entries": entries,
            "total_records": sum(e["count"] for e in entries),
        }

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _request(self, params):
        url = f"{self.base_url}/occurrence?{urlencode(params)}"
        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 200:
                    return response.json(), None
                last_error = f"HTTP {response.status_code}"
                logger.warning(f"OBIS attempt {attempt}: {last_error}")
            except requests.RequestException as e:
                last_error = str(e)
                logger.warning(f"OBIS attempt {attempt} failed: {e}")
            if attempt < self.retries:
                time.sleep(min(2 ** attempt, 8))
        return None, last_error

    # ------------------------------------------------------------------
    # Core fetch
    # ------------------------------------------------------------------
    def fetch(self, geometry=None, scientificname=None, startdate=None,
              enddate=None, max_records=None, region_label=None,
              use_cache=True, refresh=False):
        """
        Fetch and normalise occurrences.

        Returns (records, meta) where meta reports exactly where the data came
        from - 'live', 'cache' or 'unavailable' - so the UI never implies
        freshness it does not have.
        """
        max_records = max_records or self.max_records
        query = {k: v for k, v in {
            "geometry": geometry,
            "scientificname": scientificname,
            "startdate": startdate,
            "enddate": enddate,
            "max_records": max_records,
        }.items() if v is not None}

        meta = {
            "source": "unavailable", "total_available": None,
            "fetched": 0, "error": None, "query": query,
            "region_label": region_label, "fetched_at": None,
        }

        if not geometry and not scientificname:
            meta["error"] = "Provide at least a geometry or a scientific name."
            return [], meta

        if use_cache and not refresh:
            cached = self._read_cache(query)
            if cached:
                records = cached.get("records", [])
                meta.update({
                    "source": "cache", "fetched": len(records),
                    "fetched_at": cached.get("fetched_at"),
                    "total_available": cached.get("count"),
                })
                return records, meta

        collected, after = [], None
        total_available = None

        while len(collected) < max_records:
            params = {"size": min(self.page_size, max_records - len(collected))}
            if geometry:
                params["geometry"] = geometry
            if scientificname:
                params["scientificname"] = scientificname
            if startdate:
                params["startdate"] = startdate
            if enddate:
                params["enddate"] = enddate
            if after:
                params["after"] = after

            payload, error = self._request(params)
            if payload is None:
                # Network failed. Fall back to cache rather than failing hard.
                cached = self._read_cache(query)
                if cached:
                    records = cached.get("records", [])
                    meta.update({
                        "source": "cache", "fetched": len(records),
                        "fetched_at": cached.get("fetched_at"),
                        "error": f"Live fetch failed ({error}); served cache.",
                    })
                    return records, meta
                meta["error"] = (
                    f"OBIS unavailable ({error}) and no cached extract exists "
                    f"for this query."
                )
                return [], meta

            if total_available is None:
                total_available = payload.get("total")

            results = payload.get("results") or []
            if not results:
                break

            for raw in results:
                normalised = normalise_record(raw, region_label=region_label)
                if normalised:
                    collected.append(normalised)

            after = results[-1].get("id")
            if not after or len(results) < params["size"]:
                break

        meta.update({
            "source": "live",
            "fetched": len(collected),
            "total_available": total_available,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
        if collected:
            self._write_cache(query, collected)
        return collected, meta

    # ------------------------------------------------------------------
    # Search modes
    # ------------------------------------------------------------------
    def fetch_by_polygon(self, wkt, **kwargs):
        return self.fetch(geometry=wkt, **kwargs)

    def fetch_by_place(self, name, radius_km=150.0, **kwargs):
        """Place name -> region / state / city envelope."""
        resolved = resolve_area(name)
        if resolved:
            wkt, label, _kind = resolved
        else:
            return [], {
                "source": "unavailable", "fetched": 0,
                "error": f"Unknown place '{name}'. Use coordinates instead.",
                "region_label": name, "query": {}, "total_available": None,
                "fetched_at": None,
            }
        kwargs.setdefault("region_label", label)
        return self.fetch(geometry=wkt, **kwargs)

    def fetch_by_point(self, lat, lon, radius_km=150.0, **kwargs):
        """Coordinates -> envelope, then an exact great-circle radius filter."""
        wkt = point_to_wkt(lat, lon, radius_km)
        kwargs.setdefault("region_label", f"{lat:.2f},{lon:.2f}")
        records, meta = self.fetch(geometry=wkt, **kwargs)
        records = filter_by_radius(records, lat, lon, radius_km)
        meta["fetched"] = len(records)
        meta["radius_km"] = radius_km
        return records, meta

    def fetch_by_scientific_name(self, name, geometry=None, **kwargs):
        kwargs.setdefault("region_label", name)
        return self.fetch(geometry=geometry, scientificname=name, **kwargs)

    def fetch_around_argo_floats(self, float_positions, radius_km=200.0,
                                 per_float=500, **kwargs):
        """
        Biodiversity in the neighbourhood of ARGO float positions.

        float_positions is a list of (lat, lon) read from argo_profiles by the
        caller. This module never queries the ARGO database itself.
        """
        seen, collected = set(), []
        meta = {"source": "unavailable", "fetched": 0, "floats_queried": 0,
                "error": None, "query": {}, "total_available": None,
                "fetched_at": None, "region_label": "ARGO float neighbourhood"}

        for lat, lon in float_positions:
            records, sub_meta = self.fetch_by_point(
                lat, lon, radius_km=radius_km, max_records=per_float, **kwargs
            )
            if sub_meta.get("source") in ("live", "cache"):
                meta["source"] = sub_meta["source"]
                meta["fetched_at"] = sub_meta.get("fetched_at") or meta["fetched_at"]
            elif sub_meta.get("error"):
                meta["error"] = sub_meta["error"]
            meta["floats_queried"] += 1

            for record in records:
                key = record.get("occurrence_id") or record.get("obis_id")
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                record["region_label"] = "ARGO float neighbourhood"
                collected.append(record)

        meta["fetched"] = len(collected)
        return collected, meta


def filter_by_radius(records, lat, lon, radius_km):
    """Exact great-circle filter applied after the server-side box query."""
    kept = []
    for record in records:
        distance = haversine_km(lat, lon, record["latitude"], record["longitude"])
        if distance == distance and distance <= radius_km:
            record["distance_km"] = round(distance, 1)
            kept.append(record)
    return kept
