# --- marine_analysis.py ---
"""
OceanMind AI - deterministic analysis layer for AI answer generation.

WHY THIS MODULE EXISTS
----------------------
Asking an LLM "do not hallucinate" is a request. Handing it a pre-computed
facts block that it is forbidden to exceed is a constraint. Every number,
correlation and citation that appears in an OceanMind answer is calculated
HERE, in Python, from the dataframe the SQL actually returned. The language
model's only job is to narrate facts it has been given.

DESIGN CONTRACT
---------------
1. PURE FUNCTIONS. No database access, no network, no Streamlit, no LLM.
   Input is a pandas DataFrame; output is text and dicts. Fully unit-testable.
2. NOTHING IS INVENTED. If a relationship cannot be computed (too few rows,
   missing columns, zero variance) the module says so explicitly rather than
   omitting it, so the model cannot fill the silence.
3. CITATIONS ARE DERIVED, NOT DECLARED. Sources come from the tables the
   executed SQL actually referenced. A pure ARGO query does not get to claim
   it used OBIS.

Public interface:
    detect_domains(sql)                  -> ["argo", "obis", "cmfri"]
    profile_dataframe(df)                -> dict of computed statistics
    compute_relationships(df)            -> list of correlation findings
    build_facts_block(question, df, sql) -> str  (goes into the LLM prompt)
    build_sources_block(sql)             -> str  (appended after the answer)
    deterministic_summary(df, sql)       -> str  (LLM-free fallback answer)
"""

import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

# Minimum sample size before a correlation is reported at all.
MIN_CORRELATION_ROWS = 8

# Identifiers only. Aggregate counts such as `records`, `observations` and
# `reads` ARE measurements - they carry the abundance signal that makes
# "biodiversity vs temperature" answerable - so they are deliberately absent
# from this list.
NON_MEASUREMENT_COLUMNS = {
    "id", "obis_id", "aphia_id", "dataset_id", "profile_number", "float_id",
    "occurrence_id", "sequence_id", "event_year",
}

# Coordinates are real numbers but correlating one against the other describes
# the shape of the sampling track, not the ocean. Such pairs are suppressed.
COORDINATE_COLUMNS = {"lat", "lon", "latitude", "longitude",
                      "lat_min", "lat_max", "lon_min", "lon_max",
                      "distance_km", "distance_m"}

# Table -> (domain key, human label, formal citation)
DOMAIN_TABLES = {
    "argo_profiles": (
        "argo", "ARGO ocean measurements",
        "ARGO Global Data Assembly Centre - Argo float profile data "
        "(`argo_profiles`)",
    ),
    "float_metadata": (
        "argo", "ARGO float metadata",
        "ARGO Global Data Assembly Centre - Argo float profile data "
        "(`float_metadata`)",
    ),
    "biodiversity_occurrences": (
        "obis", "OBIS biodiversity occurrences",
        "OBIS (IOC-UNESCO) - Ocean Biodiversity Information System "
        "(`biodiversity_occurrences`)",
    ),
    "fisheries_landings": (
        "cmfri", "CMFRI fisheries landings",
        "ICAR-CMFRI Fisheries Database - marine fish landings "
        "(`fisheries_landings`)",
    ),
}

DOMAIN_ORDER = ["argo", "obis", "cmfri"]

DOMAIN_CITATIONS = {
    "argo": "**ARGO Global Data Assembly Centre** - Argo float profile data",
    "obis": "**OBIS (IOC-UNESCO)** - Ocean Biodiversity Information System",
    "cmfri": "**ICAR-CMFRI Fisheries Database** - marine fish landings",
}

# Column pairs whose correlation carries a recognised ecological meaning.
# The label is used only to frame a computed number - never to assert one.
ECOLOGICAL_PAIRS = {
    ("sst", "records"): "biodiversity abundance against sea-surface temperature",
    ("sst", "observations"): "biodiversity abundance against sea-surface temperature",
    ("sst", "reads"): "molecular detection intensity against sea-surface temperature",
    ("sss", "records"): "biodiversity abundance against sea-surface salinity",
    ("sss", "observations"): "biodiversity abundance against sea-surface salinity",
    ("temperature", "depth"): "the thermal structure of the water column",
    ("salinity", "depth"): "the haline structure of the water column",
    ("temperature", "salinity"): "the temperature-salinity relationship of the water mass",
    ("catch_t", "sst_c"): "fisheries landings against sea-surface temperature",
    ("total_tonnes", "sst"): "fisheries landings against sea-surface temperature",
    ("catch_tonnes", "sst"): "fisheries landings against sea-surface temperature",
    ("landed_t", "obis_observations"): "fisheries landings against biodiversity records",
    ("landed_t", "edna_reads"): "fisheries landings against molecular detections",
    ("depth", "sst"): "observation depth against surface temperature",
    ("bathymetry", "records"): "biodiversity abundance against seafloor depth",
    ("shore_distance_m", "records"): "biodiversity abundance against distance from shore",
}


