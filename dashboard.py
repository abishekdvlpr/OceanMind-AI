import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime, timedelta

# Ensure these imports are correct for your project structure
from rag_system import RAGSQLQueryExecutor
from data_processing import ArgoDataProcessor
from database_manager import DatabaseManager
try:
    from marine_data import MarineDataManager
except Exception:
    MarineDataManager = None
try:
    import proximity
    from config import PROXIMITY_CONFIG
except Exception:          # module absent -> platform behaves exactly as before
    proximity = None
    PROXIMITY_CONFIG = {"enabled": False}
import theme

# Page configuration
st.set_page_config(
    page_title=theme.BRAND["page_title"],
    page_icon=theme.BRAND["icon"],
    layout="wide",
    initial_sidebar_state="expanded"
)

# Global design system (presentation only - see theme.py)
st.markdown(theme.inject_theme(), unsafe_allow_html=True)

# Initialize components using Streamlit's caching
@st.cache_resource
def get_executor():
    try:
        return RAGSQLQueryExecutor()
    except Exception as e:
        st.error(f"Failed to initialize AI Engine (Ollama): {e}")
        st.info("Please ensure Ollama is running and the specified model is installed.")
        return None

@st.cache_resource
def get_data_processor():
    return ArgoDataProcessor()

@st.cache_resource
def get_marine_manager():
    """Fisheries + molecular biodiversity domains. None if module absent."""
    if MarineDataManager is None:
        return None
    try:
        manager = MarineDataManager()
        manager.ensure_ready()
        return manager
    except Exception as e:
        st.warning(f"Marine domain unavailable: {e}")
        return None


@st.cache_resource
def get_db_manager():
    """Standalone DB handle so stats still work when Ollama is offline."""
    manager = DatabaseManager()
    try:
        manager.ensure_ready()
    except Exception as e:
        st.warning(f"Database is not reachable: {e}")
    return manager

# Enhanced visualization function
# Columns that are identifiers or coordinates, not measured quantities. Offering
# them as chart parameters produces meaningless plots (e.g. "Avg Profile_Number").
NON_PHYSICAL_COLUMNS = {"id", "profile_number", "lat", "lon", "distance_m", "measurements", "floats"}


