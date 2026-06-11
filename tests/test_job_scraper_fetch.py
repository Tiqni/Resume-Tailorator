"""Tests for the deterministic job scraper module (no LLM, no real browser)."""

import pytest

from resume_tailorator.tools.job_scraper import (
    RawScrape,
    ScrapeError,
    assert_quality,
    html_to_markdown,
    validate_job_url,
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
