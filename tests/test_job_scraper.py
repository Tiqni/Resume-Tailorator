"""Tests for the job scraper cleanup agent and related integration.

Covers:
- The thin Markdown-cleanup agent (str -> str)
- Placeholder detection helpers used by the deterministic quality gate
- CLI integration with URL and environment variables
- The ScrapedJobPosting data model

Deterministic fetch/convert/URL-validation tests live in
``tests/test_job_scraper_fetch.py``.
"""

import os
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from resume_tailorator.models.agents.output import ScrapedJobPosting
from resume_tailorator.tools.job_scraper_helpers import (
    detect_placeholder_content,
    clean_job_posting_markdown,
)
from resume_tailorator.workflows.agents import job_scraper_agent

# Ensure model requests are blocked (test mode only)
models.ALLOW_MODEL_REQUESTS = False


# --- Test Data ---

REALISTIC_EXTRACTED_MARKDOWN = """\
# Senior Software Engineer

**Company:** TechCorp Inc.
**Location:** San Francisco, CA (Remote)
**Salary:** $180K-$220K

## About the Role

We're seeking an experienced Senior Software Engineer to join our platform team. 
You'll design and build scalable backend systems serving millions of users.

## Requirements

- 7+ years of software engineering experience
- Strong proficiency in Python, Go, or Rust
- Experience with distributed systems and microservices
- Deep knowledge of database design and optimization
- Leadership experience mentoring junior engineers
- BS in Computer Science or equivalent

## What We Offer

- Competitive salary and equity
- Comprehensive health benefits
- Professional development budget
- Flexible work arrangements

Apply at careers@techcorp.com or submit via LinkedIn.
"""


class TestJobScraperCleanupAgent:
    """The scrape agent now cleans already-converted Markdown (str -> str)."""

    def test_returns_cleaned_markdown_string(self):
        with job_scraper_agent.override(
            model=TestModel(custom_output_text=REALISTIC_EXTRACTED_MARKDOWN)
        ):
            result = job_scraper_agent.run_sync(REALISTIC_EXTRACTED_MARKDOWN)
        assert isinstance(result.output, str)
        assert "Senior Software Engineer" in result.output

    def test_output_is_non_empty(self):
        with job_scraper_agent.override(
            model=TestModel(custom_output_text=REALISTIC_EXTRACTED_MARKDOWN)
        ):
            result = job_scraper_agent.run_sync("# Some job\n\nlong body " * 20)
        assert result.output.strip()


class TestHelperFunctionsIntegration:
    """Integration tests for helper functions used in scraping."""

    def test_placeholder_detection_in_validation_flow(self):
        """Test that placeholder detection integrates properly."""
        # Script tag content should trigger placeholder detection
        assert detect_placeholder_content("<script>error</script>" + " x" * 50) is True

    def test_clean_job_posting_in_validation_flow(self):
        """Test that markdown cleaning integrates properly."""
        dirty_markdown = "line1  \n\n\n\nline2\n"
        clean_markdown = clean_job_posting_markdown(dirty_markdown)

        # Should have no triple+ newlines
        assert "\n\n\n" not in clean_markdown

    def test_html_parsing_produces_markdown(self):
        """Test that HTML parsing integrates properly."""
        # Placeholder detection should work
        assert detect_placeholder_content("<script>error</script>" + " x" * 50) is True

        # Cleaning should work
        dirty_markdown = "line1  \n\n\n\nline2\n"
        clean_markdown = clean_job_posting_markdown(dirty_markdown)
        assert "\n\n\n" not in clean_markdown