def create_visualizations(df: pd.DataFrame, unique_id: str):
    if df is None or df.empty:
        st.warning("No data available for visualization.")
        return

    # Work on a copy: the profile tab adds a derived column and the caller's
    # frame is reused across Streamlit reruns.
    df = df.copy()
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")

    st.markdown(theme.section_header(
        "Interactive Visualizations",
        f"{len(df):,} data points returned"
    ), unsafe_allow_html=True)
    
    # Enhanced tabs with better styling
    map_tab, profile_tab, series_tab, stats_tab = st.tabs([
        "🗺️  Geospatial Map",
        "📈  Depth Profile",
        "📉  Time Series",
        "📊  Statistics"
    ])
    
    with map_tab:
        if 'lat' in df.columns and 'lon' in df.columns:
            map_df = df.drop_duplicates(subset=['lat', 'lon'])
            color_opts = [col for col in map_df.columns
                          if map_df[col].dtype in ['float64', 'int64', 'float32']
                          and col not in ('lat', 'lon', 'id')]
            
            if not color_opts:
                color_opts = [map_df.columns[0]]

            col1, col2 = st.columns([3, 1])
            with col2:
                color_by = st.selectbox(
                    "Color points by:", 
                    options=color_opts, 
                    index=0, 
                    key=f"map_color_{unique_id}"
                )
            
            map_kwargs = dict(
                lat='lat',
                lon='lon',
                color=color_by,
                zoom=2,
                hover_name='float_id' if 'float_id' in map_df.columns else None,
                hover_data={col: True for col in map_df.columns[:5]},
                title=f"Float Locations · {len(map_df)} unique positions",
                color_continuous_scale=theme.SEQUENTIAL,
                height=560
            )

            # px.scatter_map is the modern MapLibre renderer; scatter_mapbox is
            # kept as the fallback for older Plotly installations.
            try:
                fig = px.scatter_map(map_df, map_style="carto-positron", **map_kwargs)
            except AttributeError:
                fig = px.scatter_mapbox(
                    map_df, mapbox_style="carto-positron", **map_kwargs
                )
            theme.style_figure(fig)
            fig.update_layout(margin=dict(l=0, r=0, t=52, b=0))
            st.plotly_chart(fig, use_container_width=True, key=f"map_fig_{unique_id}")
            
            # Map statistics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Unique Locations", f"{len(map_df)}")
            with col2:
                if 'float_id' in map_df.columns:
                    st.metric("Unique Floats", f"{map_df['float_id'].nunique()}")
            with col3:
                lat_range = map_df['lat'].max() - map_df['lat'].min()
                st.metric("Latitude Range", f"{lat_range:.2f}°")
        else:
            st.markdown(theme.empty_state("🗺️", "No geospatial data", "This result set has no latitude/longitude columns."), unsafe_allow_html=True)

    with profile_tab:
        if 'depth' in df.columns:
            param_opts = [col for col in df.columns
                          if df[col].dtype in ['float64', 'int64', 'float32']
                          and col != 'depth' and col not in NON_PHYSICAL_COLUMNS]
            if not param_opts:
                param_opts = [col for col in df.columns
                              if df[col].dtype in ['float64', 'int64', 'float32'] and col != 'depth']
            
            if not param_opts:
                st.info("No numeric parameters found for depth profile.")
            else:
                col1, col2 = st.columns([3, 1])
                with col2:
                    param = st.selectbox(
                        "Parameter:", 
                        options=param_opts, 
                        index=0,
                        key=f"profile_param_{unique_id}"
                    )
                
                # Create unique profile identifier
                if 'float_id' in df.columns and 'profile_number' in df.columns:
                    df['profile_id'] = df['float_id'].astype(str) + '_' + df['profile_number'].astype(str)
                    plot_df = df.sort_values(by='depth')
                    color_col = 'profile_id'
                else:
                    plot_df = df.sort_values(by='depth')
                    color_col = 'float_id' if 'float_id' in df.columns else None
                
                fig = px.line(
                    plot_df, 
                    x=param, 
                    y='depth', 
                    color=color_col, 
                    title=f"{param.replace('_', ' ').title()} vs. Depth",
                    height=560,
                    color_discrete_sequence=theme.CATEGORICAL
                )
                theme.style_figure(fig)
                fig.update_yaxes(autorange="reversed", title="Depth (m)")
                fig.update_xaxes(title=param.replace('_', ' ').title())
                fig.update_layout(hovermode='closest')
                st.plotly_chart(fig, use_container_width=True, key=f"profile_fig_{unique_id}")
                
                # Profile statistics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Max Depth", f"{df['depth'].max():.1f} m")
                with col2:
                    st.metric("Depth Range", f"{df['depth'].max() - df['depth'].min():.1f} m")
                with col3:
                    st.metric("Avg " + param.title(), f"{df[param].mean():.2f}")
        else:
            st.markdown(theme.empty_state("📈", "No depth data", "This result set has no depth column to profile."), unsafe_allow_html=True)
            
    with series_tab:
        if 'time' in df.columns:
            param_opts_ts = [col for col in df.columns
                             if df[col].dtype in ['float64', 'int64', 'float32']
                             and col not in NON_PHYSICAL_COLUMNS]
            if not param_opts_ts:
                param_opts_ts = [col for col in df.columns
                                 if df[col].dtype in ['float64', 'int64', 'float32']]
            
            if not param_opts_ts:
                st.info("No numeric parameters found for time series.")
            else:
                col1, col2 = st.columns([3, 1])
                with col2:
                    param_ts = st.selectbox(
                        "Parameter:", 
                        options=param_opts_ts, 
                        index=0,
                        key=f"series_param_{unique_id}"
                    )
                
                color_col = 'float_id' if 'float_id' in df.columns else None

                # px.line connects points in ROW order, so unsorted results render
                # as a zigzag. Sort chronologically before plotting.
                ts_df = df.sort_values(by='time')

                fig = px.line(
                    ts_df,
                    x='time',
                    y=param_ts, 
                    color=color_col, 
                    title=f"{param_ts.replace('_', ' ').title()} over Time",
                    height=560,
                    color_discrete_sequence=theme.CATEGORICAL
                )
                theme.style_figure(fig)
                fig.update_layout(hovermode='x unified')
                st.plotly_chart(fig, use_container_width=True, key=f"series_fig_{unique_id}")
                
                # Time series statistics
                if pd.api.types.is_datetime64_any_dtype(df['time']):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        time_range = df['time'].max() - df['time'].min()
                        st.metric("Time Span", f"{time_range.days} days")
                    with col2:
                        st.metric("Data Points", f"{len(df)}")
                    with col3:
                        trend_series = ts_df[param_ts].dropna()
                        if len(trend_series) >= 2:
                            rising = trend_series.iloc[-1] > trend_series.iloc[0]
                            st.metric("Trend", "📈 Rising" if rising else "📉 Falling")
                        else:
                            st.metric("Trend", "—")
        else:
             st.markdown(theme.empty_state("📉", "No temporal data", "This result set has no time column to plot."), unsafe_allow_html=True)
    
    with stats_tab:
        st.markdown(theme.section_header("Descriptive Statistics"), unsafe_allow_html=True)
        
        # Numeric columns summary
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            stats_df = df[numeric_cols].describe().round(3)
            st.dataframe(stats_df, use_container_width=True, key=f"stats_{unique_id}")
            
            # Correlation matrix for numeric columns
            if len(numeric_cols) > 1:
                st.markdown(theme.section_header("Correlation Matrix"), unsafe_allow_html=True)
                corr_matrix = df[numeric_cols].corr()
                fig = px.imshow(
                    corr_matrix,
                    text_auto=True,
                    aspect="auto",
                    color_continuous_scale=theme.DIVERGING,
                    title="Parameter Correlations"
                )
                theme.style_figure(fig, height=480)
                st.plotly_chart(fig, use_container_width=True, key=f"corr_fig_{unique_id}")
        else:
            st.markdown(theme.empty_state("📊", "No numeric columns", "Statistics require at least one numeric column."), unsafe_allow_html=True)

