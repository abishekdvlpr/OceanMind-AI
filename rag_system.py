# --- rag_system.py ---
"""
RAG + text-to-SQL engine.

Public interface (relied on by data_processing.py and dashboard.py):

    VectorStoreManager()
        .add_document(doc_id, document, metadata) -> bool
        .search(query, n_results)                 -> list[str]
        .reset_vector_store()                     -> bool
        .count()                                  -> int

    QueryValidator()
        .is_ocean_related(query) -> (bool, float)

    RAGSQLQueryExecutor(ollama_model=None)
        .db_manager   : DatabaseManager
        .vector_store : VectorStoreManager
        .query_with_rag(question) -> dict
"""

import logging
import random
import re

import chromadb
import pandas as pd
from sentence_transformers import SentenceTransformer

from config import OLLAMA_CONFIG, VECTOR_DB_CONFIG, get_ollama_model
from database_manager import DatabaseManager

# Optional domain module (SIH25041 fisheries + molecular biodiversity).
# Absence is never fatal: the platform degrades cleanly to ARGO-only behaviour.
try:
    from marine_data import MarineDataManager
except Exception:  # pragma: no cover
    MarineDataManager = None

# Deterministic statistics + citations. Every number and source in an answer is
# computed here, in Python, so the model can only narrate - never invent.
try:
    import marine_analysis
except Exception:  # pragma: no cover - degrades to the previous behaviour
    marine_analysis = None

# Schema-aware validation of generated SQL. Repairs the unambiguous naming
# mismatches between domains and converts the rest into readable messages.
try:
    import sql_validator
except Exception:  # pragma: no cover
    sql_validator = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VectorStoreManager:
    """ChromaDB-backed store of natural-language float metadata summaries."""

    def __init__(self):
        self.client = chromadb.PersistentClient(path=VECTOR_DB_CONFIG["path"])
        self.collection = self.client.get_or_create_collection(
            name=VECTOR_DB_CONFIG["collection_name"]
        )
        try:
            self.embedding_model = SentenceTransformer(
                VECTOR_DB_CONFIG.get("embedding_model", "all-MiniLM-L6-v2")
            )
        except Exception as e:
            logger.error(f"Could not load SentenceTransformer model: {e}")
            self.embedding_model = None

    def add_document(self, doc_id: str, document: str, metadata: dict):
        """Upsert so that reprocessing the same float never raises on duplicate IDs."""
        if not self.embedding_model or not document:
            return False
        try:
            embedding = self.embedding_model.encode(document).tolist()
            payload = {
                "ids": [str(doc_id)],
                "embeddings": [embedding],
                "documents": [document],
                "metadatas": [metadata or {}],
            }
            if hasattr(self.collection, "upsert"):
                self.collection.upsert(**payload)
            else:  # very old chromadb
                self.collection.add(**payload)
            return True
        except Exception as e:
            logger.error(f"ChromaDB - Error adding document {doc_id}: {e}")
            return False

    def search(self, query: str, n_results: int = None):
        if not self.embedding_model:
            return []
        n_results = n_results or VECTOR_DB_CONFIG.get("n_results", 3)
        try:
            if self.count() == 0:
                return []
            query_embedding = self.embedding_model.encode(query).tolist()
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(n_results, max(self.count(), 1)),
            )
            documents = results.get("documents") or []
            return documents[0] if documents else []
        except Exception as e:
            logger.error(f"ChromaDB - Error searching: {e}")
            return []

    def reset_vector_store(self):
        """
        Drop and recreate the collection.

        Called by ArgoDataProcessor.process_directory() before a fresh load so
        the vector store can never drift out of sync with the SQL database.
        """
        collection_name = VECTOR_DB_CONFIG["collection_name"]
        try:
            logger.warning("--- RESETTING CHROMA VECTOR STORE ---")
            try:
                self.client.delete_collection(name=collection_name)
            except Exception as inner:
                logger.info(f"No existing collection to delete ({inner}).")
            self.collection = self.client.get_or_create_collection(name=collection_name)
            logger.info("--- CHROMA VECTOR STORE RESET COMPLETE ---")
            return True
        except Exception as e:
            logger.error(f"Failed to reset vector store: {e}")
            return False

    def count(self):
        try:
            return int(self.collection.count())
        except Exception:
            return 0