# =========================================================================
# Domain detection
# =========================================================================
def detect_domains(sql):
    """
    Which scientific domains did the executed SQL actually touch?

    Table names are matched on word boundaries so a column mentioning a table
    name in passing cannot trigger a false citation.
    """
    if not sql:
        return []
    lowered = str(sql).lower()
    found = []
    for table, (domain, _label, _citation) in DOMAIN_TABLES.items():
        if re.search(rf"\b{re.escape(table)}\b", lowered) and domain not in found:
            found.append(domain)
    return [d for d in DOMAIN_ORDER if d in found]


def domain_labels(sql):
    """Human-readable names of the datasets used, in canonical order."""
    names = {"argo": "ARGO ocean measurements",
             "obis": "OBIS biodiversity occurrences",
             "cmfri": "CMFRI fisheries landings"}
    return [names[d] for d in detect_domains(sql)]


# =========================================================================
# Statistical profiling
# =========================================================================
def _is_measurement(column):
    return str(column).lower() not in NON_MEASUREMENT_COLUMNS


def profile_dataframe(df, max_categories=6):
    """
    Compute every statistic the answer is allowed to quote.

    Returns a dict; all values are derived from `df` alone.
    """
    profile = {
        "row_count": int(len(df)),
        "columns": list(df.columns),
        "numeric": {},
        "categorical": {},
        "spatial": None,
        "temporal": None,
        "distinct": {},
    }
    if df.empty:
        return profile

    # --- numeric measurements ---
    for column in df.columns:
        series = pd.to_numeric(df[column], errors="coerce").dropna()
        if series.empty or not _is_measurement(column):
            continue
        profile["numeric"][column] = {
            "n": int(series.size),
            "mean": float(series.mean()),
            "min": float(series.min()),
            "max": float(series.max()),
            "std": float(series.std()) if series.size > 1 else 0.0,
            "median": float(series.median()),
        }

    # --- categorical composition ---
    for column in df.columns:
        if df[column].dtype != object:
            continue
        series = df[column].dropna().astype(str)
        if series.empty:
            continue
        counts = series.value_counts()
        profile["categorical"][column] = {
            "distinct": int(counts.size),
            "top": [(str(k), int(v)) for k, v in counts.head(max_categories).items()],
        }

    # --- distinct identifier counts ---
    for column in ("float_id", "accepted_name", "scientific_name",
                   "species_common", "zone_name", "state", "source",
                   "marker_gene", "family", "genus", "phylum"):
        if column in df.columns:
            profile["distinct"][column] = int(df[column].nunique(dropna=True))

    # --- spatial extent ---
    lat_col = "lat" if "lat" in df.columns else ("latitude" if "latitude" in df.columns else None)
    lon_col = "lon" if "lon" in df.columns else ("longitude" if "longitude" in df.columns else None)
    if lat_col and lon_col:
        lats = pd.to_numeric(df[lat_col], errors="coerce").dropna()
        lons = pd.to_numeric(df[lon_col], errors="coerce").dropna()
        if not lats.empty and not lons.empty:
            profile["spatial"] = {
                "lat_min": float(lats.min()), "lat_max": float(lats.max()),
                "lon_min": float(lons.min()), "lon_max": float(lons.max()),
                "lat_centre": float(lats.mean()), "lon_centre": float(lons.mean()),
            }

    # --- temporal extent ---
    for column in ("time", "event_date", "landing_date", "day", "date"):
        if column in df.columns:
            stamps = pd.to_datetime(df[column], errors="coerce").dropna()
            if not stamps.empty:
                profile["temporal"] = {
                    "column": column,
                    "start": str(stamps.min())[:10],
                    "end": str(stamps.max())[:10],
                    "distinct_dates": int(stamps.dt.date.nunique()),
                }
                break
    if profile["temporal"] is None and "event_year" in df.columns:
        years = pd.to_numeric(df["event_year"], errors="coerce").dropna()
        if not years.empty:
            profile["temporal"] = {
                "column": "event_year",
                "start": str(int(years.min())), "end": str(int(years.max())),
                "distinct_dates": int(years.nunique()),
            }
    return profile