# Main application
@st.cache_data(ttl=300, show_spinner=False)
def _load_float_centroids():
    """One row per float, for proximity checks. Cheap (~282 rows) and cached."""
    if proximity is None:
        return None
    try:
        return proximity.load_float_centroids(get_db_manager())
    except Exception:
        return None


@st.cache_data(ttl=120, show_spinner=False)
def _load_landing_metrics():
    """
    Read-only aggregate for the landing cards.

    Uses only DatabaseManager.execute_query / get_data_summary - no new backend
    logic, no writes. Returns {} when the database is unreachable or empty.
    """
    try:
        manager = get_db_manager()
        summary = manager.get_data_summary()
        if not summary.get("available"):
            return {}

        aggregate = manager.execute_query(
            "SELECT AVG(temperature) AS avg_temp, "
            "       AVG(salinity) AS avg_sal, "
            "       AVG(CASE WHEN depth <= 50 THEN temperature END) AS sst "
            "FROM argo_profiles",
            enforce_limit=False,
        )
        row = aggregate["data"][0] if aggregate["success"] and aggregate["data"] else {}
        summary["avg_temp"] = row.get("avg_temp")
        summary["avg_sal"] = row.get("avg_sal")
        summary["sst"] = row.get("sst")

        marine_manager = get_marine_manager()
        summary["marine"] = marine_manager.get_summary() if marine_manager else {}
        return summary
    except Exception:
        return {}


def render_proximity_help(target, unique_key, context=""):
    """
    Shared coverage guidance for spatial questions that did not produce a
    usable nearby answer - whether the rows came back FAR away or not at all.

    Returns True when the dataset does hold nearby floats (and they were shown),
    False when there is genuinely no coverage near the target.
    """
    threshold = float(PROXIMITY_CONFIG.get("threshold_km", 1000))
    centroids = _load_float_centroids()
    try:
        coverage = proximity.dataset_coverage(centroids, target)
    except Exception:
        coverage = {"count": 0, "nearest_km": None, "floats": pd.DataFrame()}

    if coverage["count"] > 0:
        st.warning(
            f"{context}The dataset does contain **{coverage['count']} float(s) "
            f"within {threshold:,.0f} km** of {target.name} "
            f"(nearest {coverage['nearest_km']:,.0f} km). "
            "Showing the genuinely nearest floats below."
        )
        st.markdown("**Nearest floats in the dataset**")
        st.dataframe(
            coverage["floats"], use_container_width=True,
            key=f"nearest_fix_{unique_key}",
        )
        return True

    nearest_text = (
        f"The closest float in the current dataset is "
        f"<b>{coverage['nearest_km']:,.0f} km</b> away, beyond the "
        f"{threshold:,.0f} km relevance threshold. "
        if coverage.get("nearest_km") else ""
    )
    st.markdown(theme.empty_state(
        "🛰️",
        f"No nearby ARGO observations exist for {target.name}",
        nearest_text
        + "ARGO is a deep-ocean array, so inland and some coastal locations "
          "have no representative float nearby."
    ), unsafe_allow_html=True)

    if centroids is not None and not centroids.empty:
        try:
            picks = proximity.coverage_suggestions(centroids, target)
        except Exception:
            picks = []
        if picks:
            st.markdown("**Where coverage does exist:**")
            cols = st.columns(len(picks))
            for col, pick in zip(cols, picks):
                with col:
                    st.markdown(theme.metric_card(
                        pick["place"], f"{pick['float_count']} floats",
                        f"nearest {pick['nearest_km']:,.0f} km", "📍"
                    ), unsafe_allow_html=True)
            st.caption(f"Try: *\"Which floats are near {picks[0]['place']}?\"*")
    return False


