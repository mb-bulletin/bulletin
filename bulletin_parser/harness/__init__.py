"""Ingestion harness for the bulletin parser.

Discovers, fetches, deduplicates, parses, and stores Catholic parish
bulletins on a schedule. See `python -m bulletin_parser.harness --help`.
"""

from .storage import Storage
from .fetcher import Fetcher
from .discovery import Discovery
from .orchestrator import Orchestrator, IngestionStats

__all__ = ["Storage", "Fetcher", "Discovery", "Orchestrator", "IngestionStats"]
