"""Ledger crawler: reads marketplace pages at a polite pace and extracts licence clauses.

Kept separate from the scanner on purpose. The scanner is offline, deterministic and safe to run in
a loop over a rotation. This module touches other people's servers, so it is a command you run
deliberately, with your own contact address in the User-Agent, and its fetch log is an artefact.
"""

from .build import SiteConfig, build
from .extract import Page, classify, extract, normalise
from .policy import FetchPolicy, FetchResult

__all__ = ["SiteConfig", "build", "Page", "classify", "extract", "normalise", "FetchPolicy", "FetchResult"]