def render_landing(executor):
    """
    Landing dashboard shown before the first question.

    Cards backed by ARGO data show live values. Fisheries / Biodiversity /
    Alerts have no ingestion pipeline yet, so they render illustrative sample
    values behind an explicit DEMO chip and a dashed border.
    """
    metrics = _load_landing_metrics()
    has_data = bool(metrics)

    def _num(key, fmt, fallback="—"):
        value = metrics.get(key)
        if value is None:
            return fallback
        try:
            return format(float(value), fmt)
        except (TypeError, ValueError):
            return fallback

    st.markdown(theme.section_header(
        "Platform Overview",
        "Live indicators are computed from the ingested ARGO archive"
    ), unsafe_allow_html=True)

    row1 = st.columns(4)
    with row1[0]:
        st.markdown(theme.metric_card(
            "Ocean Temperature", f"{_num('avg_temp', '.2f')} °C" if has_data else "—",
            "Mean across all profiles", "🌡️", muted=not has_data
        ), unsafe_allow_html=True)
    with row1[1]:
        st.markdown(theme.metric_card(
            "Salinity", f"{_num('avg_sal', '.2f')} PSU" if has_data else "—",
            "Practical salinity units", "🧂", muted=not has_data
        ), unsafe_allow_html=True)
    with row1[2]:
        st.markdown(theme.metric_card(
            "Active Floats", f"{metrics.get('unique_floats', 0):,}" if has_data else "—",
            f"{metrics.get('total_records', 0):,} measurements" if has_data else "Awaiting ingestion",
            "📡", muted=not has_data
        ), unsafe_allow_html=True)
    with row1[3]:
        st.markdown(theme.metric_card(
            "Ocean Health", f"{_num('sst', '.1f')} °C" if has_data else "—",
            "Mean sea-surface layer (0-50 m)", "💧", muted=not has_data
        ), unsafe_allow_html=True)

    st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)

    marine = metrics.get("marine") or {}
    marine_live = bool(marine.get("available"))

    row2 = st.columns(4)
    with row2[0]:
        st.markdown(theme.metric_card(
            "Molecular Biodiversity",
            f"{marine.get('edna_rows', 0):,}" if marine_live else "—",
            (f"eDNA reads · {marine.get('taxa_count', 0)} taxa · "
             f"{marine.get('unassigned_motus', 0):,} unassigned MOTUs")
            if marine_live else "Run the marine seeder",
            "🧬", demo=not marine_live, muted=not marine_live
        ), unsafe_allow_html=True)
    with row2[1]:
        st.markdown(theme.metric_card(
            "Marine Fisheries",
            f"{marine.get('total_catch_tonnes', 0):,.0f} t" if marine_live else "—",
            (f"{marine.get('species_count', 0)} species · "
             f"{marine.get('zones', 0)} coastal zones")
            if marine_live else "Run the marine seeder",
            "🎣", demo=not marine_live, muted=not marine_live
        ), unsafe_allow_html=True)
    with row2[2]:
        st.markdown(theme.metric_card(
            "AI Status",
            "Online" if executor else "Offline",
            "Ollama · RAG · ChromaDB", "🧠",
            muted=not executor
        ), unsafe_allow_html=True)
    with row2[3]:
        st.markdown(theme.metric_card(
            "Recent Alerts", "3", "Thermal anomalies flagged",
            "🔔", demo=True
        ), unsafe_allow_html=True)

    if marine_live:
        st.caption(
            "All three domains — oceanographic (ARGO), fisheries and molecular "
            "biodiversity (eDNA) — are live and queryable through a single SQL "
            "layer. Fisheries and eDNA records are **representative datasets** "
            "tagged `data_source = 'representative'`; every row's provenance is "
            "auditable in SQL, and real CMLRE/OBIS extracts load into the same "
            "schema without code changes."
        )
    else:
        st.caption(
            "Fisheries and molecular biodiversity domains are not seeded yet. "
            "Run **Seed Marine Domains** in the sidebar to enable cross-domain queries."
        )

    if not has_data:
        st.markdown(theme.empty_state(
            "📥",
            "No oceanographic data ingested yet",
            "Run <b>Ingest ARGO Dataset</b> in the sidebar to load your NetCDF "
            "archive into PostgreSQL and ChromaDB."
        ), unsafe_allow_html=True)


