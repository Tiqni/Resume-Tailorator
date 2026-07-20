"""Tests for the deterministic job scraper module (no LLM, no real browser)."""

import pytest
from unittest.mock import AsyncMock

from resume_tailorator.tools.job_scraper import (
    RawScrape,
    ScrapeError,
    assert_quality,
    html_to_markdown,
    validate_job_url,
    _FETCH_TIMEOUT_MS,
    _SETTLE_MS,
    _RETRY_SETTLE_MS,
    _navigate_and_render,
    fetch_job_markdown,
)

REALISTIC_JOB_HTML = """\
<!DOCTYPE html>
<html><head><title>Senior Software Engineer</title></head>
<body>
<h1>Senior Software Engineer</h1>
<p>Company: TechCorp Inc. Location: Remote.</p>
<h2>Requirements</h2>
<ul>
<li>7+ years of software engineering experience</li>
<li>Strong proficiency in Python</li>
<li>Experience with distributed systems and microservices</li>
</ul>
<h2>What We Offer</h2>
<p>Competitive salary, equity, and comprehensive health benefits.</p>
</body></html>
"""

PLACEHOLDER_HTML = "<html><body><h1>Page Not Found</h1><p>404 error</p></body></html>"


class TestValidateJobUrl:
    def test_valid_https_passes(self):
        assert validate_job_url("https://example.com/job/123") is None

    def test_valid_http_passes(self):
        assert validate_job_url("http://example.com/job/123") is None

    def test_missing_protocol_raises(self):
        with pytest.raises(ScrapeError):
            validate_job_url("example.com/job/123")

    def test_wrong_protocol_raises(self):
        with pytest.raises(ScrapeError):
            validate_job_url("ftp://example.com/job/123")

    def test_empty_string_raises(self):
        with pytest.raises(ScrapeError):
            validate_job_url("")

    def test_none_raises(self):
        with pytest.raises(ScrapeError):
            validate_job_url(None)  # type: ignore[arg-type]


class TestHtmlToMarkdown:
    def test_markitdown_strategy_on_real_html(self):
        markdown, strategy = html_to_markdown(REALISTIC_JOB_HTML)
        assert strategy == "markitdown"
        assert "Senior Software Engineer" in markdown

    def test_falls_back_to_html2text(self, monkeypatch):
        monkeypatch.setattr(
            "resume_tailorator.tools.job_scraper.parse_html_with_markitdown",
            lambda html: "",
        )
        markdown, strategy = html_to_markdown(REALISTIC_JOB_HTML)
        assert strategy == "html2text"
        assert markdown.strip()
        assert "Senior Software Engineer" in markdown

    def test_empty_conversion_raises(self, monkeypatch):
        monkeypatch.setattr(
            "resume_tailorator.tools.job_scraper.parse_html_with_markitdown",
            lambda html: "",
        )
        monkeypatch.setattr(
            "resume_tailorator.tools.job_scraper.parse_html_with_html2text",
            lambda html: "",
        )
        with pytest.raises(ScrapeError):
            html_to_markdown("<html></html>")


class TestAssertQuality:
    def test_real_posting_passes(self):
        markdown, _ = html_to_markdown(REALISTIC_JOB_HTML)
        assert assert_quality(markdown) is None

    def test_placeholder_raises(self):
        assert_md, _ = html_to_markdown(PLACEHOLDER_HTML)
        with pytest.raises(ScrapeError):
            assert_quality(assert_md)


def test_rawscrape_is_frozen():
    raw = RawScrape(markdown_raw="x", source_text="y", extraction_strategy="markitdown")
    with pytest.raises(Exception):
        raw.markdown_raw = "z"  # type: ignore[misc]


def _mock_page(*, body_text: str, content: str, settle_error: Exception | None = None):
    page = AsyncMock()
    page.content.return_value = content
    page.inner_text.return_value = body_text
    if settle_error is not None:
        page.wait_for_load_state.side_effect = settle_error
    return page


class TestNavigateAndRender:
    @pytest.mark.anyio
    async def test_survives_networkidle_timeout(self):
        """Regression: networkidle never settling must NOT fail the fetch."""
        page = _mock_page(
            body_text="A" * 500,
            content=REALISTIC_JOB_HTML,
            settle_error=Exception("Timeout 5000ms exceeded"),
        )
        result = await _navigate_and_render(page, "https://careers.vinted.com/x")
        assert result == REALISTIC_JOB_HTML
        page.goto.assert_awaited_once_with(
            "https://careers.vinted.com/x",
            wait_until="domcontentloaded",
            timeout=_FETCH_TIMEOUT_MS,
        )
        page.wait_for_load_state.assert_awaited_once_with(
            "networkidle", timeout=_SETTLE_MS
        )
        page.wait_for_timeout.assert_not_awaited()

    @pytest.mark.anyio
    async def test_retries_once_on_short_body(self):
        page = _mock_page(body_text="tiny", content=REALISTIC_JOB_HTML)
        result = await _navigate_and_render(page, "https://example.com/job")
        assert result == REALISTIC_JOB_HTML
        page.wait_for_timeout.assert_awaited_once_with(_RETRY_SETTLE_MS)

    @pytest.mark.anyio
    async def test_no_retry_on_long_body(self):
        page = _mock_page(body_text="B" * 500, content=REALISTIC_JOB_HTML)
        await _navigate_and_render(page, "https://example.com/job")
        page.wait_for_timeout.assert_not_awaited()


class TestFetchJobMarkdown:
    @pytest.mark.anyio
    async def test_success_returns_rawscrape(self, monkeypatch):
        monkeypatch.setattr(
            "resume_tailorator.tools.job_scraper._render_html",
            AsyncMock(return_value=REALISTIC_JOB_HTML),
        )
        raw = await fetch_job_markdown("https://example.com/job/123")
        assert isinstance(raw, RawScrape)
        assert "Senior Software Engineer" in raw.markdown_raw
        assert raw.extraction_strategy == "markitdown"
        assert raw.source_text == REALISTIC_JOB_HTML

    @pytest.mark.anyio
    async def test_invalid_url_raises_before_fetch(self):
        with pytest.raises(ScrapeError):
            await fetch_job_markdown("not-a-url")

    @pytest.mark.anyio
    async def test_render_failure_wrapped_as_scrape_error(self, monkeypatch):
        monkeypatch.setattr(
            "resume_tailorator.tools.job_scraper._render_html",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        with pytest.raises(ScrapeError):
            await fetch_job_markdown("https://example.com/job")

    @pytest.mark.anyio
    async def test_placeholder_content_raises(self, monkeypatch):
        monkeypatch.setattr(
            "resume_tailorator.tools.job_scraper._render_html",
            AsyncMock(return_value=PLACEHOLDER_HTML),
        )
        with pytest.raises(ScrapeError):
            await fetch_job_markdown("https://example.com/job")