class QueryValidator:
    """Enhanced validator with better ocean region recognition"""

    def __init__(self):
        # Enhanced ocean/marine science related keywords
        self.ocean_keywords = {
            # Basic oceanographic terms
            'temperature', 'temp', 'salinity', 'sal', 'depth', 'pressure', 'ocean', 'sea', 'marine',
            'water', 'float', 'profile', 'argo', 'oceanographic', 'oceanography', 'floats',

            # Measurements and parameters
            'chlorophyll', 'chla', 'oxygen', 'doxy', 'ph', 'density', 'conductivity',
            'nitrate', 'phosphate', 'silicate', 'turbidity', 'fluorescence',

            # Ocean regions and geography
            'latitude', 'longitude', 'lat', 'lon', 'location', 'position', 'coordinate',
            'north', 'south', 'east', 'west', 'atlantic', 'pacific', 'indian', 'arctic',
            'mediterranean', 'caribbean', 'gulf', 'bay', 'strait', 'channel',
            'arabian', 'bengal', 'red', 'black', 'caspian', 'barents', 'norwegian',
            'southern', 'antarctic', 'equator', 'tropical', 'subtropical',
            'region', 'area', 'zone', 'basin', 'ridge', 'trench', 'plateau',

            # Countries and places near oceans
            'india', 'mumbai', 'goa', 'chennai', 'kochi', 'delhi', 'kolkata',
            'australia', 'japan', 'california', 'florida', 'norway', 'iceland',
            'madagascar', 'maldives', 'srilanka', 'lanka', 'perth', 'cape',

            # Time-related
            'time', 'date', 'year', 'month', 'day', 'season', 'seasonal', 'temporal',
            'recent', 'latest', 'historical', 'trend', 'series', 'current', 'present',
            'january', 'february', 'march', '2024', '2023',

            # Analysis terms
            'average', 'mean', 'maximum', 'minimum', 'max', 'min', 'range', 'variation',
            'anomaly', 'correlation', 'pattern', 'distribution', 'gradient', 'count',
            'all', 'show', 'display', 'list', 'find', 'search', 'get', 'what', 'where',
            'plot', 'graph', 'chart', 'compare', 'many', 'how',

            # Spatial terms
            'near', 'nearest', 'around', 'within', 'between', 'above', 'below',
            'surface', 'deep', 'bottom', 'shallow', 'available', 'existing',

            # Fisheries domain (SIH25041)
            'fish', 'fishery', 'fisheries', 'catch', 'landing', 'landings', 'landed',
            'tonnes', 'tonnage', 'vessel', 'vessels', 'gear', 'trawl', 'gillnet',
            'seine', 'sardine', 'mackerel', 'tuna', 'shrimp', 'squid', 'ribbonfish',
            'effort', 'stock', 'yield', 'zone', 'harvest', 'cmlre',

            # Molecular biodiversity domain (SIH25041)
            'edna', 'dna', 'molecular', 'biodiversity', 'species', 'taxon', 'taxa',
            'taxonomy', 'taxonomic', 'genus', 'family', 'marker', 'gene', 'sequence',
            'sequences', 'barcode', 'metabarcoding', 'motu', 'motus', 'unassigned',
            'assigned', 'identity', 'read', 'reads', 'sample', 'samples', 'coi',
            'rrna', 'diversity', 'detection', 'detected', 'occurrence', 'abundance'
        }

        # Enhanced patterns for better recognition
        self.query_patterns = [
            r'\b(?:show|display|plot|graph|chart|list|find|get)\b',
            r'\b(?:what|where|when|how|which|all|present)\b',
            r'\b(?:temperature|salinity|depth|pressure|float|floats)\b',
            r'\b(?:ocean|sea|marine|water)\s+(?:region|area|basin)\b',
            r'\b(?:indian|pacific|atlantic|arctic|southern)\s+ocean\b',
            r'\b(?:arabian|bengal|red|black)\s+sea\b',
            r'\bfloats?\s+(?:in|near|around|present)\b',
            r'\d+\s*(?:degrees?|°)\s*[ns]',   # Latitude patterns
            r'\d+\s*(?:degrees?|°)\s*[ew]',   # Longitude patterns
            r'\d+\s*(?:m|meters?|km|kilometers?)',  # Distance patterns
            r'\b(?:fish|catch|landing|landings|fisheries)\b',
            r'\b(?:edna|dna|species|taxa|taxon|motu|marker\s+gene)\b',
            r'\b(?:biodiversity|molecular|metabarcoding)\b',
        ]

    def is_ocean_related(self, query: str):
        """Enhanced validation with better ocean region recognition"""
        if not query or not query.strip():
            return False, 0.0

        query_lower = query.lower().strip()

        # Remove common punctuation and normalize
        normalized_query = re.sub(r'[^\w\s°]', ' ', query_lower)

        # Check for meaningless input (repeated characters, gibberish)
        if self._is_gibberish(normalized_query):
            logger.info(f"Query detected as gibberish: '{query[:30]}...'")
            return False, 0.0

        # Check for ocean-related keywords
        words = set(normalized_query.split())
        keyword_matches = len(words.intersection(self.ocean_keywords))
        keyword_score = min(keyword_matches / max(len(words), 1), 1.0)

        # Check for query patterns with higher weight
        pattern_matches = sum(
            1 for pattern in self.query_patterns
            if re.search(pattern, query_lower, re.IGNORECASE)
        )
        pattern_score = min(pattern_matches / 2, 1.0)  # More lenient

        # Special boost for ocean regions
        ocean_region_boost = 0.0
        ocean_regions = [
            'indian ocean', 'pacific ocean', 'atlantic ocean', 'arctic ocean',
            'southern ocean', 'arabian sea', 'bay of bengal', 'red sea',
            'mediterranean sea'
        ]
        if any(region in query_lower for region in ocean_regions):
            ocean_region_boost = 0.5

        # Combined confidence score with region boost
        confidence = (keyword_score * 0.6) + (pattern_score * 0.4) + ocean_region_boost

        # More lenient threshold for ocean-related queries
        is_relevant = confidence > 0.05 or ocean_region_boost > 0

        logger.info(
            f"Query validation - '{query[:50]}...' -> "
            f"Relevant: {is_relevant}, Confidence: {confidence:.3f}"
        )

        return is_relevant, confidence

    def _is_gibberish(self, query: str) -> bool:
        """Detect gibberish but be less aggressive"""
        words = query.split()

        if not words:
            return True

        # Only flag truly meaningless patterns
        if len(words) >= 3:
            # Check if all words are identical (like "what is the what is the")
            if len(set(words)) <= 2 and all(len(w) <= 4 for w in words):
                return True

        # Check for single repeated character patterns
        if len(query.replace(' ', '')) <= 10 and len(set(query.replace(' ', ''))) <= 2:
            return True

        return False


