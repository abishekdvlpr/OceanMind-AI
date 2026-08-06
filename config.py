# --- config.py ---
"""
Central configuration for the OceanMind AI ocean intelligence platform.

Every other module imports from here. Nothing in this file imports project
modules, so it can never take part in a circular import.

All values can be overridden with environment variables (optionally supplied
through a .env file placed next to this file).
"""

import os
from pathlib import Path
from urllib.parse import quote_plus

# --- Optional .env support (python-dotenv is in requirements.txt) ---------
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # dotenv missing or unreadable .env - never fatal
    pass

BASE_DIR = Path(__file__).resolve().parent


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# =========================================================================
# Database configuration
# =========================================================================
# PostgreSQL + PostGIS is the primary backend. SQLite exists only as an
# emergency offline fallback and disables geospatial SQL functions.
USE_SQLITE = _as_bool(os.environ.get("USE_SQLITE"), default=False)

POSTGRES_SETTINGS = {
    "user": os.environ.get("PGUSER", "argo_user"),
    "password": os.environ.get("PGPASSWORD", "111111"),
    "host": os.environ.get("PGHOST", "localhost"),
    "port": os.environ.get("PGPORT", "5432"),
    "database": os.environ.get("PGDATABASE", "argo_db"),
}


def _build_postgres_url():
    return (
        f"postgresql+psycopg2://{quote_plus(POSTGRES_SETTINGS['user'])}:"
        f"{quote_plus(POSTGRES_SETTINGS['password'])}@"
        f"{POSTGRES_SETTINGS['host']}:{POSTGRES_SETTINGS['port']}/"
        f"{POSTGRES_SETTINGS['database']}"
    )


DATABASE_CONFIG = {
    "sqlite": {
        "url": f"sqlite:///{(BASE_DIR / 'argo.db').as_posix()}",
    },
    "postgresql": {
        "url": _build_postgres_url(),
        **POSTGRES_SETTINGS,
    },
}


def get_db_url():
    """Single source of truth for the SQLAlchemy connection string."""
    if USE_SQLITE:
        return DATABASE_CONFIG["sqlite"]["url"]
    return os.environ.get("DATABASE_URL", DATABASE_CONFIG["postgresql"]["url"])


# =========================================================================
# Ollama / LLM configuration
# =========================================================================
OLLAMA_CONFIG = {
    "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
    # Must match a model shown by `ollama list`.
    "model": os.environ.get("OLLAMA_MODEL", "llama3.2:latest"),
    "temperature": float(os.environ.get("OLLAMA_TEMPERATURE", "0.1")),
    "top_p": float(os.environ.get("OLLAMA_TOP_P", "0.9")),
    "request_timeout": int(os.environ.get("OLLAMA_TIMEOUT", "180")),
}


def get_ollama_model():
    return os.environ.get("OLLAMA_MODEL", OLLAMA_CONFIG["model"])


# =========================================================================
# Vector store (ChromaDB)
# =========================================================================
VECTOR_DB_CONFIG = {
    "path": os.environ.get("CHROMA_PATH", (BASE_DIR / "chroma_db").as_posix()),
    "collection_name": os.environ.get("CHROMA_COLLECTION", "argo_metadata"),
    "embedding_model": os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
    "n_results": int(os.environ.get("CHROMA_N_RESULTS", "3")),
}


# =========================================================================
# Data processing
# =========================================================================
DATA_PROCESSING_CONFIG = {
    "data_dir": os.environ.get("ARGO_DATA_DIR", (BASE_DIR / "data").as_posix()),
    "max_files": int(os.environ.get("ARGO_MAX_FILES", "100")),
    "chunk_size": int(os.environ.get("ARGO_CHUNK_SIZE", "5000")),
    # Columns that may be absent in core (non-BGC) ARGO files.
    "optional_parameters": ["DOXY", "CHLA", "PH_IN_SITU_TOTAL", "BBP700"],
}


# =========================================================================
# SQL execution guard rails (used by DatabaseManager.execute_query)
# =========================================================================
QUERY_CONFIG = {
    "default_limit": int(os.environ.get("SQL_DEFAULT_LIMIT", "500")),
    "max_limit": int(os.environ.get("SQL_MAX_LIMIT", "5000")),
    "read_only": _as_bool(os.environ.get("SQL_READ_ONLY"), default=True),
}


# =========================================================================
# Spatial proximity verification (used by proximity.py)
# =========================================================================
# When a user asks for observations "near <place>", results farther than this
# are NOT presented as nearby. ARGO is a deep-ocean array, so the closest float
# to a coastal city is routinely several hundred kilometres offshore; 1000 km is
# a defensible default for basin-scale relevance.
PROXIMITY_CONFIG = {
    "enabled": _as_bool(os.environ.get("PROXIMITY_ENABLED"), default=True),
    "threshold_km": float(os.environ.get("PROXIMITY_THRESHOLD_KM", "1000")),
    "suggestion_count": int(os.environ.get("PROXIMITY_SUGGESTIONS", "3")),
}


# =========================================================================
# Application settings
# =========================================================================
APP_CONFIG = {
    "host": os.environ.get("STREAMLIT_HOST", "0.0.0.0"),
    "port": int(os.environ.get("STREAMLIT_PORT", "8501")),
    "debug": _as_bool(os.environ.get("APP_DEBUG"), default=True),
    "title": "OceanMind AI - Ocean Intelligence Platform",
}