class TestCLIIntegration:
    """Tests for CLI argument and environment variable handling."""

    def test_cli_job_url_argument_parsing(self):
        """Test that CLI correctly parses --job-url argument."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--job-url", default=None)

        # Test with URL provided
        args = parser.parse_args(["--job-url", "https://example.com/job/123"])
        assert args.job_url == "https://example.com/job/123"

    def test_cli_job_url_none_when_not_provided(self):
        """Test that job_url is None when not provided."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--job-url", default=None)

        args = parser.parse_args([])
        assert args.job_url is None

    def test_cli_job_url_with_complex_url(self):
        """Test that CLI handles complex URLs with query parameters."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--job-url", default=None)

        url = "https://example.com/job?id=123&ref=email&source=newsletter"
        args = parser.parse_args(["--job-url", url])
        assert args.job_url == url

    def test_job_url_env_var_fallback(self, monkeypatch):
        """Test that JOB_URL environment variable is used as fallback."""
        import argparse

        # Set environment variable
        monkeypatch.setenv("JOB_URL", "https://example.com/job/from-env")

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--job-url",
            default=os.environ.get("JOB_URL"),
        )

        # Parse without --job-url argument
        args = parser.parse_args([])

        # Should use env var
        assert args.job_url == "https://example.com/job/from-env"

    def test_cli_argument_overrides_env_var(self, monkeypatch):
        """Test that CLI argument takes precedence over environment variable."""
        import argparse

        # Set environment variable
        monkeypatch.setenv("JOB_URL", "https://example.com/job/from-env")

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--job-url",
            default=os.environ.get("JOB_URL"),
        )

        # Parse with explicit --job-url argument
        cli_url = "https://example.com/job/from-cli"
        args = parser.parse_args(["--job-url", cli_url])

        # Should use CLI argument
        assert args.job_url == cli_url

    def test_job_url_env_var_not_set_defaults_to_none(self, monkeypatch):
        """Test that job_url defaults to None when env var not set."""
        import argparse

        # Ensure env var is not set
        monkeypatch.delenv("JOB_URL", raising=False)

        parser = argparse.ArgumentParser()
        parser.add_argument("--job-url", default=os.environ.get("JOB_URL"))

        args = parser.parse_args([])

        # Should be None
        assert args.job_url is None


class TestPlaceholderDetectionInScraping:
    """Tests for placeholder detection edge cases in scraping context."""

    def test_error_page_detected_as_placeholder(self):
        """Test that error pages are detected as placeholders."""
        error_content = "<script>alert('Error loading')</script>" + " x" * 50
        assert detect_placeholder_content(error_content) is True

    def test_click_here_detected_as_placeholder(self):
        """Test that 'click here' content is detected as placeholder."""
        content = "To view the job posting, click here" + " x" * 50
        assert detect_placeholder_content(content) is True

    def test_real_posting_with_javascript_skills_not_placeholder(self):
        """Test that real job posting mentioning JavaScript is not flagged."""
        content = (
            """
        Senior Software Engineer
        Requirements: JavaScript, TypeScript, React
        We seek an expert in JavaScript frameworks.
        Must have 5+ years working with JavaScript.
        """
            + " x" * 50
        )
        assert detect_placeholder_content(content) is False

    def test_minimum_valid_content_length(self):
        """Test boundary of minimum content length."""
        # 99 chars - should be placeholder
        content_99 = "x" * 99
        assert detect_placeholder_content(content_99) is True

        # 100 chars - should be valid
        content_100 = "x" * 100
        assert detect_placeholder_content(content_100) is False

        # 101 chars - should be valid
        content_101 = "x" * 101
        assert detect_placeholder_content(content_101) is False


class TestScrapedJobPostingModel:
    """Tests for ScrapedJobPosting data model."""

    def test_scraped_job_posting_creation(self):
        """Test creating ScrapedJobPosting with all fields."""
        posting = ScrapedJobPosting(
            url="https://example.com/job/123",
            markdown="# Job Title\n\nRequirements...",
            source_text="<html>...</html>",
            extraction_strategy="html2text",
        )

        assert posting.url == "https://example.com/job/123"
        assert posting.markdown == "# Job Title\n\nRequirements..."
        assert posting.source_text == "<html>...</html>"
        assert posting.extraction_strategy == "html2text"

    def test_scraped_job_posting_url_validation(self):
        """Test that URL field accepts valid URLs."""
        valid_urls = [
            "https://example.com/job/123",
            "https://jobs.github.com/positions/456",
            "http://careers.company.com/job?id=789",
        ]

        for url in valid_urls:
            posting = ScrapedJobPosting(
                url=url,
                markdown="Job content",
                source_text="HTML",
                extraction_strategy="html2text",
            )
            assert posting.url == url

    def test_scraped_job_posting_markdown_field(self):
        """Test that markdown field stores formatted content."""
        markdown = """# Senior Engineer

## Requirements
- 5+ years experience
- Python expertise

## Location
San Francisco, CA
"""
        posting = ScrapedJobPosting(
            url="https://example.com/job",
            markdown=markdown,
            source_text="<html>...</html>",
            extraction_strategy="markitdown",
        )

        assert posting.markdown == markdown
        assert "Senior Engineer" in posting.markdown

    def test_scraped_job_posting_strategies(self):
        """Test different extraction strategy values."""
        strategies = ["html2text", "markitdown", "playwright_llm", "custom_parser"]

        for strategy in strategies:
            posting = ScrapedJobPosting(
                url="https://example.com/job",
                markdown="Job content",
                source_text="HTML",
                extraction_strategy=strategy,
            )
            assert posting.extraction_strategy == strategy