# =========================================================================
# Relationships
# =========================================================================
def _strength(r):
    magnitude = abs(r)
    if magnitude >= 0.7:
        return "strong"
    if magnitude >= 0.4:
        return "moderate"
    if magnitude >= 0.2:
        return "weak"
    return "negligible"


def compute_relationships(df, max_pairs=6):
    """
    Pearson correlations between numeric measurement columns.

    Only pairs with at least MIN_CORRELATION_ROWS complete observations and
    non-zero variance in both columns are reported. Everything else is
    returned in `insufficient` so the answer can say so out loud.
    """
    findings, insufficient = [], []
    if df.empty:
        return findings, insufficient

    numeric = {}
    for column in df.columns:
        if not _is_measurement(column):
            continue
        series = pd.to_numeric(df[column], errors="coerce")
        if series.notna().sum() >= 2:
            numeric[column] = series
    names = list(numeric)

    for i, x in enumerate(names):
        for y in names[i + 1:]:
            # A correlation between two coordinates describes the sampling
            # track, not an oceanographic relationship.
            if (str(x).lower() in COORDINATE_COLUMNS
                    and str(y).lower() in COORDINATE_COLUMNS):
                continue

            pair = pd.DataFrame({"x": numeric[x], "y": numeric[y]}).dropna()
            label = (ECOLOGICAL_PAIRS.get((x, y))
                     or ECOLOGICAL_PAIRS.get((y, x)))
            if len(pair) < MIN_CORRELATION_ROWS:
                if label:
                    insufficient.append({
                        "x": x, "y": y, "n": int(len(pair)), "label": label,
                        "reason": f"only {len(pair)} paired observations "
                                  f"(minimum {MIN_CORRELATION_ROWS})",
                    })
                continue
            if pair["x"].std() == 0 or pair["y"].std() == 0:
                if label:
                    insufficient.append({
                        "x": x, "y": y, "n": int(len(pair)), "label": label,
                        "reason": "one variable has no variation in this result set",
                    })
                continue
            try:
                r = float(pair["x"].corr(pair["y"]))
            except Exception:
                continue
            if r != r:  # NaN
                continue
            findings.append({
                "x": x, "y": y, "n": int(len(pair)), "r": round(r, 3),
                "strength": _strength(r),
                "direction": "positive" if r >= 0 else "negative",
                "label": label,
                "ecological": bool(label),
            })

    # Ecologically meaningful pairs first, then by correlation magnitude.
    findings.sort(key=lambda f: (not f["ecological"], -abs(f["r"])))
    return findings[:max_pairs], insufficient


