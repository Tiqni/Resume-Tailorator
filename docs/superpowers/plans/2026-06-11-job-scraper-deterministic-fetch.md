# Job Scraper Deterministic Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile LLM-driven scraper (which reads raw HTML and waits for `networkidle`) with a deterministic Playwright fetch + Markdown conversion step, followed by a thin LLM cleanup pass on already-clean Markdown.

**Architecture:** A new pure-Python module `tools/job_scraper.py` owns fetch + convert + quality gate (no LLM, unit-testable). `job_scraper_agent` becomes a tool-less `str→str` cleanup agent on the `fast` tier. `main.py` calls `fetch_job_markdown(url)` then runs the agent on the resulting Markdown. Only the `job_posting_markdown` string is persisted (unchanged contract), so no `ScrapedJobPosting` assembly is needed.

**Tech Stack:** Python 3.13, `uv`, Playwright (chromium, async), `markitdown`/`html2text` (existing helpers), `pydantic-ai` 1.24, `pytest` + `pytest-anyio`, `ruff`.

**Spec:** `docs/superpowers/specs/2026-06-11-job-scraper-deterministic-fetch-design.md`

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `resume_tailorator/tools/job_scraper.py` | Deterministic fetch + HTML→Markdown + quality gate; `RawScrape`, `ScrapeError`, `fetch_job_markdown`, `validate_job_url`, `html_to_markdown`, `assert_quality`, `_navigate_and_render`, `_render_html` | **Create** |
| `resume_tailorator/tools/job_scraper_helpers.py` | Existing conversion/clean/placeholder helpers — finally wired in by the new module | Unchanged (consumed) |
| `resume_tailorator/workflows/agents.py` | `job_scraper_agent` → tool-less `str` cleanup agent; drop `fetch_webpage`/`validate_extraction`/`scraper_agent`; tier `strong`→`fast` | **Modify** |
| `resume_tailorator/tools/playwright.py` | Dead (`read_job_content_file` + commented block) | **Delete** |
| `resume_tailorator/main.py` | `_tailor_impl` calls `fetch_job_markdown` then the cleanup agent; drop `ScrapedJobPosting` import/branch | **Modify** |
| `tests/test_job_scraper_fetch.py` | Unit tests for the new module (conversion, quality gate, URL validation, navigation/retry, `networkidle`-timeout regression) | **Create** |
| `tests/test_job_scraper.py` | Drop dead `validate_extraction`/`fetch_webpage`/quality-score tests; rewrite agent tests for `str` output | **Modify** |
| `tests/test_cli_typer.py` | Patch `fetch_job_markdown`; agent output is now a Markdown `str` | **Modify** |

**Decisions (locked in spec):** keep Playwright; full `<body>`→Markdown (no selector targeting / readability lib); thin LLM cleanup retained; cleanup on `fast` tier; one retry on short content.

---

## Task 1: Deterministic conversion + quality gate (pure functions)

Build the LLM-free parts of the new module first: URL validation, HTML→Markdown (markitdown → html2text fallback), and the placeholder/length quality gate. These have no Playwright dependency and are trivially testable.

**Files:**
- Create: `resume_tailorator/tools/job_scraper.py`
- Test: `tests/test_job_scraper_fetch.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_job_scraper_fetch.py`:

```python
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

PLACEHOLDER_HTML = (
    "<html><body><h1>Page Not Found</h1><p>404 error</p></body></html>"
)


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_job_scraper_fetch.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailorator.tools.job_scraper'`.

- [ ] **Step 3: Create the module with the pure functions**

Create `resume_tailorator/tools/job_scraper.py`:

```python
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
_FETCH_TIMEOUT_MS = 30_000   # hard cap on goto(domcontentloaded)
_SETTLE_MS = 5_000           # best-effort networkidle wait after the DOM is parsed
_RETRY_SETTLE_MS = 3_000     # extra wait for the single retry when body looks short
_MIN_CONTENT_CHARS = 200     # below this, treat as not-yet-rendered / placeholder

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_job_scraper_fetch.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add resume_tailorator/tools/job_scraper.py tests/test_job_scraper_fetch.py
git commit -m "$(cat <<'EOF'
feat(scraper): deterministic HTML->Markdown conversion + quality gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Playwright fetch with resilient wait (the Vinted fix)

Add the navigation logic that fixes the `networkidle` timeout, plus the orchestrating `fetch_job_markdown`. `_navigate_and_render(page, url)` takes an already-open page so it can be tested with a mock page (no real browser). `_render_html` owns the browser lifecycle and is exercised only via monkeypatch.

**Files:**
- Modify: `resume_tailorator/tools/job_scraper.py`
- Test: `tests/test_job_scraper_fetch.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_job_scraper_fetch.py`:

```python
from unittest.mock import AsyncMock

