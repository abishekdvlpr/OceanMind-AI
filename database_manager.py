# --- database_manager.py ---
"""
SQL layer for the ARGO explorer.

Public interface (relied on by data_processing.py, rag_system.py and
dashboard.py). Do not change signatures without updating those callers:

    DatabaseManager()
        .initialize_database()   -> bool
        .reset_database()        -> bool
        .table_exists(name)      -> bool
        .insert_argo_data(df, metadata_dict) -> bool
        .execute_query(sql)      -> dict(success, data, columns, rowcount, error)
        .spatial_query(lat, lon, radius_km) -> same dict shape
        .get_data_summary()      -> dict
        .get_schema_description() -> str
"""

import logging
import re

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import JSON, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DATA_PROCESSING_CONFIG, QUERY_CONFIG, USE_SQLITE, get_db_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# GeoAlchemy2 is only meaningful on PostGIS. On the SQLite fallback we degrade
# the geometry column to TEXT so that create_all() cannot explode.
if not USE_SQLITE:
    from geoalchemy2 import Geometry

    def _geom_column():
        return sa.Column(
            Geometry(geometry_type="POINT", srid=4326), index=True, nullable=True
        )
else:  # pragma: no cover - offline fallback only
    def _geom_column():
        return sa.Column(sa.Text, nullable=True)


class Base(DeclarativeBase):
    pass


class ArgoProfile(Base):
    __tablename__ = "argo_profiles"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    float_id = sa.Column(sa.String, index=True, nullable=False)
    profile_number = sa.Column(sa.Integer)
    time = sa.Column(sa.DateTime, index=True)
    lat = sa.Column(sa.Float)
    lon = sa.Column(sa.Float)
    depth = sa.Column(sa.Float)
    temperature = sa.Column(sa.Float, nullable=True)
    salinity = sa.Column(sa.Float, nullable=True)
    doxy = sa.Column(sa.Float, nullable=True)
    chla = sa.Column(sa.Float, nullable=True)
    ph = sa.Column(sa.Float, nullable=True)
    bbp = sa.Column(sa.Float, nullable=True)

    geom = _geom_column()


class FloatMetadata(Base):
    __tablename__ = "float_metadata"

    float_id = sa.Column(sa.String, primary_key=True, index=True)
    wmo_id = sa.Column(sa.String, nullable=True)
    project_name = sa.Column(sa.String, nullable=True)
    institution = sa.Column(sa.String, nullable=True)
    date_launched = sa.Column(sa.String, nullable=True)
    parameters = sa.Column(JSON, nullable=True)


# Columns physically written by the ingestion pipeline. 'geom' is deliberately
# excluded: it is populated server-side with ST_MakePoint after the bulk load,
# because pandas.to_sql cannot bind an EWKT string to a geometry column.
INSERT_COLUMNS = [
    "float_id",
    "profile_number",
    "time",
    "lat",
    "lon",
    "depth",
    "temperature",
    "salinity",
    "doxy",
    "chla",
    "ph",
    "bbp",
]

_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"copy|vacuum|reindex|cluster|call|do|merge)\b",
    re.IGNORECASE,
)