# =========================================================================
# Prompt and answer construction
# =========================================================================
def _fmt(value, digits=2):
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def build_facts_block(question, df, sql=None):
    """
    The complete, closed set of facts the model may use.

    Anything absent from this block is, by construction, unavailable to the
    answer - which is what makes the no-hallucination rule enforceable rather
    than aspirational.
    """
    domains = detect_domains(sql)
    profile = profile_dataframe(df)
    findings, insufficient = compute_relationships(df)

    lines = []
    lines.append(f"ROWS RETURNED: {profile['row_count']:,}")
    lines.append(
        "DATASETS QUERIED: "
        + (", ".join(domain_labels(sql)) if domains else "not determinable from the SQL")
    )
    lines.append(
        "CROSS-DOMAIN: "
        + ("yes - this result combines "
           f"{len(domains)} of the platform's three domains"
           if len(domains) > 1 else
           "no - this result draws on a single domain")
    )

    if profile["distinct"]:
        lines.append("DISTINCT ENTITIES: " + ", ".join(
            f"{k}={v:,}" for k, v in profile["distinct"].items()))

    if profile["spatial"]:
        s = profile["spatial"]
        lines.append(
            f"SPATIAL EXTENT: latitude {_fmt(s['lat_min'])} to {_fmt(s['lat_max'])}, "
            f"longitude {_fmt(s['lon_min'])} to {_fmt(s['lon_max'])} "
            f"(centroid {_fmt(s['lat_centre'])}, {_fmt(s['lon_centre'])})"
        )

    if profile["temporal"]:
        t = profile["temporal"]
        lines.append(
            f"TEMPORAL EXTENT: {t['start']} to {t['end']} "
            f"({t['distinct_dates']:,} distinct values of {t['column']})"
        )

    if profile["numeric"]:
        lines.append("NUMERIC STATISTICS (use these figures verbatim):")
        for column, stats in profile["numeric"].items():
            lines.append(
                f"  - {column}: n={stats['n']:,} mean={_fmt(stats['mean'])} "
                f"median={_fmt(stats['median'])} min={_fmt(stats['min'])} "
                f"max={_fmt(stats['max'])} sd={_fmt(stats['std'])}"
            )

    if profile["categorical"]:
        lines.append("CATEGORY COMPOSITION:")
        for column, info in profile["categorical"].items():
            top = ", ".join(f"{k} ({v:,})" for k, v in info["top"])
            lines.append(f"  - {column}: {info['distinct']:,} distinct; top: {top}")

    if findings:
        lines.append("COMPUTED CORRELATIONS (Pearson r, already calculated - "
                     "do not recompute or estimate):")
        for f in findings:
            meaning = f" [{f['label']}]" if f["label"] else ""
            lines.append(
                f"  - {f['x']} vs {f['y']}: r={f['r']} ({f['strength']} "
                f"{f['direction']}), n={f['n']}{meaning}"
            )
    else:
        lines.append("COMPUTED CORRELATIONS: none could be calculated from "
                     "this result set.")

    if insufficient:
        lines.append("RELATIONSHIPS THAT COULD NOT BE ESTABLISHED "
                     "(state these as limitations):")
        for item in insufficient:
            lines.append(f"  - {item['label']}: {item['reason']}")

    if profile["row_count"] and profile["row_count"] <= 3:
        lines.append("SAMPLE ROWS: " + str(df.head(3).to_dict("records")))

    return "\n".join(lines)


def build_sources_block(sql=None):
    """
    Provenance footer.

    All three platform datasets are listed for completeness, but only those the
    executed query actually touched are marked as used. Listing an unused
    source as a source would itself be a fabrication.
    """
    used = set(detect_domains(sql))
    lines = ["", "---", "**Sources**"]
    for domain in DOMAIN_ORDER:
        marker = "✓ used in this answer" if domain in used else "not queried here"
        lines.append(f"- {DOMAIN_CITATIONS[domain]} — _{marker}_")
    return "\n".join(lines)


def deterministic_summary(df, sql=None):
    """
    A complete, correct answer built without the LLM.

    Used when the model is unreachable or errors, so the platform degrades to
    a factual report rather than an apology.
    """
    if df is None or df.empty:
        return "No records matched this query."

    profile = profile_dataframe(df)
    findings, insufficient = compute_relationships(df)
    parts = [
        f"**Summary.** The query returned {profile['row_count']:,} records from "
        + (", ".join(domain_labels(sql)) or "the platform database") + "."
    ]

    stats = []
    for column, s in list(profile["numeric"].items())[:4]:
        stats.append(f"{column} averages {_fmt(s['mean'])} "
                     f"(range {_fmt(s['min'])}–{_fmt(s['max'])}, n={s['n']:,})")
    if stats:
        parts.append("**Statistics.** " + "; ".join(stats) + ".")
    if profile["spatial"]:
        s = profile["spatial"]
        parts.append(
            f"**Spatial coverage.** {_fmt(s['lat_min'])}–{_fmt(s['lat_max'])}°N, "
            f"{_fmt(s['lon_min'])}–{_fmt(s['lon_max'])}°E."
        )
    if findings:
        parts.append("**Relationships.** " + "; ".join(
            f"{f['x']} vs {f['y']} shows a {f['strength']} {f['direction']} "
            f"correlation (r={f['r']}, n={f['n']})" for f in findings[:3]) + ".")
    elif insufficient:
        parts.append("**Relationships.** Not established: "
                     + "; ".join(f"{i['label']} ({i['reason']})"
                                 for i in insufficient[:2]) + ".")
    return "\n\n".join(parts)
