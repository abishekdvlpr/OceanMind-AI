# --- data_processing_verbose.py ---
"""
Verbose command-line runner for the ARGO ingestion pipeline.

This script no longer contains a second, divergent copy of the parser. It is a
thin diagnostic wrapper around the single canonical implementation in
data_processing.ArgoDataProcessor, so the CLI and the Streamlit button can
never disagree about how data is parsed again.

Usage:
    python data_processing_verbose.py
    python data_processing_verbose.py --max-files 2
    python data_processing_verbose.py --no-reset
    python data_processing_verbose.py --data-dir ./data
"""

import argparse
import logging
import os
import sys
import traceback

try:
    from config import DATA_PROCESSING_CONFIG
    from data_processing import ArgoDataProcessor
except ImportError as e:
    print(
        "FATAL ERROR: Could not import necessary modules. "
        f"Please check your project structure. Details: {e}"
    )
    sys.exit(1)


def _configure_logging(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
        force=True,
    )


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Ingest ARGO NetCDF files into PostgreSQL/PostGIS and ChromaDB."
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory containing *.nc files (defaults to config value).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Maximum number of NetCDF files to ingest.",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Append to the existing database instead of wiping it first.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG level logging.",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    _configure_logging(args.verbose)

    print("=" * 60)
    print("   Running ARGO Data Processor in Verbose Mode")
    print("=" * 60)

    data_dir = args.data_dir or DATA_PROCESSING_CONFIG["data_dir"]
    max_files = args.max_files if args.max_files is not None else DATA_PROCESSING_CONFIG.get("max_files")

    print(f"-> Data directory : {os.path.abspath(data_dir)}")
    print(f"-> Max files      : {max_files}")
    print(f"-> Reset first    : {not args.no_reset}")

    try:
        print("\n-> Initializing processor (database + vector store)...")
        processor = ArgoDataProcessor(data_dir=data_dir)
        print("-> Processor initialized successfully.")
    except Exception as e:
        print("\n-> FATAL ERROR: Could not initialize the processor.")
        print("-> Check that PostgreSQL is running and config.py credentials are correct.")
        print(f"-> Details: {e}")
        traceback.print_exc()
        return 1

    try:
        print("\n-> Starting directory processing...\n")
        stats = processor.process_directory(
            max_files=max_files, reset=not args.no_reset
        )
    except Exception as e:
        print("\n-> A critical error occurred during processing.")
        print(f"-> Details: {e}")
        traceback.print_exc()
        return 1

    print("\n" + "=" * 60)
    print("   INGESTION SUMMARY")
    print("=" * 60)
    print(f"   NetCDF files found      : {stats['files_found']}")
    print(f"   NetCDF files ingested   : {stats['files_processed']}")
    print(f"   Float groups inserted   : {stats['floats_inserted']}")
    print(f"   Measurements inserted   : {stats['records_inserted']:,}")

    if stats["errors"]:
        print(f"\n   Warnings ({len(stats['errors'])}):")
        for problem in stats["errors"][:20]:
            print(f"     - {problem}")
        if len(stats["errors"]) > 20:
            print(f"     ... and {len(stats['errors']) - 20} more")

    try:
        summary = processor.db_manager.get_data_summary()
        if summary["available"]:
            print("\n   DATABASE COVERAGE")
            print(f"     Rows          : {summary['total_records']:,}")
            print(f"     Unique floats : {summary['unique_floats']:,}")
            print(f"     Time range    : {summary['time_min']} -> {summary['time_max']}")
            print(f"     Latitude      : {summary['lat_min']} -> {summary['lat_max']}")
            print(f"     Longitude     : {summary['lon_min']} -> {summary['lon_max']}")
            print(f"     Max depth     : {summary['depth_max']} m")
        print(f"     Vector store  : {processor.vector_store.count()} float summaries")
    except Exception as e:
        print(f"\n   Could not read post-ingestion summary: {e}")

    print("=" * 60)
    return 0 if stats["records_inserted"] else 1


if __name__ == "__main__":
    sys.exit(main())
