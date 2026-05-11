"""Roster seeder for the bulletin harness.

Discovers parishes from diocesan directories and produces roster entries
the harness can ingest. See `python -m bulletin_parser.seeder --help`.
"""

from .dioceses import Diocese, US_DIOCESES, by_id, by_state, with_directory
from .directory_scrapers import (
    DirectoryScraper,
    GenericHtmlListScraper,
    ScrapedParish,
    SitemapScraper,
)
from .geocoder import (
    GeocodeError,
    GeocodeResult,
    Geocoder,
    NominatimGeocoder,
    geocode_pending,
)
from .host_detector import DetectionResult, HostDetector, detect_from_html
from .orchestrator import Seeder, SeedingReport

__all__ = [
    "Diocese", "US_DIOCESES", "by_id", "by_state", "with_directory",
    "DirectoryScraper", "GenericHtmlListScraper", "SitemapScraper",
    "ScrapedParish",
    "DetectionResult", "HostDetector", "detect_from_html",
    "Seeder", "SeedingReport",
    "Geocoder", "GeocodeResult", "GeocodeError", "NominatimGeocoder",
    "geocode_pending",
]
