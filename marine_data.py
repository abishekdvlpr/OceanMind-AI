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
from datetime import date, timedelta

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import USE_SQLITE, get_db_url

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


class EdnaSample(MarineBase):
    __tablename__ = "edna_samples"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    sample_id = sa.Column(sa.String, index=True)
    lat = sa.Column(sa.Float)
    lon = sa.Column(sa.Float)
    depth = sa.Column(sa.Float)                        # metres
    sample_date = sa.Column(sa.Date, index=True)
    marker_gene = sa.Column(sa.String, index=True)     # COI / 18S rRNA / 12S rRNA
    sequence_id = sa.Column(sa.String)                 # accession-style identifier
    read_count = sa.Column(sa.Integer)
    assigned_taxon = sa.Column(sa.String, index=True)  # NULL when unassigned
    taxon_rank = sa.Column(sa.String)                  # species / genus / family
    percent_identity = sa.Column(sa.Float)             # % match to reference
    confidence = sa.Column(sa.Float)                   # 0-1 assignment confidence
    is_unassigned_motu = sa.Column(sa.Boolean, index=True)
    data_source = sa.Column(sa.String, index=True)
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

# Marker genes used in marine eDNA metabarcoding
MARKERS = ["COI", "18S rRNA", "12S rRNA"]

TAXA = [
    ("Sardinella longiceps", "species"), ("Rastrelliger kanagurta", "species"),
    ("Thunnus albacares", "species"),    ("Penaeus indicus", "species"),
    ("Stolephorus", "genus"),            ("Carangidae", "family"),
    ("Engraulidae", "family"),           ("Decapterus russelli", "species"),
    ("Calanus", "genus"),                ("Copepoda", "class"),
]