from resume_tailorator.tools.job_scraper import (
    _FETCH_TIMEOUT_MS,
    _navigate_and_render,
    fetch_job_markdown,
)


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
        page.wait_for_timeout.assert_not_awaited()

    @pytest.mark.anyio
    async def test_retries_once_on_short_body(self):
        page = _mock_page(body_text="tiny", content=REALISTIC_JOB_HTML)
        result = await _navigate_and_render(page, "https://example.com/job")
        assert result == REALISTIC_JOB_HTML
        page.wait_for_timeout.assert_awaited_once()

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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_job_scraper_fetch.py -k "Navigate or FetchJobMarkdown" -q`
Expected: FAIL — `ImportError: cannot import name '_navigate_and_render'` (and `fetch_job_markdown`).

- [ ] **Step 3: Add the fetch functions to the module**

Append to `resume_tailorator/tools/job_scraper.py`:

```python
async def _navigate_and_render(page, url: str) -> str:
    """Drive an open Playwright page to a rendered HTML string.

    Navigates with wait_until="domcontentloaded" (fast, reliable), then makes a
    BEST-EFFORT networkidle settle that is swallowed on timeout — the core fix
    for sites whose network never goes idle. Retries once with a longer settle
    if the visible body text is suspiciously short.
    """
    await page.goto(url, wait_until="domcontentloaded", timeout=_FETCH_TIMEOUT_MS)
    try:
        await page.wait_for_load_state("networkidle", timeout=_SETTLE_MS)
    except Exception:
        # networkidle is a bonus, never a gate: analytics/websockets keep the
        # network busy forever on many job boards. Proceed with what rendered.
        logger.debug("networkidle settle timed out; proceeding", extra={"url": url})
    body_text = await page.inner_text("body")
    if len(body_text.strip()) < _MIN_CONTENT_CHARS:
        logger.debug("body text short; one retry settle", extra={"url": url})
        await page.wait_for_timeout(_RETRY_SETTLE_MS)
    return await page.content()


