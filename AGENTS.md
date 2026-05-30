# AGENTS.md — Resume Tailorator

## Quickstart

```bash
uv sync                        # install dev deps
export OPENAI_API_KEY=sk-…
uv run resume-tailor tailor <JOB_URL> <RESUME_PATH>          # scrape + tailor
uv run resume-tailor re-tailor <JOB_ID> <RECOMMENDATIONS>    # re-run with feedback
```

## Development Workflow

**Always use isolated git worktrees.** Never commit or modify directly on `main`. Worktrees allow multiple agents to work on the same repo concurrently without interference.

```bash
# Worktrees are created automatically via EnterWorktree native tool.
# .worktrees/ and .claude/worktrees/ are gitignored — use them for isolation.
# The main branch stays pristine as the source of truth.
```

## Tool Invocation

**Always use `uv` for any Python invocation.** Never use bare `python`, `python3`, or `pip` directly.

```bash
uv run pytest ...           # tests
uv run python -m ...        # modules
uv run resume-tailor ...    # CLI
uv sync                     # install deps
uv add <pkg>                # add dependency
```

## CLI Commands

Two Typer subcommands in `resume_tailorator/main.py`:

| Command     | Signature                                                                                                                                    | Description                           |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| `tailor`    | `tailor JOB_URL RESUME_PATH [--output-dir] [--model] [--verbose] [--debug] [--output-pattern] [--resume-name-pattern]`                       | Scrape job posting, run full pipeline |
| `re-tailor` | `re-tailor JOB_ID RECOMMENDATIONS [--resume-path] [--output-dir] [--model] [--verbose] [--debug] [--output-pattern] [--resume-name-pattern]` | Re-run with prior audit feedback      |

A console script is registered: `resume-tailor` → `resume_tailorator.main:run` (see `pyproject.toml`).

## Execution & Commands

| Command       | How to run                                   | Description                                                |
| ------------- | -------------------------------------------- | ---------------------------------------------------------- |
| `tailor`      | `uv run resume-tailor tailor <URL> <PATH>`   | Scrape job posting and run the agentic workflow.           |
| `re-tailor`   | `uv run resume-tailor re-tailor <ID> <RECS>` | Re-run tailoring with prior audit recommendations.         |
| `test`        | `make test` or `uv run pytest -v`            | Run the full test suite.                                   |
| `install/dev` | `make install/dev` or `uv sync`              | Install development dependencies (incl. `pytest`, `ruff`). |
| `help`        | `make help`                                  | Show Makefile targets.                                     |

> **Note**: The Makefile `run` target is deprecated and uses broken paths. Use `uv run resume-tailor tailor` instead.

### CLI Options

| Option                  | Description                                                                         |
| ----------------------- | ----------------------------------------------------------------------------------- |
| `--output-dir`          | Output directory (default: `./output`)                                              |
| `--model`               | AI model override (default: `openai:gpt-5-mini`)                                    |
| `--verbose` / `-v`      | Stream agent thinking and prompts in real-time                                      |
| `--debug` / `-d`        | Enable debug output; saves converted resume to `resume_debug.md`                    |
| `--output-pattern`      | Template for job-specific subdirectory name (default: `{company_name}-{job_title}`) |
| `--resume-name-pattern` | Template for resume file base name (default: `{company_name}-{full_name}`)          |

Pattern variables: `{company_name}`, `{job_title}`, `{full_name}`, `{timestamp}` — all slugified.

### Environment

- **Python** `3.13+` managed by `uv`. (`.python-version` pins 3.13)
- **Required env var**: `OPENAI_API_KEY`.

### Inputs

- Both CLI commands use **positional arguments** (not interactive prompts).
- `tailor` requires a job URL (scraped via Playwright) and a resume path (`.md`, `.docx`, or `.pdf`).
- `re-tailor` requires a job ID (UUID from a prior `tailor` run) and recommendations text. It uses the stored job posting and resolved resume.
- `resume_tailorator/utils/` contains:
  - `validate_inputs.py` — Standalone input validation script (not used by the Typer CLI).
  - `resume_converter.py` — Converts DOCX/PDF to Markdown via `markitdown`.
  - `markdown_writer.py` — Generates Markdown output for resumes and reports.
  - `cv_diff.py` — Computes structural diffs and gap analysis between original and tailored CVs.
  - `pdf_converter.py` — PDF creation helpers.
  - `resume_output_converter.py` — Resume output conversion utilities.

## Architecture

Single package: `resume_tailorator/`

| Directory                      | Purpose                                                                |
| ------------------------------ | ---------------------------------------------------------------------- |
| `resume_tailorator/workflows/` | Workflow orchestration (`ResumeTailorWorkflow`) and agent definitions  |
| `resume_tailorator/models/`    | Pydantic data models (agents output types, workflow result)            |
| `resume_tailorator/memory/`    | SQLite-backed memory (parser, repository, service)                     |
| `resume_tailorator/tools/`     | Playwright scraping, HTML→Markdown parsing, placeholder detection      |
| `resume_tailorator/utils/`     | Markdown writer, resume conversion, CV diff, PDF converter, validation |
| `output/`                      | Default output directory for generated files                           |

### Multi-Agent Pipeline (6 Stages)

1. **Resume Parser** — parses Markdown/DOCX/PDF resume into structured `CV` object.
2. **Job Analyst** — extracts structured `JobAnalysis` (title, company, skills, keywords).
3. **CV Writer** — tailors CV to match job requirements using only original content.
4. **Reviewer** — scores draft quality and provides improvement suggestions (feeds refinement loop).
5. **Auditor** — checks for hallucinations and AI clichés; triggers write-retry loop on failure.
6. **Report Generator** — compiles `FinalReport` with CVDiff, gap analysis, and narrative.