class RAGSQLQueryExecutor:
    """Natural language -> context retrieval -> SQL -> execution -> summary."""

    def __init__(self, ollama_model=None):
        self.db_manager = DatabaseManager()
        self.vector_store = VectorStoreManager()
        self.query_validator = QueryValidator()

        # Fisheries / eDNA domains are optional and additive.
        # Live schema index, used to check every generated statement before it
        # reaches the database.
        self.schema_index = None
        if sql_validator is not None:
            try:
                self.schema_index = sql_validator.SchemaIndex(self.db_manager.engine)
            except Exception as e:
                logger.warning(f"Schema index unavailable: {e}")

        self.marine_manager = None
        if MarineDataManager is not None:
            try:
                self.marine_manager = MarineDataManager()
            except Exception as e:
                logger.warning(f"Marine domain unavailable: {e}")

        try:
            from langchain_ollama.llms import OllamaLLM
        except ImportError as e:
            logger.error(
                "langchain-ollama is not installed. Run: pip install langchain-ollama"
            )
            raise RuntimeError(
                "Missing dependency 'langchain-ollama'. "
                "Install it with: pip install langchain-ollama"
            ) from e

        try:
            self.llm = OllamaLLM(
                base_url=OLLAMA_CONFIG["base_url"],
                model=ollama_model or get_ollama_model(),
                temperature=OLLAMA_CONFIG["temperature"],
                top_p=OLLAMA_CONFIG.get("top_p", 0.9),
            )
            # Fail fast and loudly if the daemon or model is unavailable.
            self.llm.invoke("Reply with the single word: ready")
            logger.info(f"Connected to Ollama model: {self.llm.model}")
        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {e}")
            raise

        # Improved fallback responses
        self.fallback_responses = [
            "I'm designed to help you explore and analyze ARGO oceanographic data. "
            "Please ask questions about ocean temperature, salinity, depth profiles, "
            "float locations, or other marine science topics.",

            "I can help you with oceanographic data queries such as:\n"
            "• Temperature and salinity profiles\n• Float locations and movements\n"
            "• Depth analysis\n• Time series data\n• Geospatial ocean data\n\n"
            "Please ask a question related to ocean or marine science data.",

            "I specialize in ARGO ocean float data analysis. Try asking about:\n"
            "• 'Which floats are located in the Arabian Sea?'\n"
            "• 'Find the 10 nearest floats to Mumbai, India'\n"
            "• 'Show the temperature profile for float 2903140'\n"
            "• 'What is the average temperature below 500 m depth?'",
        ]

        self.sql_prompt_template = """You are an expert oceanographer and PostgreSQL developer working on a PostGIS-enabled ARGO float database. Generate ONE PostgreSQL SELECT query.

### CRITICAL RULES:
1. Output ONLY the SQL query. No explanation, no markdown, no commentary.
2. The measurement table is ALWAYS 'argo_profiles'.
3. Prefer simple WHERE clauses for single-table questions. Subqueries ARE allowed and expected for cross-domain questions (see rule 14).
4. ALWAYS include a LIMIT clause.
5. NEVER use INSERT, UPDATE, DELETE, DROP, ALTER or CREATE.
6. Use only the columns listed in the schema below.
7. Respect the ACTUAL DATA COVERAGE. Never filter on a date range outside it, and never use NOW() or CURRENT_DATE, because this is an archived historical dataset.
8. For "nearest to <place>" questions, order by ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(<lon>, <lat>), 4326)::geography).
9. When the user asks to plot or profile something, select the columns needed for that plot (for example depth, temperature, float_id).
10. ROW GRAIN - THIS IS THE MOST IMPORTANT RULE. Every row in argo_profiles is ONE DEPTH LEVEL, and a single float has hundreds or thousands of levels. So for any question about WHICH floats, WHERE floats are, HOW MANY floats, or any map/location question, you MUST aggregate to one row per float with GROUP BY float_id and AVG(lat), AVG(lon). If you do not, a LIMIT will return many depth levels of a single float and the map will show only one point.
11. DEPTH PROFILES - a profile only makes sense for ONE float at a time. For any depth-profile question, restrict to a single float with WHERE float_id = '<id>' (use a specific id, or pick one with a subquery) and ORDER BY depth, with LIMIT 2000. NEVER write ORDER BY depth across the whole table: that returns only the shallowest surface rows of many different floats and plots a flat line.
12. Aggregations (AVG, MIN, MAX, COUNT) over depth ranges are safe without GROUP BY because they collapse to one row.
13. CROSS-DOMAIN JOINS - this platform unifies three domains: argo_profiles (ocean physics), fisheries_landings (catch), biodiversity_occurrences (marine biodiversity from OBIS). Join them on SPACE, and on TIME only when the domains actually overlap in time. They are independent observation systems with no shared keys, so use a tolerance of about 5 degrees of latitude/longitude, and restrict argo_profiles to depth <= 50 when you mean sea-surface conditions. Note that biodiversity_occurrences uses the column names latitude/longitude while argo_profiles uses lat/lon.
14. JOIN FAN-OUT - NEVER apply SUM() to a measure across a join. argo_profiles has hundreds of rows per float, so joining it to fisheries_landings multiplies catch_tonnes many times over and produces a wildly inflated total. To combine a SUM with a joined average, compute each side in its own subquery and join the two aggregated results. AVG and COUNT(DISTINCT ...) are safe; bare SUM across a join is not.
15. BIODIVERSITY - biodiversity_occurrences holds REAL observations harvested from the OBIS API (Ocean Biodiversity Information System, IOC-UNESCO). Use accepted_name for species-level grouping and scientific_name for what was recorded. vernacular_name is the common name and is often NULL. event_date and depth are frequently NULL because providers did not record them - never filter them out unless the question requires it, or you will discard most of the data.
16. MOLECULAR RECORDS - rows with is_dna_derived = true come from eDNA metabarcoding; marker_gene holds COI / 16S rRNA / 18S rRNA / 12S rRNA, sequence_id holds the ENA or SRA accession and read_count the sequence read count. Filter on is_dna_derived for molecular biodiversity questions.
17. OBIS ENVIRONMENTAL FIELDS - sst and sss on biodiversity_occurrences are satellite-derived values attached by OBIS. They are INDEPENDENT of argo_profiles.temperature, so comparing the two is a genuine cross-validation between observation systems, not a join key.
18. ALIASES - never ORDER BY or reference an alias you did not define in the SELECT list. If you order by distance, the distance expression must appear in SELECT with that alias.
19. UNITS - ST_Distance on ::geography returns METRES. A 500 km radius is 500000, not 500.

### SCHEMA:
{schema}

### ACTUAL DATA COVERAGE:
{coverage}

### EXAMPLES:

User: "Show all floats in the Indian Ocean"
SQL: SELECT float_id, AVG(lat) AS lat, AVG(lon) AS lon, COUNT(*) AS measurements FROM argo_profiles WHERE lat BETWEEN -60 AND 30 AND lon BETWEEN 20 AND 147 GROUP BY float_id LIMIT 300;

User: "Which floats are in the Arabian Sea?"
SQL: SELECT float_id, AVG(lat) AS lat, AVG(lon) AS lon, MAX(depth) AS max_depth FROM argo_profiles WHERE lat BETWEEN 8 AND 25 AND lon BETWEEN 60 AND 78 GROUP BY float_id LIMIT 100;

User: "Find the nearest floats to Mumbai (19.07N, 72.87E)"
SQL: SELECT float_id, AVG(lat) AS lat, AVG(lon) AS lon, MIN(ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(72.87, 19.07), 4326)::geography)) AS distance_m FROM argo_profiles WHERE geom IS NOT NULL GROUP BY float_id ORDER BY distance_m ASC LIMIT 10;

User: "Show temperature profiles for float 2903140"
SQL: SELECT float_id, profile_number, depth, temperature, salinity FROM argo_profiles WHERE float_id = '2903140' ORDER BY depth LIMIT 2000;

User: "Plot a depth profile of temperature"
SQL: SELECT float_id, profile_number, depth, temperature FROM argo_profiles WHERE float_id = (SELECT float_id FROM argo_profiles GROUP BY float_id ORDER BY COUNT(*) DESC LIMIT 1) AND temperature IS NOT NULL ORDER BY depth LIMIT 2000;

User: "What is the average temperature below 500m?"
SQL: SELECT AVG(temperature) AS avg_temperature, COUNT(*) AS measurements FROM argo_profiles WHERE depth > 500 AND temperature IS NOT NULL LIMIT 1;

User: "Compare average daily salinity"
SQL: SELECT DATE(time) AS day, AVG(salinity) AS avg_salinity, COUNT(DISTINCT float_id) AS floats FROM argo_profiles WHERE salinity IS NOT NULL GROUP BY DATE(time) ORDER BY day LIMIT 100;

User: "How many floats are there?"
SQL: SELECT COUNT(DISTINCT float_id) AS total_floats, COUNT(*) AS total_measurements FROM argo_profiles LIMIT 1;

User: "Compare fish catch with sea surface temperature by zone"
SQL: SELECT c.zone_name, c.state, c.catch_t, (SELECT AVG(a.temperature) FROM argo_profiles a WHERE a.depth <= 50 AND a.lat BETWEEN c.lat - 5 AND c.lat + 5 AND a.lon BETWEEN c.lon - 5 AND c.lon + 5) AS sst_c, (SELECT COUNT(DISTINCT a.float_id) FROM argo_profiles a WHERE a.depth <= 50 AND a.lat BETWEEN c.lat - 5 AND c.lat + 5 AND a.lon BETWEEN c.lon - 5 AND c.lon + 5) AS argo_floats FROM (SELECT zone_name, state, AVG(lat) AS lat, AVG(lon) AS lon, SUM(catch_tonnes) AS catch_t FROM fisheries_landings GROUP BY zone_name, state) c ORDER BY c.catch_t DESC LIMIT 50;

User: "Show biodiversity near Chennai"
SQL: SELECT accepted_name, vernacular_name, latitude, longitude, event_date, depth, source, occurrence_id FROM biodiversity_occurrences WHERE latitude BETWEEN 11.6 AND 14.6 AND longitude BETWEEN 78.8 AND 81.8 ORDER BY event_date DESC NULLS LAST LIMIT 200;

User: "Marine organisms near Tamil Nadu"
SQL: SELECT accepted_name, vernacular_name, phylum, class_name, COUNT(*) AS records, MIN(latitude) AS lat_min, MAX(latitude) AS lat_max FROM biodiversity_occurrences WHERE latitude BETWEEN 8 AND 13.6 AND longitude BETWEEN 77.5 AND 81.5 GROUP BY accepted_name, vernacular_name, phylum, class_name ORDER BY records DESC LIMIT 100;

User: "Species recorded in the Bay of Bengal"
SQL: SELECT accepted_name, COUNT(*) AS observations, MIN(event_year) AS first_year, MAX(event_year) AS last_year, COUNT(DISTINCT source) AS providers FROM biodiversity_occurrences WHERE latitude BETWEEN 5 AND 22.5 AND longitude BETWEEN 78 AND 95 AND accepted_name IS NOT NULL GROUP BY accepted_name ORDER BY observations DESC LIMIT 100;

User: "Marine organisms near 13.08 N, 80.27 E"
SQL: SELECT accepted_name, vernacular_name, latitude, longitude, event_date, depth, source, occurrence_id, ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(80.27, 13.08), 4326)::geography) AS distance_m FROM biodiversity_occurrences WHERE geom IS NOT NULL ORDER BY distance_m ASC LIMIT 50;

User: "Biodiversity around nearby ARGO floats"
SQL: SELECT b.accepted_name, b.vernacular_name, COUNT(*) AS records, AVG(b.sst) AS obis_sst, (SELECT AVG(a.temperature) FROM argo_profiles a WHERE a.depth <= 50 AND a.lat BETWEEN AVG(b.latitude) - 5 AND AVG(b.latitude) + 5 AND a.lon BETWEEN AVG(b.longitude) - 5 AND AVG(b.longitude) + 5) AS argo_sst FROM biodiversity_occurrences b WHERE b.accepted_name IS NOT NULL GROUP BY b.accepted_name, b.vernacular_name ORDER BY records DESC LIMIT 50;

User: "Which molecular eDNA records exist and for which marker genes?"
SQL: SELECT marker_gene, COUNT(*) AS records, COUNT(DISTINCT accepted_name) AS taxa, SUM(read_count) AS total_reads FROM biodiversity_occurrences WHERE is_dna_derived = TRUE GROUP BY marker_gene ORDER BY records DESC LIMIT 20;

User: "Which landed species are also recorded in biodiversity observations?"
SQL: SELECT f.species_common, f.landed_t, COALESCE(b.observations, 0) AS obis_observations FROM (SELECT species_common, species_scientific, SUM(catch_tonnes) AS landed_t FROM fisheries_landings GROUP BY species_common, species_scientific) f LEFT JOIN (SELECT accepted_name, COUNT(*) AS observations FROM biodiversity_occurrences GROUP BY accepted_name) b ON b.accepted_name = f.species_scientific ORDER BY f.landed_t DESC LIMIT 50;

User: "Total fish landings by species"
SQL: SELECT species_common, species_scientific, SUM(catch_tonnes) AS total_tonnes, SUM(vessels) AS vessel_trips FROM fisheries_landings GROUP BY species_common, species_scientific ORDER BY total_tonnes DESC LIMIT 50;

### CONTEXT FROM FLOAT METADATA:
{context}

### USER QUESTION:
{question}

SQL Query:"""

        self.repair_prompt_template = """The following PostgreSQL query failed.

### Failed query:
{failed_sql}

### Database error:
{error}

### Schema:
{schema}

### Reminders:
- Each row is ONE DEPTH LEVEL. For location / "which floats" questions use GROUP BY float_id with AVG(lat), AVG(lon).
- Depth profiles must be restricted to a single float_id.
- Never use NOW() or CURRENT_DATE; this is an archived historical dataset.

### Original question:
{question}

Rewrite it as ONE valid PostgreSQL SELECT query that answers the question. Output ONLY the corrected SQL, nothing else.

SQL Query:"""

        self.response_prompt_template = """You are a senior marine scientist and ocean data analyst working at an operational oceanography centre. You are briefing a colleague on results just retrieved from OceanMind AI, a unified platform holding three independent observation systems: ARGO float profiles (ocean physics), OBIS occurrence records (marine biodiversity, IOC-UNESCO) and ICAR-CMFRI marine fish landings (fisheries).

### User question
{question}

### Datasets queried
{domains}

### VERIFIED FACTS - the complete set of information available to you
{facts}

### How to answer

Write in this structure, using markdown bold for the section leads:

**Summary.** Two or three sentences stating what the data shows and over what area and period.

**Key statistics.** The most decision-relevant figures, quoted exactly as given above.

**Scientific interpretation.** What these values mean oceanographically or ecologically - water-mass character, thermocline structure, seasonality, habitat suitability, fishing pressure, biodiversity representation. Explain mechanism, not just description.

**Cross-domain relationships.** Discuss the computed correlations. Name the domains involved. Where a relationship could not be established, say so plainly and state what additional data would be needed.

**Implications.** One short paragraph on what this suggests for conservation, fisheries management or further sampling - framed as a hypothesis consistent with the data, never as a settled conclusion.

### Absolute rules
1. Every number you write must appear in the VERIFIED FACTS block. Do not compute, estimate, round differently, extrapolate or infer any figure that is not there.
2. Do not name a species, region, float, gear type or date that is not in the facts.
3. Correlation is not causation. Describe associations as associations.
4. If the facts list relationships that could not be established, you MUST mention them as limitations rather than passing over them in silence.
5. If only one domain was queried, say so and note which additional dataset would be required to extend the analysis. Do not imply you used data you did not.
6. Be precise and collegial, as a scientist briefing a peer. No filler, no encouragement, no apologies.
7. Do NOT write a Sources section - one is appended automatically.

Briefing:"""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _check_sql(self, sql):
        """
        Validate generated SQL against the live schema.

        Returns (sql, report). Repairs are applied in place; unrecoverable
        problems are reported so the caller can ask the model to try again with
        precise feedback instead of guessing.
        """
        if sql_validator is None or self.schema_index is None or not sql:
            return sql, {"ok": True, "repairs": [], "problems": [],
                         "missing": [], "unknown_tables": [], "ambiguous": []}
        try:
            fixed, report = sql_validator.validate_and_repair(sql, self.schema_index)
            for repair in report["repairs"]:
                logger.info(f"SQL auto-repair: {repair}")
            return fixed, report
        except Exception as e:
            logger.error(f"SQL validation failed, passing through: {e}")
            return sql, {"ok": True, "repairs": [], "problems": [],
                         "missing": [], "unknown_tables": [], "ambiguous": []}

    def _full_schema(self):
        """
        ARGO schema plus any domain tables that actually exist.

        Tables are advertised to the LLM only when present, so a missing or
        unseeded marine_data module can never cause the model to query a
        phantom table.
        """
        schema = self.db_manager.get_schema_description()
        if self.marine_manager is not None:
            try:
                extra = self.marine_manager.get_schema_description()
                if extra:
                    schema = schema + "\n" + extra
            except Exception as e:
                logger.warning(f"Could not read marine schema: {e}")
        return schema

    def _get_fallback_response(self) -> str:
        """Return a helpful fallback response"""
        return random.choice(self.fallback_responses)

    def _format_coverage(self):
        """Ground the model in what is actually loaded, not in today's date."""
        try:
            summary = self.db_manager.get_data_summary()
        except Exception as e:
            logger.error(f"Could not read data summary: {e}")
            return "Coverage unknown - assume a small historical archive."

        if not summary.get("available"):
            return "The database is currently empty. No measurements are loaded."

        def _fmt(value, digits=2):
            if value is None:
                return "unknown"
            if isinstance(value, (int, float)):
                return f"{value:.{digits}f}"
            return str(value)

        base = (
            f"- Rows: {summary['total_records']:,} (each row is ONE DEPTH LEVEL, not one float)\n"
            f"- Distinct floats: {summary['unique_floats']:,} "
            f"(~{max(summary['total_records'] // max(summary['unique_floats'], 1), 1):,} depth levels per float)\n"
            f"- Time range: {summary['time_min']} to {summary['time_max']}\n"
            f"- Latitude range: {_fmt(summary['lat_min'])} to {_fmt(summary['lat_max'])}\n"
            f"- Longitude range: {_fmt(summary['lon_min'])} to {_fmt(summary['lon_max'])}\n"
            f"- Maximum depth: {_fmt(summary['depth_max'], 1)} m\n"
            f"- doxy, chla, ph and bbp are NULL for these core floats."
        )

        if self.marine_manager is not None:
            try:
                marine = self.marine_manager.get_summary()
                if marine.get("available"):
                    base += (
                        f"\n- fisheries_landings: {marine['fisheries_rows']:,} records, "
                        f"{marine['species_count']} species across {marine['zones']} Indian coastal zones, "
                        f"{marine['total_catch_tonnes']:,.1f} tonnes total.\n"
                        f"- biodiversity_occurrences: {marine['biodiversity_rows']:,} REAL OBIS "
                        f"observations, {marine['species_observed']:,} distinct accepted species, "
                        f"{marine['data_providers']:,} data providers, "
                        f"{marine['dna_records']:,} DNA-derived (eDNA) records"
                        + (f", observation years {marine['year_min']}-{marine['year_max']}."
                           if marine.get('year_min') else ".")
                        + "\n- Biodiversity records span many decades, so do NOT restrict them "
                          "to the ARGO time window; join biodiversity to ARGO on SPACE only."
                    )
            except Exception as e:
                logger.warning(f"Could not read marine coverage: {e}")
        return base

    @staticmethod
    def _extract_sql(raw_response: str):
        """
        Pull a single SELECT statement out of whatever the LLM produced.

        Handles markdown fences, leading prose, trailing explanations and
        models that answer with several statements.
        """
        if not raw_response:
            return None

        text_response = raw_response.strip()

        # Prefer a fenced block when present.
        fenced = re.search(
            r"```(?:sql)?\s*(.+?)```", text_response, re.DOTALL | re.IGNORECASE
        )
        if fenced:
            text_response = fenced.group(1).strip()

        text_response = re.sub(r"^\s*SQL\s*Query\s*:\s*", "", text_response, flags=re.IGNORECASE)

        # Locate the first real statement keyword.
        match = re.search(r"\b(SELECT|WITH)\b", text_response, re.IGNORECASE)
        if not match:
            return None

        statement = text_response[match.start():]

        # Cut at the first statement terminator.
        semicolon = statement.find(";")
        if semicolon != -1:
            statement = statement[:semicolon]

        # Drop trailing prose lines that are clearly not SQL.
        lines = []
        for line in statement.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("--"):
                continue
            if re.match(r"^(note|explanation|this query|here)\b", stripped, re.IGNORECASE):
                break
            lines.append(line)

        statement = " ".join(part.strip() for part in lines).strip()
        statement = re.sub(r"\s+", " ", statement)

        if not statement or not re.match(r"^(SELECT|WITH)\b", statement, re.IGNORECASE):
            return None
        return statement + ";"

    def _generate_sql(self, question: str, context: str):
        """Enhanced SQL generation with markdown stripping and validation."""
        prompt = self.sql_prompt_template.format(
            schema=self._full_schema(),
            coverage=self._format_coverage(),
            context=context,
            question=question,
        )

        try:
            response = self.llm.invoke(prompt)
            sql_query = self._extract_sql(response)
            if sql_query:
                logger.info(f"Generated SQL query: {sql_query}")
            else:
                logger.warning(f"LLM returned no usable SQL. Raw: {str(response)[:300]}")
            return sql_query
        except Exception as e:
            logger.error(f"Error generating SQL: {e}")
            return None

    def _repair_sql(self, question: str, failed_sql: str, error: str):
        """One self-correction attempt when the database rejects the query."""
        prompt = self.repair_prompt_template.format(
            failed_sql=failed_sql,
            error=error,
            schema=self._full_schema(),
            question=question,
        )
        try:
            response = self.llm.invoke(prompt)
            repaired = self._extract_sql(response)
            if repaired:
                logger.info(f"Repaired SQL query: {repaired}")
            return repaired
        except Exception as e:
            logger.error(f"Error repairing SQL: {e}")
            return None

    def _summarize_results(self, question: str, df: pd.DataFrame, sql=None):
        """
        Produce an expert marine-science briefing grounded in computed facts.

        The statistics, correlations and citations are calculated by
        marine_analysis before the model is called, so the LLM narrates a
        closed set of verified numbers rather than generating its own. If
        marine_analysis is unavailable the previous behaviour is preserved.
        """
        if df.empty:
            return (
                "No data found matching your criteria. This could mean the area or "
                "timeframe you specified doesn't have available measurements, or the "
                "query parameters were too restrictive."
            )

        if marine_analysis is None:
            return self._legacy_summary(question, df)

        try:
            facts = marine_analysis.build_facts_block(question, df, sql)
            domains = marine_analysis.domain_labels(sql)
            sources = marine_analysis.build_sources_block(sql)
        except Exception as e:
            logger.error(f"Fact computation failed: {e}")
            return self._legacy_summary(question, df)

        prompt = self.response_prompt_template.format(
            question=question,
            domains=", ".join(domains) if domains else
                    "not determinable from the executed SQL",
            facts=facts,
        )

        try:
            narrative = self.llm.invoke(prompt)
        except Exception as e:
            # The model is unreachable - fall back to a fully deterministic
            # briefing rather than an apology. The figures are identical
            # because they came from the same computation.
            logger.error(f"Error generating response: {e}")
            narrative = marine_analysis.deterministic_summary(df, sql)

        # Provenance is appended in code, never left to the model, so a source
        # can only be cited when the SQL genuinely referenced its table.
        return f"{str(narrative).strip()}\n{sources}"

    def _legacy_summary(self, question: str, df: pd.DataFrame):
        """Original concise summariser, retained as a safety net."""
        if len(df) == 1 and len(df.columns) == 1:
            value = df.iloc[0, 0]
            col_name = df.columns[0]
            if isinstance(value, (int, float)):
                value_str = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
            else:
                value_str = str(value)
            data_summary = f"Single result: {col_name} = {value_str}"
        else:
            cols = ', '.join(df.columns[:4])
            sample = df.head(2).to_dict('records')
            extra = ""
            if 'float_id' in df.columns:
                extra = f" Distinct floats in result: {df['float_id'].nunique()}."
            data_summary = (
                f"Found {len(df)} records with columns: {cols}.{extra} "
                f"Sample values: {sample}"
            )
        try:
            return self.llm.invoke(
                "You are an expert oceanographer. Summarise these results in "
                f"2-3 sentences without inventing numbers.\n\nQuestion: {question}"
                f"\n\nData: {data_summary}\n\nResponse:"
            )
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return (
                f"I found {len(df)} records matching your query. The data includes "
                "measurements from ARGO ocean floats."
            )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def query_with_rag(self, user_question: str):
        """
        Always returns a dict containing at minimum:
            success, enhanced_response, generated_query, data, columns, fallback_used
        dashboard.py depends on exactly these keys.
        """
        base = {
            "success": False,
            "enhanced_response": "",
            "generated_query": None,
            "data": [],
            "columns": [],
            "fallback_used": False,
            "error": None,
        }

        try:
            is_relevant, confidence = self.query_validator.is_ocean_related(user_question)

            if not is_relevant:
                logger.info(
                    f"Query rejected as irrelevant: '{user_question}' "
                    f"(confidence: {confidence:.3f})"
                )
                base.update(
                    {
                        "success": True,
                        "enhanced_response": self._get_fallback_response(),
                        "fallback_used": True,
                    }
                )
                return base

            logger.info(
                f"Processing relevant query: '{user_question}' "
                f"(confidence: {confidence:.3f})"
            )

            if not self.db_manager.table_exists("argo_profiles"):
                base.update(
                    {
                        "success": True,
                        "enhanced_response": (
                            "The database has no ARGO tables yet. Use "
                            "**Process New Data Files** in the sidebar to ingest the "
                            "NetCDF files in your data directory, then ask again."
                        ),
                        "fallback_used": True,
                    }
                )
                return base

            # Retrieve metadata context from the vector store
            context_docs = self.vector_store.search(user_question)
            context = (
                "\n".join(f"- {doc}" for doc in context_docs)
                if context_docs
                else "No specific float context found."
            )

            sql_query = self._generate_sql(user_question, context)

            if not sql_query:
                base.update(
                    {
                        "success": True,
                        "enhanced_response": (
                            "I couldn't turn that into a valid database query. Try "
                            "phrasing it more concretely, for example: 'Show temperature "
                            "and depth for the 20 shallowest measurements'."
                        ),
                        "fallback_used": True,
                    }
                )
                return base

            # --- Schema validation BEFORE execution -------------------------
            # Catches column/table errors while we can still act on them,
            # instead of surfacing a database traceback to the user.
            sql_query, report = self._check_sql(sql_query)
            if not report["ok"]:
                logger.warning(f"SQL failed schema validation: {report['problems']}")
                feedback = " ".join(report["problems"])[:500]
                retried = self._repair_sql(user_question, sql_query, feedback)
                if retried:
                    retried, retry_report = self._check_sql(retried)
                    if retry_report["ok"]:
                        sql_query, report = retried, retry_report
                if not report["ok"]:
                    # Unrecoverable: explain in domain terms, never raw SQL.
                    base.update({
                        "success": True,
                        "generated_query": sql_query,
                        "enhanced_response": sql_validator.friendly_error(
                            report, user_question),
                        "fallback_used": True,
                        "error": None,
                    })
                    return base

            query_result = self.db_manager.execute_query(sql_query)

            # One self-repair attempt before giving up.
            if not query_result["success"]:
                logger.warning(
                    f"SQL execution failed, attempting repair: {query_result.get('error')}"
                )
                repaired = self._repair_sql(
                    user_question, sql_query, str(query_result.get("error"))
                )
                if repaired:
                    repaired, _ = self._check_sql(repaired)
                    repaired_result = self.db_manager.execute_query(repaired)
                    if repaired_result["success"]:
                        sql_query = repaired
                        query_result = repaired_result

            if not query_result["success"]:
                logger.error(f"SQL execution failed: {query_result.get('error')}")
                base.update(
                    {
                        "success": False,
                        "generated_query": sql_query,
                        "error": query_result.get("error"),
                        # Technical detail is logged above, not shown. The user
                        # gets a sentence describing the limitation instead.
                        "enhanced_response": (
                            "This analysis could not be completed against the "
                            "available data. The query was valid for the schema "
                            "but the database could not execute it - this usually "
                            "means the requested combination of fields is not "
                            "supported for these domains. Try narrowing the "
                            "question to a single dataset, or asking for a "
                            "different measurement."
                        ),
                    }
                )
                return base

            df = pd.DataFrame(query_result["data"])
            enhanced_response = self._summarize_results(
                user_question, df, query_result.get("executed_query", sql_query)
            )

            base.update(
                {
                    "success": True,
                    "enhanced_response": enhanced_response,
                    "generated_query": query_result.get("executed_query", sql_query),
                    "data": query_result["data"],
                    "columns": query_result["columns"],
                    "fallback_used": False,
                }
            )
            return base

        except Exception as e:
            logger.error(f"RAG query failed: {e}")
            base.update(
                {
                    "success": False,
                    "error": str(e),
                    "enhanced_response": (
                        "An unexpected error occurred while processing your "
                        f"oceanographic data query. Error details: {e}"
                    ),
                }
            )
            return base