async def _render_html(url: str) -> str:
    """Launch a headless browser and return the rendered HTML for url."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent=_USER_AGENT)
            page = await context.new_page()
            return await _navigate_and_render(page, url)
        finally:
            await browser.close()


async def fetch_job_markdown(url: str) -> RawScrape:
    """Fetch a job posting and return cleaned Markdown (deterministic, no LLM).

    Raises ScrapeError on a bad URL, navigation failure, or low-quality content.
    """
    validate_job_url(url)
    logger.info("fetch_job_markdown_start", extra={"url": url})
    try:
        html = await _render_html(url)
    except ScrapeError:
        raise
    except Exception as e:
        raise ScrapeError(f"Failed to fetch {url}: {e}") from e
    markdown, strategy = html_to_markdown(html)
    assert_quality(markdown)
    logger.info(
        "fetch_job_markdown_success",
        extra={"url": url, "strategy": strategy, "length": len(markdown)},
    )
    return RawScrape(
        markdown_raw=markdown, source_text=html, extraction_strategy=strategy
    )
```

- [ ] **Step 4: Run the full module test file to verify it passes**

Run: `uv run pytest tests/test_job_scraper_fetch.py -q`
Expected: PASS (all tests, including Task 1).

- [ ] **Step 5: Commit**

```bash
git add resume_tailorator/tools/job_scraper.py tests/test_job_scraper_fetch.py
git commit -m "$(cat <<'EOF'
feat(scraper): resilient Playwright fetch (domcontentloaded + best-effort settle)

Replaces wait_until="networkidle", which timed out on JS-heavy boards like
Vinted. networkidle becomes a best-effort settle, swallowed on timeout.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Reduce `job_scraper_agent` to a thin Markdown cleanup pass

Strip the agent down to `str → str`: remove its `fetch_webpage`/`validate_extraction` tools, change `output_type` to `str`, rewrite the system prompt for clean-Markdown input, move it to the `fast` tier, and delete the dead `scraper_agent`. Update the agent's tests in the same commit so the suite stays green.

**Files:**
- Modify: `resume_tailorator/workflows/agents.py` (lines 33–36 import, 189 tier, 321–335 `scraper_agent`, 609–774 agent + tools)
- Modify: `tests/test_job_scraper.py` (imports 31–40; delete `TestValidateExtraction`, `TestURLValidation`, `TestExtractionQualityScoring`; rewrite `TestJobScraperAgent`)

- [ ] **Step 1: Rewrite the agent tests first**

In `tests/test_job_scraper.py`, replace the import block (current lines ~31–40):

```python
# Import agent and tools only if playwright is available
if HAS_PLAYWRIGHT:
    from resume_tailorator.workflows.agents import (
        job_scraper_agent,
        validate_extraction,
    )
else:
    # Define dummy validate_extraction for non-agent tests
    def validate_extraction(raw_html: str, extracted_markdown: str) -> dict:
        """Dummy validate_extraction for when playwright not available."""
        raise RuntimeError("playwright not installed")
```

with:

```python
from resume_tailorator.workflows.agents import job_scraper_agent
```

(The `HAS_PLAYWRIGHT` / `find_spec` lines above it may remain; the agent no longer imports Playwright at module load.)

Then **replace the entire `TestJobScraperAgent` class** (current lines ~140–226) with:

```python
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
```

Then **delete these three now-obsolete classes entirely** (they test the removed `validate_extraction`/`fetch_webpage`):
- `TestValidateExtraction` (current lines ~229–342)
- `TestURLValidation` (current lines ~344–399) — URL validation is now covered by `TestValidateJobUrl` in `tests/test_job_scraper_fetch.py`
- `TestExtractionQualityScoring` (current lines ~401–467)

Leave `TestHelperFunctionsIntegration`, `TestCLIIntegration`, `TestPlaceholderDetectionInScraping`, and `TestScrapedJobPostingModel` untouched.

- [ ] **Step 2: Run the agent tests to verify they fail**

Run: `uv run pytest tests/test_job_scraper.py -q`
Expected: FAIL — `ImportError`/`TypeError`: `custom_output_text` produces a non-`str` because the agent still declares `output_type=ScrapedJobPosting`, and/or collection errors from the deleted classes' removed symbols. (This confirms the tests now demand the new agent shape.)

- [ ] **Step 3: Rewrite the agent and remove dead code in `agents.py`**

In `resume_tailorator/workflows/agents.py`:

(a) Remove the now-unused imports. Delete line 33 and the import block on lines 34–36:

```python
from resume_tailorator.tools.playwright import read_job_content_file
from resume_tailorator.tools.job_scraper_helpers import (
    detect_placeholder_content,
)
```

(`detect_placeholder_content` was only used by the deleted `validate_extraction`; `read_job_content_file` only by the deleted `scraper_agent`. Keep the `ModelRetry` and `RunContext` imports — the quality gate still uses them.)

(b) Change the Scraper tier (line 189) from:

```python
    "Scraper": "strong",  # job_scraper_agent; wired in a later task
```

to:

```python
    "Scraper": "fast",  # job_scraper_agent: cleanup pass on clean Markdown
```

(c) Delete the dead `scraper_agent` block (current lines ~321–335), including its `# --- Agent 0: The Scraper ---` comment header.

(d) Replace the whole `job_scraper_agent` definition + its system prompt + `fetch_webpage` + `validate_extraction` (current lines ~609–774) with:

```python
job_scraper_agent = Agent(
    _DEFAULT_MODEL,
    model_settings=MODEL_SETTINGS,
    output_type=str,
    retries=3,
)


@job_scraper_agent.system_prompt
async def build_scraper_instructions() -> str:
    """System prompt: isolate the job posting from already-clean Markdown."""
    return """You clean up a job posting that has already been converted to Markdown.

The Markdown you receive is the FULL page body, so it surrounds the real posting
with navigation, cookie/consent banners, search bars, "related jobs", social
links, and footer boilerplate.

Your task: return ONLY the job posting as clean Markdown.

CRITICAL RULES:
1. Never invent or add information. Only keep and lightly tidy what is present.
2. Remove site chrome: nav menus, cookie/consent banners, search bars,
   related/similar jobs, social/share links, and footers.
3. Keep the role title, company, location, description, responsibilities,
   requirements, and benefits.