**Job scraping runs BEFORE the pipeline** — the CLI uses `job_scraper_agent` (Playwright + LLM extraction) to scrape the job URL and produce markdown. The scraped content is then passed into the pipeline as `job_content`.

The **Write → Review → Audit** inner loop: after the initial write, the reviewer assesses quality and the writer refines (up to 3 review iterations). The auditor then checks the final draft. If audit fails, the entire loop retries from a fresh write (up to 3 write attempts, each with up to 3 review iterations).

### Agents Defined (in `workflows/agents.py`)

| Agent                       | Output Type          | Retries | Has Quality Gate                             |
| --------------------------- | -------------------- | ------- | -------------------------------------------- |
| `job_scraper_agent`         | `ScrapedJobPosting`  | 3       | No (has `validate_extraction` tool)          |
| `scraper_agent`             | `JobAnalysis`        | 5       | No (legacy; `job_scraper_agent` used by CLI) |
| `resume_parser_agent`       | `CV`                 | 5       | Yes                                          |
| `analyst_agent`             | `JobAnalysis`        | 5       | Yes                                          |
| `writer_agent`              | `CV`                 | 5       | Yes                                          |
| `reviewer_agent`            | `ReviewResult`       | 5       | No                                           |
| `auditor_agent`             | `AuditResult`        | 5       | Yes                                          |
| `report_agent`              | `FinalReport`        | 5       | No                                           |
| `cover_letter_writer_agent` | `str`                | 5       | Yes (defined but not wired into workflow)    |
| `quality_gate_agent`        | `QualityCheckResult` | 2       | N/A (this is the gate itself)                |

**Quality gate fallback**: Each gated agent has a `_QualityState` instance (`_parser_qs`, `_analyst_qs`, `_writer_qs`, `_auditor_qs`, `_cover_qs`). When the quality gate exhausts retries, the system uses the last available output instead of failing fatally (`UnexpectedModelBehavior` is caught and fallback applied).

### Technology Stack

- **Framework**: `pydantic-ai` (agent orchestration)
- **LLM**: OpenAI GPT (configurable via `--model`; default `openai:gpt-5-mini`)
- **Models**: Pydantic v2 for structured outputs
- **CLI**: Typer with two subcommands (`tailor`, `re-tailor`)
- **Web Scraping**: Playwright (headless Chromium), LLM-directed extraction via `job_scraper_agent`
- **HTML→Markdown**: `html2text` and `markitdown` (multi-strategy fallback in `job_scraper_helpers.py`)
- **Resume Conversion**: `markitdown` via `InputConverterRegistry` (DOCX/PDF → Markdown)
- **Memory**: SQLite (`files/resume_memory.sqlite3`) with `ResumeMemoryService`
- **Formatting**: `ruff`

## Testing

```bash
uv run pytest -v
```

- Test config lives in `pyproject.toml` (`[tool.pytest.ini_options]`).
- `tests/conftest.py` disables real LLM calls when testing (`models.ALLOW_MODEL_REQUESTS = False`).
- All tests use a dummy `OPENAI_API_KEY`; no real API calls are made.
- Test modules: `test_cli_typer.py`, `test_cv_diff.py`, `test_job_scraper_helpers.py`, `test_job_scraper.py`, `test_main.py`, `test_parsing_determinism.py`, `test_quality_gate.py`, `test_resume_converter.py`, `test_verbose_agent.py`, `memory/test_service.py`, `workflows/test_resume_tailor_workflow.py`, and more.

## Style & Linting

- Python style enforced by `ruff` (see `pyproject.toml` dev dependencies).
- No pre-commit hooks or CI workflows configured.

## Key Conventions

- **Never hallucinate**: Agents must only rephrase existing content, never invent skills or experiences.
- **Anti-cliché**: Avoid terms like "spearheaded", "synergy", "leveraged", "game-changer".
- **Quality Gates**: Core pipeline agents' output is scored 0–10 by a quality gate validator; score < 9 triggers retry. On exhaustion, fallback to last available output via `_QualityState`.
- **Resume formats**: Accepts `.md`, `.docx`, `.pdf`; DOCX/PDF are converted to Markdown before processing.
- **Memory**: Each `tailor` run stores the original resume, tailored CV, audit result, and job posting in SQLite. `re-tailor` reuses the stored job posting.
- **Output**: Tailored resumes and reports are saved to `output/<company_name>-<job_title>/` (overridable via `--output-dir`).

### Content-Hash Caching

The `ResumeMemoryService.aresolve_original_resume` method (async, used by CLI under asyncio) computes a SHA-256 content hash of the resume file. If the hash and parser version match a previously stored parsed record, the pre-parsed `CV` is reused — skipping AI parsing entirely. This avoids redundant LLM calls on re-runs with unchanged resumes.

### `re-tailor` Edge Cases

- If the original resume file no longer exists on disk but a source record is stored, `re-tailor` fails with a message to re-provide `--resume-path`.
- If no original source record exists for the job, the same fallback applies.
- The stored job posting markdown is reused directly; no re-scraping occurs.

## Other Instruction Files

- `.github/copilot-instructions.md` — Additional agent-specific guidelines and anti-hallucination rules.
- `ARCHITECTURE.md` — Detailed system architecture and data flow documentation.