# eDNA stations sit on the ARGO footprint (Arabian Sea + Bay of Bengal)
EDNA_STATIONS = [
    (10.50, 72.80), (12.10, 68.90), (15.40, 70.30), (18.20, 69.50),
    (8.90, 76.10),  (14.30, 74.00), (11.70, 80.20), (16.80, 82.40),
    (19.30, 87.10), (13.60, 78.90), (17.35, 68.35), (9.98, 63.46),
]

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

    def reset(self):
        """Drops ONLY fisheries_landings and edna_samples. Never touches ARGO."""
        try:
            logger.warning("--- RESETTING MARINE DOMAIN TABLES ---")
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
                "edna_samples": inspector.has_table("edna_samples"),
            }
        except Exception:
            return {"fisheries_landings": False, "edna_samples": False}

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

    def _build_edna(self, rng):
        rows = []
        counter = 0
        for day_offset in range(SEED_DAYS):
            sample_day = SEED_START + timedelta(days=day_offset)
            for lat, lon in EDNA_STATIONS:
                for depth in (5.0, 50.0, 200.0):
                    if rng.random() > 0.62:
                        continue
                    for _ in range(rng.randint(2, 5)):
                        counter += 1
                        # ~18% of marine eDNA reads fail to match a reference
                        # sequence - these are unassigned MOTUs, and reporting
                        # them honestly is the scientifically correct behaviour.
                        unassigned = rng.random() < 0.18
                        if unassigned:
                            taxon, rank = None, None
                            identity = round(rng.uniform(72.0, 86.0), 2)
                            confidence = round(rng.uniform(0.10, 0.45), 3)
                        else:
                            taxon, rank = rng.choice(TAXA)
                            identity = round(rng.uniform(95.0, 99.9), 2)
                            confidence = round(rng.uniform(0.78, 0.99), 3)
                        rows.append({
                            "sample_id": f"CMLRE-eDNA-{sample_day:%Y%m%d}-{counter:04d}",
                            "lat": lat + rng.uniform(-0.05, 0.05),
                            "lon": lon + rng.uniform(-0.05, 0.05),
                            "depth": depth,
                            "sample_date": sample_day,
                            "marker_gene": rng.choice(MARKERS),
                            "sequence_id": f"OM{rng.randint(100000, 999999)}",
                            "read_count": rng.randint(120, 24000),
                            "assigned_taxon": taxon,
                            "taxon_rank": rank,
                            "percent_identity": identity,
                            "confidence": confidence,
                            "is_unassigned_motu": unassigned,
                            "data_source": "representative",
                        })
        return pd.DataFrame(rows)

    def seed(self, reset=True, seed_value=20260101):
        """Deterministic seed - same input always produces the same dataset."""
        stats = {"fisheries_rows": 0, "edna_rows": 0, "errors": []}
        rng = random.Random(seed_value)

        if reset:
            if not self.reset():
                stats["errors"].append("Marine reset failed.")
                return stats
        else:
            self.ensure_ready()

        try:
            fisheries = self._build_fisheries(rng)
            fisheries.to_sql("fisheries_landings", self.engine,
                             if_exists="append", index=False, chunksize=2000)
            stats["fisheries_rows"] = len(fisheries)

            edna = self._build_edna(rng)
            edna.to_sql("edna_samples", self.engine,
                        if_exists="append", index=False, chunksize=2000)
            stats["edna_rows"] = len(edna)

            if self.is_postgres:
                self._populate_geometry()

            logger.info(
                f"Seeded {stats['fisheries_rows']} landings and "
                f"{stats['edna_rows']} eDNA reads."
            )
        except Exception as e:
            logger.error(f"Marine seed failed: {e}")
            stats["errors"].append(str(e))
        return stats

    def _populate_geometry(self):
        for table in ("fisheries_landings", "edna_samples"):
            try:
                with self.engine.connect() as conn:
                    conn.execute(text(
                        f"UPDATE {table} "
                        "SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326) "
                        "WHERE geom IS NULL AND lon IS NOT NULL AND lat IS NOT NULL;"
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

        if present.get("edna_samples"):
            blocks.append(
                "TABLE edna_samples(\n"
                "  id integer PRIMARY KEY,\n"
                "  sample_id text,\n"
                "  lat double precision, lon double precision, depth double precision,\n"
                "  sample_date date,\n"
                "  marker_gene text,        -- 'COI', '18S rRNA', '12S rRNA'\n"
                "  sequence_id text,\n"
                "  read_count integer,\n"
                "  assigned_taxon text,     -- NULL when the read is an unassigned MOTU\n"
                "  taxon_rank text,         -- species / genus / family / class\n"
                "  percent_identity double precision,\n"
                "  confidence double precision,   -- 0-1\n"
                "  is_unassigned_motu boolean,\n"
                "  data_source text,\n"
                "  geom geometry(Point,4326)\n"
                ")"
            )
        return "\n".join(blocks)

    def get_summary(self):
        summary = {
            "available": False, "fisheries_rows": 0, "edna_rows": 0,
            "species_count": 0, "taxa_count": 0, "unassigned_motus": 0,
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
                if present.get("edna_samples"):
                    row = conn.execute(text(
                        "SELECT COUNT(*) n, COUNT(DISTINCT assigned_taxon) t "
                        "FROM edna_samples")).mappings().first()
                    summary["edna_rows"] = row["n"] or 0
                    summary["taxa_count"] = row["t"] or 0
                    row = conn.execute(text(
                        "SELECT COUNT(*) u FROM edna_samples "
                        "WHERE is_unassigned_motu = 1 OR is_unassigned_motu = TRUE"
                    )).mappings().first()
                    summary["unassigned_motus"] = row["u"] or 0
            summary["available"] = bool(
                summary["fisheries_rows"] or summary["edna_rows"]
            )
        except Exception as e:
            logger.error(f"Marine summary failed: {e}")
        return summary


def main():
    parser = argparse.ArgumentParser(
        description="Create and seed the fisheries and eDNA domain tables."
    )
    parser.add_argument("--no-reset", action="store_true",
                        help="Append instead of dropping the marine tables first.")
    args = parser.parse_args()

    print("=" * 60)
    print("   OceanMind AI - Marine Domain Seeder (SIH25041)")
    print("=" * 60)

    manager = MarineDataManager()
    stats = manager.seed(reset=not args.no_reset)

    print(f"   Fisheries landings : {stats['fisheries_rows']:,}")
    print(f"   eDNA reads         : {stats['edna_rows']:,}")
    for problem in stats["errors"]:
        print(f"   ERROR: {problem}")

    s = manager.get_summary()
    print(f"\n   Species            : {s['species_count']}")
    print(f"   Fishing zones      : {s['zones']}")
    print(f"   Total catch        : {s['total_catch_tonnes']:,.1f} t")
    print(f"   Distinct taxa      : {s['taxa_count']}")
    print(f"   Unassigned MOTUs   : {s['unassigned_motus']:,}")
    print("=" * 60)
    return 0 if stats["fisheries_rows"] and stats["edna_rows"] else 1


if __name__ == "__main__":
    sys.exit(main())