def main():
    # Hero
    st.markdown(theme.hero(), unsafe_allow_html=True)

    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Sidebar
    with st.sidebar:
        st.markdown(theme.sidebar_brand(), unsafe_allow_html=True)

        # ---- System status ----
        st.markdown(theme.nav_label("System"), unsafe_allow_html=True)
        executor = get_executor()
        if executor:
            st.markdown(theme.status_pill("AI Engine Online", "ok"), unsafe_allow_html=True)
        else:
            st.markdown(theme.status_pill("AI Engine Offline", "error"), unsafe_allow_html=True)

        # ---- Data management ----
        st.markdown(theme.nav_label("Data Pipeline"), unsafe_allow_html=True)

        if st.button("⬇  Ingest ARGO Dataset", type="primary", use_container_width=True):
            with st.spinner("Processing ARGO NetCDF files... This may take a moment."):
                processor = get_data_processor()
                try:
                    stats = processor.process_directory()
                    if stats["records_inserted"]:
                        st.success(
                            f"✅ Loaded {stats['records_inserted']:,} measurements "
                            f"from {stats['floats_inserted']} floats "
                            f"({stats['files_processed']}/{stats['files_found']} files)."
                        )
                    else:
                        st.warning(
                            "No measurements were ingested. Check that .nc files "
                            "exist in the configured data directory."
                        )
                    for problem in stats["errors"][:5]:
                        st.caption(f"⚠️ {problem}")
                    _load_landing_metrics.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Processing failed: {str(e)}")

        marine_manager = get_marine_manager()
        if marine_manager is not None:
            if st.button("🧬  Seed Marine Domains", key="seed_marine",
                         use_container_width=True,
                         help="Creates and populates fisheries_landings and edna_samples. Never touches ARGO data."):
                with st.spinner("Seeding fisheries and molecular biodiversity domains..."):
                    try:
                        stats = marine_manager.seed(reset=True)
                        if stats["errors"]:
                            for problem in stats["errors"]:
                                st.error(f"❌ {problem}")
                        else:
                            st.success(
                                f"✅ {stats['fisheries_rows']:,} landings and "
                                f"{stats['edna_rows']:,} eDNA reads loaded."
                            )
                        _load_landing_metrics.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Marine seeding failed: {e}")

        # ---- Example queries ----
        st.markdown(theme.nav_label("Suggested Queries"), unsafe_allow_html=True)

        # Demo questions are chosen to match the ingested coverage (5-day core-Argo
        # archive). Each one has been verified to return a non-empty, meaningful
        # result set with a sensible visualization.
        example_questions = [
            "Compare fish catch with sea surface temperature by zone",
            "Which species are detected by eDNA and at what ocean temperature?",
            "Which landed species are confirmed by molecular detection?",
            "How much dark diversity is there by marker gene?",
            "Total fish landings by species",
            "Which floats are located in the Arabian Sea?",
            "Show the temperature and salinity profile for float 2903140",
            "What is the average temperature below 500 m depth?",
        ]

        for i, q in enumerate(example_questions):
            if st.button(q, key=f"example_{i}", use_container_width=True, help="Click to use this example query"):
                st.session_state["selected_example"] = q
                st.rerun()

        # ---- Coverage ----
        st.markdown(theme.nav_label("Dataset Coverage"), unsafe_allow_html=True)

        try:
            db_manager = executor.db_manager if executor else get_db_manager()
            summary = db_manager.get_data_summary()
            if summary["available"]:
                st.metric("Total Records", f"{summary['total_records']:,}")
                st.metric("Active Floats", f"{summary['unique_floats']:,}")
                if summary["time_min"] and summary["time_max"]:
                    st.caption(
                        f"Coverage: {str(summary['time_min'])[:10]} → "
                        f"{str(summary['time_max'])[:10]}"
                    )
                if summary["depth_max"] is not None:
                    st.caption(f"Max depth: {float(summary['depth_max']):,.0f} m")
            else:
                st.info("No data loaded yet. Use **Ingest ARGO Dataset** above.")
        except Exception as e:
            st.info(f"Database unavailable: {e}")

        if st.session_state.messages:
            st.markdown(theme.nav_label("Session"), unsafe_allow_html=True)
            if st.button("🗑  Clear Conversation", key="clear_chat", use_container_width=True):
                st.session_state.messages = []
                st.rerun()

    # Landing dashboard - only before the first question
    if not st.session_state.messages:
        render_landing(executor)

    # Main chat interface
    st.markdown(theme.section_header(
        "Conversational Ocean Data Analysis",
        "Ask in plain English · answers are grounded in the ARGO archive"
    ), unsafe_allow_html=True)

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            # A location question whose SQL could not execute is still
            # answerable: the proximity layer computes the nearest floats
            # deterministically. Detect that case BEFORE rendering, so a raw
            # database traceback is not shown as the primary answer.
            recovery_target = None
            if (message.get("query_failed")
                    and proximity is not None
                    and PROXIMITY_CONFIG.get("enabled", True)):
                try:
                    recovery_target = proximity.detect_target(
                        message.get("question", ""), message.get("query")
                    )
                except Exception:
                    recovery_target = None

            if recovery_target is not None:
                st.markdown(
                    f"The generated query could not be executed, so I answered "
                    f"**{recovery_target.name}** directly from the float index instead."
                )
                if message.get("error_detail"):
                    with st.expander("Technical detail", expanded=False):
                        st.code(str(message["error_detail"]), language="text")
            else:
                st.markdown(message["content"])

            # Handle data visualization for valid queries
            # Query executed successfully but matched no rows. For spatial
            # questions this is the common failure mode: the model writes a
            # bounding box tighter than the distance to the nearest float.
            if ((message.get("empty_result") or message.get("query_failed"))
                    and proximity is not None
                    and PROXIMITY_CONFIG.get("enabled", True)):
                if message.get("query_failed"):
                    empty_target = recovery_target
                    recovery_context = ""
                else:
                    try:
                        empty_target = proximity.detect_target(
                            message.get("question", ""), message.get("query")
                        )
                    except Exception:
                        empty_target = None
                    recovery_context = "This query matched no observations. "
                if empty_target is not None:
                    empty_key = str(message["timestamp"]).replace(" ", "_").replace(":", "-")
                    render_proximity_help(
                        empty_target, f"empty_{empty_key}",
                        context=recovery_context,
                    )

            if "data" in message and message["data"] and not message.get("fallback", False):
                df = pd.DataFrame(message["data"])
                unique_key = str(message["timestamp"]).replace(" ", "_").replace(":", "-")

                # ---- Spatial proximity verification -------------------------
                # The SQL is correct, but "nearest" is not necessarily "near".
                # Verify the claim before the UI implies it. Entirely inert for
                # non-spatial questions (verdict 'unknown').
                verdict = None
                if (proximity is not None
                        and PROXIMITY_CONFIG.get("enabled", True)
                        and "float_id" in df.columns):
                    try:
                        target = proximity.detect_target(
                            message.get("question", ""), message.get("query")
                        )
                        if target is not None:
                            df, was_reordered = proximity.reorder_by_distance(df, target)
                            verdict = proximity.assess(df, target)
                            if was_reordered and verdict.status == "near":
                                st.caption(
                                    "ℹ️ Results re-ordered nearest-first by "
                                    "great-circle distance."
                                )
                    except Exception:
                        verdict = None   # never let this break rendering

                if verdict is not None and verdict.is_far:
                    corrected = render_proximity_help(
                        verdict.target, unique_key,
                        context=(f"These results are not near {verdict.target.name}. "
                                 f"The closest returned observation is "
                                 f"{verdict.nearest_km:,.0f} km away. "),
                    )
                    show_anyway = st.checkbox(
                        f"Show the returned observations anyway "
                        f"({verdict.total_count} rows, {verdict.nearest_km:,.0f}–"
                        f"{verdict.farthest_km:,.0f} km away)",
                        key=f"show_far_{unique_key}",
                    )
                    if not show_anyway:
                        continue   # skip metrics/table/exports/charts for this message
                # -------------------------------------------------------------

                # Data summary cards
                if len(df) > 0:
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Records", f"{len(df):,}")
                    with col2:
                        if 'float_id' in df.columns:
                            st.metric("Floats", f"{df['float_id'].nunique()}")
                    with col3:
                        if 'depth' in df.columns:
                            st.metric("Max Depth", f"{df['depth'].max():.0f}m")
                    with col4:
                        if 'time' in df.columns and pd.api.types.is_datetime64_any_dtype(df['time']):
                            st.metric("Latest", df['time'].max().strftime("%Y-%m-%d"))

                # Data table and download
                with st.expander("📋  Result Data & Export", expanded=False):
                    st.dataframe(df, use_container_width=True, height=300, key=f"table_{unique_key}")
                    
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        csv = df.to_csv(index=False).encode('utf-8')
                        st.download_button(
                           "📥 Download CSV",
                           csv,
                           f"argo_query_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                           "text/csv",
                           key=f'download_{unique_key}'
                        )
                    with col2:
                        json_data = df.to_json(orient='records', date_format='iso').encode('utf-8')
                        st.download_button(
                           "📥 Download JSON",
                           json_data,
                           f"argo_query_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.json",
                           "application/json",
                           key=f'download_json_{unique_key}'
                        )
                
                # Create visualizations
                create_visualizations(df, unique_key)

            # Show SQL query for valid queries
            if "query" in message and not message.get("fallback", False):
                with st.expander("⚙️  Generated SQL Query", expanded=False):
                    st.code(message["query"], language="sql")
            
            # Show helpful tips for fallback responses
            elif message.get("fallback", False):
                st.markdown("""
                <div class="om-tips">
                    <h4>Try asking a specific question about the ocean data</h4>
                    <ul>
                        <li>Which floats are located in the Arabian Sea?</li>
                        <li>Find the 10 nearest floats to Mumbai, India</li>
                        <li>Show the temperature profile for float 2903140</li>
                        <li>What is the average temperature below 500 m depth?</li>
                        <li>Compare average daily salinity across the dataset</li>
                        <li>How many floats are in the database?</li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

    # Chat input
    prompt = st.session_state.pop("selected_example", None)

    chat_prompt = st.chat_input("Ask OceanMind AI about the ocean data...")
    if prompt is None:
        prompt = chat_prompt

    if prompt:
        executor = get_executor()
        if executor:
            # Add user message
            st.session_state.messages.append({
                "role": "user",
                "content": prompt,
                "timestamp": pd.Timestamp.now()
            })

            with st.chat_message("user"):
                st.markdown(prompt)

            # Process and display response
            with st.chat_message("assistant"):
                with st.spinner("Analyzing your query..."):
                    response = executor.query_with_rag(prompt)

                    message = {
                        "role": "assistant",
                        "question": prompt,
                        "content": response.get("enhanced_response", "An error occurred while processing your request."),
                        "timestamp": pd.Timestamp.now()
                    }

                    # Add data and query for valid ocean data queries
                    if response["success"] and response.get("data") and not response.get("fallback_used", False):
                        message["data"] = response["data"]
                        message["query"] = response["generated_query"]
                    elif response.get("fallback_used", False):
                        message["fallback"] = True
                    elif response["success"]:
                        # Query ran but matched nothing. Keep the SQL so the
                        # proximity layer can still identify the location asked
                        # about and offer the genuinely nearest observations.
                        message["empty_result"] = True
                        message["query"] = response.get("generated_query")
                    else:
                        # Query could not execute at all (bad alias, wrong units,
                        # syntax). For location questions the proximity layer can
                        # still answer deterministically, so keep the SQL and the
                        # technical detail rather than discarding them.
                        message["query_failed"] = True
                        message["query"] = response.get("generated_query")
                        message["error_detail"] = response.get("error")

                    st.session_state.messages.append(message)
                    st.rerun()
        else:
            st.error("❌ AI system is not available. Please check your Ollama installation.")

    # Footer
    st.markdown(theme.footer(), unsafe_allow_html=True)


if __name__ == "__main__":
    main()