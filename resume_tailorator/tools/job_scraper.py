"""Deterministic job-posting fetch + Markdown conversion (no LLM).

Fetches a rendered job posting with Playwright (handling JS-heavy SPAs),
converts the full page body to Markdown via the existing helpers, runs a
pure-Python quality gate, and returns a RawScrape for the thin LLM cleanup
pass. Replaces the old in-agent fetch_webpage/validate_extraction tools.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from resume_tailorator.tools.job_scraper_helpers import (
    clean_job_posting_markdown,
    detect_placeholder_content,
    parse_html_with_html2text,
    parse_html_with_markitdown,
)

logger = logging.getLogger(__name__)

# Navigation / settle tuning (milliseconds).
_FETCH_TIMEOUT_MS = 30_000  # hard cap on goto(domcontentloaded)
_SETTLE_MS = 5_000  # best-effort networkidle wait after the DOM is parsed
_RETRY_SETTLE_MS = 3_000  # extra wait for the single retry when body looks short
_MIN_CONTENT_CHARS = 200  # below this, treat as not-yet-rendered / placeholder

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ScrapeError(RuntimeError):
    """Raised when a job posting cannot be fetched or extracted."""


@dataclass(frozen=True)
class RawScrape:
    """Deterministic scrape result handed to the thin LLM cleanup pass."""

    markdown_raw: str
    source_text: str
    extraction_strategy: str  # "markitdown" or "html2text"


def validate_job_url(url: str) -> None:
    """Raise ScrapeError if url is not a well-formed http(s) URL."""
    if not url or not isinstance(url, str):
        raise ScrapeError(f"Invalid URL provided: {url!r}")
    if not url.startswith(("http://", "https://")):
        raise ScrapeError(f"URL must start with http:// or https://: {url}")


def html_to_markdown(html: str) -> tuple[str, str]:
    """Convert HTML to cleaned Markdown, returning (markdown, strategy).

    Tries markitdown first, falls back to html2text. Raises ScrapeError if
    neither produces content.
    """
    markdown = parse_html_with_markitdown(html)
    strategy = "markitdown"
    if not markdown.strip():
        markdown = parse_html_with_html2text(html)
        strategy = "html2text"
    markdown = clean_job_posting_markdown(markdown)
    if not markdown.strip():
        raise ScrapeError("HTML produced no Markdown content")
    return markdown, strategy


def assert_quality(markdown: str) -> None:
    """Raise ScrapeError if extracted Markdown looks like a placeholder/error."""
    if detect_placeholder_content(markdown):
        raise ScrapeError(
            "Extracted content looks like a placeholder or error page, "
            "not a job posting"
        )
