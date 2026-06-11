# Job Scraper Deterministic Fetch Design

## Goal

Make job-posting scraping reliable and cheaper. The current scraper times out on
JavaScript-heavy job boards (e.g. `careers.vinted.com`) because Playwright waits
for `networkidle`, which never occurs on sites with persistent analytics /
websocket / polling connections — the navigation dies at 30s even though the job
content rendered seconds earlier.

A second, deeper problem: the scraper hands the **entire raw HTML** to the LLM and
asks it to transcribe Markdown. That is slow, token-expensive, a hallucination
risk, and itself a source of flakiness. The Markdown-conversion helpers in
`tools/job_scraper_helpers.py` (`parse_html_with_markitdown`,
`parse_html_with_html2text`, `clean_job_posting_markdown`) already exist but were
never wired in.

## Approach

Split the scrape stage into a **deterministic fetch + convert** step (pure Python,
no LLM, unit-testable) and a **thin LLM cleanup** step (strips page boilerplate
from already-clean Markdown — never raw HTML). Keep Playwright as the fetch engine;
it is the right tool for JS-rendered SPAs like Vinted, where a plain HTTP GET would
return an empty shell.

Decisions locked during brainstorming:

- **Keep Playwright** as the fetch engine.
- **Full `<body>` → Markdown**; no main-content selector targeting and no
  readability dependency. The thin LLM pass removes nav/footer/boilerplate noise.
- **Thin LLM cleanup pass is retained** (not fully deterministic) — its only job is
  to isolate the job posting from clean Markdown, under the existing "never
  hallucinate / only rephrase" rules.
- **Cleanup pass runs on the `fast` model tier** (was `strong`), since it now only
  strips boilerplate from clean text.
- **Retry count = 1** on short content, to keep latency bounded.

## Flow

**Today**

```
main.py
  └─ job_scraper_agent.run(url)
        LLM calls fetch_webpage tool (Playwright, wait_until="networkidle")
        LLM reads RAW HTML  →  transcribes Markdown  →  ScrapedJobPosting
```

**New**

```
main.py
  └─ fetch_job_markdown(url)                      ← pure Python, NO LLM, unit-testable
        Playwright: goto(domcontentloaded) + best-effort settle
        → page.content()  (full body HTML)
        → parse_html_with_markitdown()  (fallback: parse_html_with_html2text())
        → clean_job_posting_markdown()
        → deterministic quality gate (detect_placeholder_content + length)
        → RawScrape{ markdown_raw, source_text, extraction_strategy }
  └─ job_scraper_agent.run(markdown_raw)          ← thin LLM (fast tier): strip nav/
        → cleaned job-posting Markdown                  footer/boilerplate, isolate posting
  └─ assemble ScrapedJobPosting(...) in Python    ← url, markdown=cleaned,
                                                       source_text, extraction_strategy
```

The agent **loses its `fetch_webpage` and `validate_extraction` tools** and becomes
input→output (clean Markdown in, cleaned Markdown out). No tool calls, no network,
no raw HTML — trivially testable and far cheaper.

## Part 1 — Deterministic fetch + convert (`fetch_job_markdown`)

A new pure-Python async function (new module `tools/job_scraper.py`) owns
everything before the LLM:

### Fetch (the Vinted fix)

```
1. page.goto(url, wait_until="domcontentloaded", timeout=30s)   # returns in ~1-3s
2. best-effort settle: try page.wait_for_load_state("networkidle", timeout=5s)
   wrapped in try/except — give JS time to render, but NEVER hard-fail on idle
3. html = page.content()                                        # full rendered DOM
4. if the visible body text is shorter than the quality-gate threshold
   (< 200 chars — SPA likely not finished rendering):
      ONE retry: page.wait_for_timeout(longer settle), re-read page.content()
5. still failing / navigation error → raise a clear, typed error
```

The key change: `networkidle` becomes a best-effort *bonus*, not a hard gate.
Navigation succeeds as soon as the DOM is parsed.

