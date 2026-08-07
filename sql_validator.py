# --- sql_validator.py ---
"""
OceanMind AI - schema-aware validation and repair for LLM-generated SQL.

WHY THIS MODULE EXISTS
----------------------
The platform's three domains use inconsistent column names for the same
concept: argo_profiles and fisheries_landings store `lat`/`lon`, while
biodiversity_occurrences stores `latitude`/`longitude`. A language model
cannot reliably keep that straight, so a large share of generated queries
fail on a column that does not exist in the table being queried.

Rather than let the database reject them - which exposes a driver traceback to
the user - this module checks every generated statement against the LIVE
schema before execution, repairs the unambiguous cases, and turns the rest
into a sentence a marine scientist would understand.

DESIGN CONTRACT
---------------
1. READ-ONLY AND ADDITIVE. Introspects the schema; never alters it. Does not
   touch ingestion, models, caching or the API layer.
2. REPAIRS ONLY WHEN UNAMBIGUOUS. A synonym is applied only when the target
   table has exactly one matching column and the original is absent. Anything
   uncertain is reported, never guessed.
3. NEVER INVENTS. If a requested measurement does not exist in the dataset,
   the answer says so; it does not substitute a different column.

Public interface:
    SchemaIndex(engine)                  -> live schema, cached
        .tables / .columns_of(table) / .tables_with(column)
    validate_and_repair(sql, index)      -> (sql, report)
    friendly_error(report)               -> user-facing sentence
"""

import logging
import re
import time

from sqlalchemy import inspect

logger = logging.getLogger(__name__)

SCHEMA_CACHE_SECONDS = 300

# Concept -> the column names used for it across the three domains. Applied
# only when the table has exactly one of them and the written one is absent.
COLUMN_SYNONYMS = {
    "lat": ["lat", "latitude"],
    "latitude": ["latitude", "lat"],
    "lon": ["lon", "longitude"],
    "longitude": ["longitude", "lon"],
    "lng": ["lon", "longitude"],
    "long": ["lon", "longitude"],
    "class": ["class_name"],
    "order": ["order_name"],
    "species": ["accepted_name", "scientific_name", "species_common"],
    "species_name": ["accepted_name", "scientific_name", "species_common"],
    "scientificname": ["scientific_name", "accepted_name"],
    "common_name": ["vernacular_name", "species_common"],
    "date": ["event_date", "landing_date", "time"],
    "observation_date": ["event_date", "landing_date", "time"],
    "sample_date": ["event_date", "landing_date"],
    "year": ["event_year"],
    "catch": ["catch_tonnes", "catch_t"],
    "tonnes": ["catch_tonnes"],
    "temp": ["temperature"],
    "sea_surface_temperature": ["sst", "temperature"],
    "abundance": ["read_count", "individual_count"],
}

# Columns a user may reasonably ask for that genuinely do not exist anywhere in
# a given table. The message explains the gap in domain terms.
MISSING_COLUMN_MESSAGES = {
    "salinity": ("This dataset does not contain salinity values. Salinity is "
                 "measured by ARGO floats (argo_profiles.salinity); "
                 "biodiversity records carry only a sea-surface salinity "
                 "estimate (sss)."),
    "temperature": ("This dataset does not contain in-situ temperature. ARGO "
                    "profiles hold measured temperature; biodiversity records "
                    "hold a satellite sea-surface estimate (sst)."),
    "depth": ("This dataset does not record depth for these rows."),
    "biomass": ("Biomass is not recorded. Fisheries data holds landed weight "
                "in tonnes (catch_tonnes); biodiversity data holds occurrence "
                "counts, not biomass."),
    "population": ("Population size is not recorded. Biodiversity data holds "
                   "occurrence records, which are presence observations rather "
                   "than population estimates."),
    "chlorophyll": ("Chlorophyll is not available: the ingested ARGO files are "
                    "core floats, so chla is null for every profile."),
    "chla": ("Chlorophyll is not available: the ingested ARGO files are core "
             "floats, so chla is null for every profile."),
    "oxygen": ("Dissolved oxygen is not available: the ingested ARGO files are "
               "core floats, so doxy is null for every profile."),
    "doxy": ("Dissolved oxygen is not available: the ingested ARGO files are "
             "core floats, so doxy is null for every profile."),
}

SQL_KEYWORDS = {
    "select", "from", "where", "group", "by", "order", "having", "limit",
    "offset", "join", "inner", "left", "right", "outer", "full", "cross", "on",
    "as", "and", "or", "not", "in", "is", "null", "like", "ilike", "between",
    "case", "when", "then", "else", "end", "distinct", "count", "sum", "avg",
    "min", "max", "round", "cast", "coalesce", "nullif", "asc", "desc", "with",
    "union", "all", "date", "extract", "interval", "true", "false", "abs",
    "stddev", "variance", "percentile_cont", "over", "partition", "nulls",
    "first", "last", "exists", "any", "some", "using", "natural", "lateral",
}