4. Preserve wording. Do not paraphrase, summarize, or editorialize.
5. Output Markdown only. No commentary and no code fences."""
```

- [ ] **Step 4: Run the affected tests to verify they pass**

Run: `uv run pytest tests/test_job_scraper.py -q`
Expected: PASS. Then confirm nothing else imported the removed symbols:

Run: `uv run pytest -q`
Expected: PASS (full suite — catches any stray `validate_extraction`/`fetch_webpage`/`scraper_agent`/`read_job_content_file` references).

- [ ] **Step 5: Commit**

```bash
git add resume_tailorator/workflows/agents.py tests/test_job_scraper.py
git commit -m "$(cat <<'EOF'
refactor(scraper): thin Markdown-cleanup agent on the fast tier

Drop fetch_webpage/validate_extraction tools and the dead scraper_agent;
job_scraper_agent now takes clean Markdown and returns cleaned Markdown (str).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire `fetch_job_markdown` into the CLI

`_tailor_impl` currently asks the agent to fetch from a URL. Change it to fetch deterministically first, then run the cleanup agent on the Markdown. The agent output is now a `str`, so drop the `ScrapedJobPosting` import and the `isinstance` branch.

**Files:**
- Modify: `resume_tailorator/main.py` (import line 24; scrape block lines ~417–447)
- Modify: `tests/test_cli_typer.py` (success + failure tests must patch `fetch_job_markdown`)

- [ ] **Step 1: Update the CLI tests first**

In `tests/test_cli_typer.py`:

(a) Add an import and a module-level constant near the top (after the existing imports):

```python
from unittest.mock import AsyncMock  # already imported on line 4 — keep one copy
from resume_tailorator.tools.job_scraper import RawScrape

CLEANED_JOB_MD = "# Senior Software Engineer\n\nRequirements: Python, distributed systems."
```

(b) In `test_tailor_command_success` (and `test_tailor_command_failed_audit_exits_zero`), the patch context currently does:

```python
        patch(
            "resume_tailorator.main.job_scraper_agent.run",
            AsyncMock(return_value=MagicMock(output=scraped_job)),
        ),
```

Replace each with two patches — a deterministic fetch and a `str`-output cleanup agent:

```python
        patch(
            "resume_tailorator.main.fetch_job_markdown",
            AsyncMock(
                return_value=RawScrape(
                    markdown_raw="raw body markdown",
                    source_text="<html>...</html>",
                    extraction_strategy="markitdown",
                )
            ),
        ),
        patch(
            "resume_tailorator.main.job_scraper_agent.run",
            AsyncMock(return_value=MagicMock(output=CLEANED_JOB_MD)),
        ),
```

Delete the now-unused `scraped_job = _make_scraped_job()` line in those tests.

(c) In `test_tailor_command_scraping_failure`, move the failure to the fetch step:

```python
    mock_fetch = AsyncMock(side_effect=Exception("Network error"))

    with patch("resume_tailorator.main.fetch_job_markdown", mock_fetch):
```

(d) Remove the now-unused `_make_scraped_job` helper (lines ~71–80) and drop `ScrapedJobPosting` from the import on line 11 (it is only used by that helper). Verify with: `grep -n "ScrapedJobPosting\|_make_scraped_job" tests/test_cli_typer.py` — expect no remaining references.

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run: `uv run pytest tests/test_cli_typer.py -q`
Expected: FAIL — `AttributeError: <module 'resume_tailorator.main'> does not have the attribute 'fetch_job_markdown'` (it is not imported/used yet).

- [ ] **Step 3: Update `main.py`**

(a) Remove `ScrapedJobPosting` from the import on line 24 (keep the other names in that import group), and add the fetch import near the other `resume_tailorator` imports:

```python
from resume_tailorator.tools.job_scraper import fetch_job_markdown
```

(b) Replace the scrape block (current lines ~419–447, from `scrape_result = await run_agent(` through the `else:`/`raise typer.Exit(code=1)` that handles an unexpected output type) with:

```python
                raw = await fetch_job_markdown(job_url)
                scrape_result = await run_agent(
                    job_scraper_agent,
                    raw.markdown_raw,
                    verbose=verbose,
                    agent_label="Scraper",
                )
                job_posting_markdown = scrape_result.output
                if not job_posting_markdown.strip():
                    logger.error(
                        "job_posting_scraped_but_empty", extra={"url": job_url}
                    )
                    console.print(
                        "[red]❌ Job posting scraped but content is empty[/red]"
                    )
                    raise typer.Exit(code=1)
                logger.info(
                    "job_posting_scraped_successfully",
                    extra={
                        "url": job_url,
                        "content_length": len(job_posting_markdown),
                    },
                )
                console.print(f"✅ Job posting scraped successfully from {job_url}")
```

The surrounding `try` / `except (typer.Exit, KeyboardInterrupt): raise` / `except Exception as e:` block (with the red "Failed to scrape" message and the "💡 Tip" line) stays exactly as-is — it now also catches `ScrapeError` from `fetch_job_markdown`.

- [ ] **Step 4: Run the CLI tests, then the full suite**

Run: `uv run pytest tests/test_cli_typer.py -q`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS (full suite).

- [ ] **Step 5: Commit**

```bash
git add resume_tailorator/main.py tests/test_cli_typer.py
git commit -m "$(cat <<'EOF'
feat(cli): scrape via deterministic fetch_job_markdown + cleanup agent

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Delete the dead `tools/playwright.py`

The commented-out `fetch_job_content` and unused `read_job_content_file` are the only contents, and the sole importer (`scraper_agent`) is gone.

**Files:**
- Delete: `resume_tailorator/tools/playwright.py`

- [ ] **Step 1: Confirm no remaining importers**

Run: `grep -rn "tools.playwright\|read_job_content_file" resume_tailorator/ tests/`
Expected: no output (zero references).

- [ ] **Step 2: Delete the file**

```bash
git rm resume_tailorator/tools/playwright.py
```

- [ ] **Step 3: Run the full suite to verify nothing broke**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore(scraper): remove dead tools/playwright.py

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Full verification + graph refresh

**Files:** none (verification only).

- [ ] **Step 1: Lint and format check**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: both pass with no errors. If `ruff format --check` reports diffs, run `uv run ruff format .`, re-run tests, and amend the relevant commit.

- [ ] **Step 2: Full test suite (read the log, not just the exit banner)**

Run: `uv run pytest -q`
Expected: all tests pass; 0 failures, 0 errors. (CI pipes through `tee` and can mask failures — read the summary line.)

- [ ] **Step 3: Live smoke test against the original failing URL**

Run:
```bash
uv run resume-tailor tailor 'https://careers.vinted.com/jobs/j/4888772101' \
  '/Volumes/External/OneDrive/Documents/Resume/Staff Software Engineer.docx' \
  --model='openai:gpt-5.5' -v
```
Expected: `✅ Job posting scraped successfully from https://careers.vinted.com/...` — no `networkidle` TimeoutError. (Requires `playwright install chromium` and a valid OpenAI key. If the resume path is gone, substitute any local resume.)

- [ ] **Step 4: Refresh the knowledge graph**

Run: `graphify update .`
Expected: graph updates (AST-only, no API cost).

- [ ] **Step 5: Final commit (if Step 1 or 4 produced changes)**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(scraper): formatting + graph refresh

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- Deterministic fetch + convert (`fetch_job_markdown`) → Tasks 1–2. ✓
- `networkidle` → `domcontentloaded` + best-effort settle → Task 2, `_navigate_and_render` + regression test. ✓
- One retry on short content (< 200 chars) → Task 2. ✓
- markitdown → html2text fallback; `extraction_strategy` recorded → Task 1. ✓
- Pure-Python quality gate (placeholder + length) → Task 1 (`assert_quality`). ✓
- Thin LLM cleanup agent, no tools, `output_type=str`, `fast` tier → Task 3. ✓
- `main.py` wiring; only the Markdown string persisted (re-tailor unaffected) → Task 4. ✓
- Scoped cleanup: `scraper_agent`, `tools/playwright.py`, stale tier comment → Tasks 3 & 5. ✓
- Tests under `ALLOW_MODEL_REQUESTS = False` / `pytest-anyio`; tier resets via conftest → all test tasks. ✓
- Out-of-scope items (bot-blocking, httpx fast path, readability, caching) → not introduced. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows complete code. ✓

**Type consistency:** `RawScrape(markdown_raw, source_text, extraction_strategy)`, `ScrapeError`, `fetch_job_markdown`, `validate_job_url`, `html_to_markdown`, `assert_quality`, `_navigate_and_render`, `_render_html` are named identically across the module, its tests, and the CLI wiring. Agent `output_type=str` is consistent across Task 3 (definition), Task 3 tests (`custom_output_text`), and Task 4 (`scrape_result.output` used as a `str`). ✓