class DatabaseManager:
    def __init__(self, db_url=None):
        self.db_url = db_url or get_db_url()
        self.engine = create_engine(self.db_url, pool_pre_ping=True, future=True)
        self.Session = sessionmaker(bind=self.engine)
        self.is_postgres = self.engine.dialect.name == "postgresql"

    # ------------------------------------------------------------------
    # Schema lifecycle
    # ------------------------------------------------------------------
    def initialize_database(self):
        """Create the PostGIS extension (if needed) and all tables."""
        try:
            if self.is_postgres:
                with self.engine.connect() as conn:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
                    conn.commit()
            Base.metadata.create_all(self.engine)
            logger.info("Database initialized successfully.")
            return True
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

    def reset_database(self):
        """
        Drop and recreate every table owned by this application.

        Only argo_profiles and float_metadata are touched. PostGIS system
        tables such as spatial_ref_sys are never dropped.
        """
        try:
            logger.warning("--- RESETTING SQL DATABASE ---")
            Base.metadata.drop_all(self.engine, checkfirst=True)
            logger.info("Application tables dropped successfully.")
            self.initialize_database()
            logger.info("--- SQL DATABASE RESET COMPLETE ---")
            return True
        except Exception as e:
            logger.error(f"Failed to reset database: {e}")
            return False

    def table_exists(self, table_name="argo_profiles"):
        try:
            return inspect(self.engine).has_table(table_name)
        except Exception as e:
            logger.error(f"Could not inspect database: {e}")
            return False

    def ensure_ready(self):
        """Idempotent startup hook - safe to call on every Streamlit rerun."""
        try:
            if not self.table_exists("argo_profiles"):
                self.initialize_database()
            return True
        except Exception as e:
            logger.error(f"Database is not reachable: {e}")
            return False

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def insert_argo_data(self, df: pd.DataFrame, metadata_dict: dict):
        """
        Bulk-insert measurements and upsert the owning float's metadata.

        The dataframe may contain extra columns; only INSERT_COLUMNS are
        written. The PostGIS geometry is generated by the database itself.
        """
        if df is None or df.empty:
            logger.warning("insert_argo_data called with an empty dataframe.")
            return False

        try:
            frame = df.copy()
            for column in INSERT_COLUMNS:
                if column not in frame.columns:
                    frame[column] = None
            frame = frame[INSERT_COLUMNS]

            frame.to_sql(
                name=ArgoProfile.__tablename__,
                con=self.engine,
                if_exists="append",
                index=False,
                chunksize=DATA_PROCESSING_CONFIG.get("chunk_size", 5000),
                method="multi",
            )

            if self.is_postgres:
                self._populate_geometry()

            with self.Session() as session:
                session.merge(FloatMetadata(**metadata_dict))
                session.commit()

            logger.info(
                f"Inserted {len(frame)} rows for float {metadata_dict.get('float_id')}"
            )
            return True
        except Exception as e:
            logger.error(f"Error during bulk insert: {e}")
            return False

    def _populate_geometry(self):
        """Fill the PostGIS point column for any freshly inserted rows."""
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text(
                        "UPDATE argo_profiles "
                        "SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326) "
                        "WHERE geom IS NULL AND lon IS NOT NULL AND lat IS NOT NULL;"
                    )
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Could not populate geometry column: {e}")

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_sql_comments(sql: str) -> str:
        sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
        sql = re.sub(r"--[^\n]*", " ", sql)
        return sql.strip()

    def _validate_read_only(self, sql: str):
        """Return (ok, reason). Blocks anything that is not a single SELECT."""
        if not QUERY_CONFIG.get("read_only", True):
            return True, ""

        cleaned = self._strip_sql_comments(sql)
        statements = [s for s in cleaned.split(";") if s.strip()]
        if len(statements) > 1:
            return False, "Only a single SQL statement may be executed."
        if not statements:
            return False, "Empty SQL statement."

        statement = statements[0].strip()
        first_word = statement.split(None, 1)[0].lower() if statement.split() else ""
        if first_word not in ("select", "with"):
            return False, f"Only SELECT queries are permitted (got '{first_word}')."
        if _FORBIDDEN_SQL.search(statement):
            return False, "Query contains a data-modifying keyword."
        return True, ""

    def _enforce_limit(self, sql: str) -> str:
        """Append a LIMIT when the model forgot one, and cap oversized limits."""
        cleaned = self._strip_sql_comments(sql).rstrip().rstrip(";")
        default_limit = QUERY_CONFIG.get("default_limit", 500)
        max_limit = QUERY_CONFIG.get("max_limit", 5000)

        match = re.search(r"\blimit\s+(\d+)\s*$", cleaned, re.IGNORECASE)
        if match:
            requested = int(match.group(1))
            if requested > max_limit:
                cleaned = cleaned[: match.start()] + f"LIMIT {max_limit}"
        else:
            cleaned = f"{cleaned} LIMIT {default_limit}"
        return cleaned + ";"

    def execute_query(self, query: str, enforce_limit: bool = True):
        """
        Execute a read-only SQL query.

        Always returns the same dict shape so callers never need to branch on
        missing keys:
            {success, data, columns, rowcount, error, executed_query}
        """
        empty = {
            "success": False,
            "data": [],
            "columns": [],
            "rowcount": 0,
            "error": None,
            "executed_query": query,
        }

        if not query or not query.strip():
            empty["error"] = "No SQL query was provided."
            return empty

        ok, reason = self._validate_read_only(query)
        if not ok:
            logger.warning(f"Blocked unsafe SQL: {reason} | {query[:200]}")
            empty["error"] = reason
            return empty

        final_query = self._enforce_limit(query) if enforce_limit else query
        empty["executed_query"] = final_query

        try:
            with self.engine.connect() as connection:
                df = pd.read_sql_query(text(final_query), connection)
            return {
                "success": True,
                "data": df.to_dict("records"),
                "columns": df.columns.tolist(),
                "rowcount": len(df),
                "error": None,
                "executed_query": final_query,
            }
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            empty["error"] = str(e)
            return empty

    def spatial_query(self, lat: float, lon: float, radius_km: int = 10):
        """Nearest-float lookup. Uses PostGIS geography when available."""
        if not self.is_postgres:
            logger.warning(
                "Spatial queries fall back to planar distance without PostGIS."
            )
            query = f"""
            SELECT float_id, lat, lon, depth, temperature, salinity, time,
                   ((lat - {lat}) * (lat - {lat}) + (lon - {lon}) * (lon - {lon})) AS dist_sq
            FROM argo_profiles
            ORDER BY dist_sq
            LIMIT 20
            """
            return self.execute_query(query)

        query = f"""
        SELECT float_id, lat, lon, depth, temperature, salinity, time,
               ST_Distance(
                   geom::geography,
                   ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)::geography
               ) AS distance_m
        FROM argo_profiles
        WHERE geom IS NOT NULL
          AND ST_DWithin(
                  geom::geography,
                  ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)::geography,
                  {int(radius_km) * 1000}
              )
        ORDER BY distance_m
        LIMIT 20
        """
        return self.execute_query(query)

    # ------------------------------------------------------------------
    # Introspection helpers used to ground the LLM prompt
    # ------------------------------------------------------------------
    def get_data_summary(self):
        """Real coverage of the loaded dataset, injected into the SQL prompt."""
        summary = {
            "available": False,
            "total_records": 0,
            "unique_floats": 0,
            "time_min": None,
            "time_max": None,
            "lat_min": None,
            "lat_max": None,
            "lon_min": None,
            "lon_max": None,
            "depth_max": None,
        }

        if not self.table_exists("argo_profiles"):
            return summary

        sql = """
        SELECT COUNT(*) AS total_records,
               COUNT(DISTINCT float_id) AS unique_floats,
               MIN(time) AS time_min,
               MAX(time) AS time_max,
               MIN(lat) AS lat_min,
               MAX(lat) AS lat_max,
               MIN(lon) AS lon_min,
               MAX(lon) AS lon_max,
               MAX(depth) AS depth_max
        FROM argo_profiles
        """
        result = self.execute_query(sql, enforce_limit=False)
        if not result["success"] or not result["data"]:
            return summary

        row = result["data"][0]
        summary.update(
            {
                "available": bool(row.get("total_records")),
                "total_records": row.get("total_records") or 0,
                "unique_floats": row.get("unique_floats") or 0,
                "time_min": row.get("time_min"),
                "time_max": row.get("time_max"),
                "lat_min": row.get("lat_min"),
                "lat_max": row.get("lat_max"),
                "lon_min": row.get("lon_min"),
                "lon_max": row.get("lon_max"),
                "depth_max": row.get("depth_max"),
            }
        )
        return summary

    def get_schema_description(self):
        """Human-readable schema block for the LLM prompt."""
        return (
            "TABLE argo_profiles(\n"
            "  id integer PRIMARY KEY,\n"
            "  float_id text,          -- ARGO platform number\n"
            "  profile_number integer, -- cycle number\n"
            "  time timestamp,\n"
            "  lat double precision,\n"
            "  lon double precision,\n"
            "  depth double precision, -- adjusted pressure in decibars ~ metres\n"
            "  temperature double precision,\n"
            "  salinity double precision,\n"
            "  doxy double precision,  -- often NULL (core floats)\n"
            "  chla double precision,  -- often NULL (core floats)\n"
            "  ph double precision,    -- often NULL\n"
            "  bbp double precision,   -- often NULL\n"
            "  geom geometry(Point,4326)\n"
            ")\n"
            "TABLE float_metadata(\n"
            "  float_id text PRIMARY KEY,\n"
            "  wmo_id text, project_name text, institution text,\n"
            "  date_launched text, parameters json\n"
            ")"
        )