# PostGIS and other function names that look like identifiers.
FUNCTION_PATTERN = re.compile(r"\b(st_\w+|date_trunc|to_char|now|current_date)\s*\(",
                              re.IGNORECASE)


class SchemaIndex:
    """Live schema, refreshed at most every SCHEMA_CACHE_SECONDS."""

    def __init__(self, engine):
        self.engine = engine
        self._tables = {}
        self._loaded_at = 0.0

    def refresh(self, force=False):
        if not force and self._tables and (time.time() - self._loaded_at) < SCHEMA_CACHE_SECONDS:
            return self._tables
        try:
            inspector = inspect(self.engine)
            self._tables = {
                name: {column["name"] for column in inspector.get_columns(name)}
                for name in inspector.get_table_names()
            }
            self._loaded_at = time.time()
        except Exception as e:
            logger.error(f"Schema introspection failed: {e}")
        return self._tables

    @property
    def tables(self):
        return self.refresh()

    def columns_of(self, table):
        return self.refresh().get(table, set())

    def tables_with(self, column):
        return [t for t, cols in self.refresh().items() if column in cols]


# =========================================================================
# Parsing helpers (regex-based; no new dependency)
# =========================================================================
def _strip_literals_and_comments(sql):
    """Blank out string literals and comments so they cannot be misparsed."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"'[^']*'", "''", sql)
    return sql


def extract_tables(sql):
    """
    Tables and their aliases: {alias_or_name: table_name}.
    Subquery aliases are recorded with a None table so they are not validated
    against the physical schema.
    """
    cleaned = _strip_literals_and_comments(sql)
    mapping = {}
    for match in re.finditer(
        r"\b(?:from|join)\s+([A-Za-z_][\w]*)\s*(?:as\s+)?([A-Za-z_][\w]*)?",
        cleaned, re.IGNORECASE,
    ):
        table, alias = match.group(1), match.group(2)
        if table.lower() in SQL_KEYWORDS:
            continue
        mapping[table] = table
        if alias and alias.lower() not in SQL_KEYWORDS:
            mapping[alias] = table
    # Derived tables: FROM ( ... ) alias
    for match in re.finditer(r"\)\s*(?:as\s+)?([A-Za-z_][\w]*)", cleaned, re.IGNORECASE):
        alias = match.group(1)
        if alias.lower() not in SQL_KEYWORDS and alias not in mapping:
            mapping[alias] = None
    return mapping


def extract_select_aliases(sql):
    """Aliases defined with AS in the SELECT list, usable in ORDER BY."""
    cleaned = _strip_literals_and_comments(sql)
    return {m.group(1).lower()
            for m in re.finditer(r"\bas\s+([A-Za-z_][\w]*)", cleaned, re.IGNORECASE)}


def extract_qualified_columns(sql):
    """[(alias, column, full_text)] for alias.column references."""
    cleaned = _strip_literals_and_comments(sql)
    found = []
    for match in re.finditer(r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\b", cleaned):
        alias, column = match.group(1), match.group(2)
        if alias.lower() in SQL_KEYWORDS:
            continue
        found.append((alias, column, match.group(0)))
    return found


def extract_bare_identifiers(sql):
    """Identifiers that are not keywords, functions, aliases or qualified."""
    cleaned = _strip_literals_and_comments(sql)
    cleaned = FUNCTION_PATTERN.sub(" ( ", cleaned)
    cleaned = re.sub(r"\b[A-Za-z_][\w]*\.[A-Za-z_][\w]*\b", " ", cleaned)
    cleaned = re.sub(r"\b[A-Za-z_][\w]*\s*\(", " ( ", cleaned)
    names = set()
    for match in re.finditer(r"\b([A-Za-z_][\w]*)\b", cleaned):
        word = match.group(1)
        if word.lower() in SQL_KEYWORDS or word.isdigit():
            continue
        names.add(word)
    return names


# =========================================================================
# Validation and repair
# =========================================================================
def _resolve_synonym(column, candidate_columns):
    """Return the real column a synonym maps to, or None if unresolvable."""
    for option in COLUMN_SYNONYMS.get(column.lower(), []):
        if option in candidate_columns:
            return option
    return None


def validate_and_repair(sql, index):
    """
    Check `sql` against the live schema and repair what can be repaired safely.

    Returns (possibly rewritten sql, report) where report contains:
        ok            - safe to execute
        repairs       - list of human-readable corrections applied
        problems      - list of unrecoverable issues
        missing       - column names that do not exist anywhere relevant
        unknown_tables- tables not present in the database
    """
    report = {"ok": True, "repairs": [], "problems": [], "missing": [],
              "unknown_tables": [], "ambiguous": []}
    if not sql or not sql.strip():
        report.update(ok=False, problems=["No SQL statement was produced."])
        return sql, report

    schema = index.tables
    if not schema:
        # Cannot introspect; let the database be the judge rather than blocking.
        return sql, report

    aliases = extract_tables(sql)
    physical = {a: t for a, t in aliases.items() if t and t in schema}

    # --- unknown tables ---
    for alias, table in aliases.items():
        if table and table not in schema and table == alias:
            report["unknown_tables"].append(table)
    if report["unknown_tables"]:
        report["ok"] = False
        report["problems"].append(
            "The query refers to "
            + ", ".join(f"'{t}'" for t in sorted(set(report['unknown_tables'])))
            + ", which is not a table in this platform."
        )
        return sql, report

    # --- qualified columns: alias.column ---
    repaired = sql
    for alias, column, full in extract_qualified_columns(sql):
        table = aliases.get(alias)
        if table is None:            # subquery alias - not schema-checkable
            continue
        if table not in schema:
            continue
        columns = schema[table]
        if column in columns:
            continue
        replacement = _resolve_synonym(column, columns)
        if replacement:
            repaired = re.sub(rf"\b{re.escape(alias)}\.{re.escape(column)}\b",
                              f"{alias}.{replacement}", repaired)
            report["repairs"].append(
                f"{alias}.{column} -> {alias}.{replacement} "
                f"({table} stores it under that name)"
            )
        else:
            report["missing"].append(column)
            report["problems"].append(
                f"Column '{column}' does not exist in {table}."
            )

    # --- bare identifiers ---
    known_aliases = extract_select_aliases(sql)
    candidate_columns = set()
    for table in set(physical.values()):
        candidate_columns |= schema[table]

    for name in extract_bare_identifiers(sql):
        lowered = name.lower()
        if lowered in known_aliases or name in candidate_columns:
            continue
        if name in aliases or name in schema:
            continue
        owners = [t for t in set(physical.values()) if name in schema[t]]
        if owners:
            continue
        replacement = _resolve_synonym(name, candidate_columns)
        if replacement:
            repaired = re.sub(rf"(?<![\w.]){re.escape(name)}(?![\w])",
                              replacement, repaired)
            report["repairs"].append(
                f"{name} -> {replacement} (actual column name in this schema)"
            )
        else:
            report["missing"].append(name)
            report["problems"].append(
                f"'{name}' is not a column in "
                + ", ".join(sorted(set(physical.values() or ["this schema"])))
                + "."
            )

    # --- ambiguity: same bare column present in two joined tables ---
    #
    # Only checked for FLAT statements. A nested SELECT introduces its own
    # scope, so a bare `lat` inside a subquery over one table is perfectly
    # unambiguous even though another table in the outer query also has `lat`.
    # Applying a whole-statement namespace here produced false positives that
    # blocked valid cross-domain queries, so subqueries are left to the
    # database, which resolves scope correctly.
    has_subquery = bool(re.search(r"\(\s*select\b", _strip_literals_and_comments(repaired),
                                  re.IGNORECASE))
    if len(set(physical.values())) > 1 and not has_subquery:
        select_aliases = extract_select_aliases(repaired)
        for name in extract_bare_identifiers(repaired):
            if name.lower() in select_aliases:
                continue          # defined by this query, not a table column
            owners = [t for t in set(physical.values()) if name in schema[t]]
            if len(owners) > 1:
                report["ambiguous"].append((name, owners))
        if report["ambiguous"]:
            report["ok"] = False
            names = ", ".join(f"'{n}'" for n, _ in report["ambiguous"])
            report["problems"].append(
                f"{names} appears in more than one joined table and must be "
                f"written with its table prefix."
            )

    if report["missing"]:
        report["ok"] = False
    return repaired, report


def friendly_error(report, question=None):
    """
    Turn a validation report into one sentence a scientist would accept.

    Domain-specific explanations take priority over generic ones, because
    "this dataset does not contain salinity values" is more useful than
    "column salinity does not exist".
    """
    for column in report.get("missing", []):
        message = MISSING_COLUMN_MESSAGES.get(str(column).lower())
        if message:
            return message

    if report.get("unknown_tables"):
        return (
            "That question refers to a dataset this platform does not hold. "
            "Available domains are ARGO ocean profiles, OBIS biodiversity "
            "occurrences and ICAR-CMFRI fisheries landings."
        )

    if report.get("ambiguous"):
        names = ", ".join(n for n, _ in report["ambiguous"])
        return (
            f"This comparison could not be run because the field(s) {names} "
            f"exist in more than one of the joined datasets, so the request is "
            f"ambiguous. Try naming the domain explicitly, for example "
            f"'biodiversity latitude' or 'float latitude'."
        )

    if report.get("missing"):
        missing = ", ".join(sorted(set(str(m) for m in report["missing"])))
        return (
            f"This dataset does not contain {missing}. The available fields "
            f"differ by domain: ARGO holds temperature, salinity and depth; "
            f"biodiversity holds species, coordinates, dates and sea-surface "
            f"estimates; fisheries holds catch tonnage, gear and zone."
        )

    if report.get("problems"):
        return (
            "This analysis could not be completed as written. "
            + report["problems"][0]
        )
    return "This analysis could not be completed with the available data."