### Convert

```
markdown_raw = parse_html_with_markitdown(html)        # existing helper
if not markdown_raw:                                   # fallback
    markdown_raw = parse_html_with_html2text(html)
markdown_raw = clean_job_posting_markdown(markdown_raw)  # existing helper
```

`extraction_strategy` records which converter produced the output (`"markitdown"`
or `"html2text"`), preserving the existing `ScrapedJobPosting.extraction_strategy`
contract.

### Quality gate (pure Python, no LLM)

Run `detect_placeholder_content` + the length threshold on the converted Markdown.
On failure, raise a clear error (e.g. "extracted content looks like a placeholder /
error page") rather than producing empty output. This replaces the old
`validate_extraction` tool's role with deterministic Python.

## Part 2 — Thin LLM cleanup (`job_scraper_agent`)

The agent is reduced to a single responsibility: take clean full-body Markdown and
return the job posting with surrounding page chrome (nav, cookie banners, "related
jobs", footers) removed.

- Tools removed: `fetch_webpage`, `validate_extraction`.
- System prompt rewritten: input is **clean Markdown, not HTML**; the task is to
  isolate and lightly tidy the posting; the "never hallucinate / only extract what
  is present" rules stay.
- Model tier: `fast` (update `_AGENT_TIERS` from `"strong"`).
- `output_type` changes from `ScrapedJobPosting` to `str` (the cleaned Markdown).
  The caller assembles `ScrapedJobPosting` so the LLM never fabricates `url`,
  `source_text`, or `extraction_strategy`. `ScrapedJobPosting` itself is unchanged.

## Part 3 — Wiring in `main.py`

`_tailor_impl` (around `main.py:417-457`) changes from "run the scraper agent with a
URL" to:

```
raw = await fetch_job_markdown(job_url)          # deterministic, may raise typed error
result = await run_agent(job_scraper_agent, raw.markdown_raw, agent_label="Scraper", ...)
job_posting_markdown = result.output             # cleaned Markdown (str)
# assemble ScrapedJobPosting(url, markdown=result.output, source_text=raw.source_text,
#                            extraction_strategy=raw.extraction_strategy) if needed downstream
```

The existing `try/except` that prints the red "Failed to scrape" message + tip stays
and now also catches the typed fetch error. The empty-content guard stays.

## Part 4 — Cleanup (scoped)

Remove now-dead scraper code, nothing unrelated:

- `scraper_agent` (unused duplicate in `agents.py`).
- The commented-out `fetch_job_content` block and unused `read_job_content_file` in
  `tools/playwright.py`.
- The stale `"Scraper": "strong",  # ... wired in a later task` comment in
  `_AGENT_TIERS` (replaced by the `fast` tier entry).

## Testing

All tests stay under the existing harness (`ALLOW_MODEL_REQUESTS = False`, dummy
`OPENAI_API_KEY`; async via `pytest-anyio`). Model state reset via
`reset_agent_models()` where tiers are touched.

Unit tests for `fetch_job_markdown` (mock Playwright so `page.content()` returns
fixture HTML; `page.goto` / `wait_for_load_state` patched):

- `networkidle` timeout path still **succeeds** (best-effort settle swallowed) — the
  regression test for the Vinted bug.
- markitdown success path; html2text fallback path (markitdown returns empty).
- short-content path triggers exactly one retry, then succeeds / fails.
- placeholder / too-short content raises the typed error.
- `extraction_strategy` is set correctly per converter.

Cleanup-agent tests: agent receives Markdown (not HTML) and the `Scraper` tier
resolves to `fast`. Existing scraper tests in `tests/test_job_scraper.py` are
updated to the new split (fetch helpers tested directly; agent tested without
tools).

## Out of scope

- Bot-blocking / 403 / captcha handling for boards like LinkedIn & Indeed.
- An httpx-first fast path for static pages (Playwright handles all sites for now).
- Main-content selector targeting and readability libraries.
- Caching of scrape results.
