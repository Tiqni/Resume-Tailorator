# Developer Guide — Resume Tailorator

## Quickstart for Contributors

```bash
# Clone and install
git clone https://github.com/EmadMokhtar/resume_tailorator
cd resume_tailorator
uv sync                  # installs all dev deps (pytest, ruff, commitizen)
export OPENAI_API_KEY=sk-…

# Run tests (no real LLM calls — conftest.py disables them)
make test
# or:
uv run pytest -v

# Run the full workflow
uv run resume-tailor tailor <JOB_URL> <RESUME_PATH>
```

## Project Layout

```
resume_tailorator/           # Main Python package
├── main.py                  # CLI entry point (Typer: tailor + re-tailor)
├── __init__.py              # Package init
├── __main__.py              # python -m resume_tailorator entry
├── workflows/               # Agent definitions and pipeline
│   ├── __init__.py          # ResumeTailorWorkflow class
│   └── agents.py            # All agents, quality gate validators, run_agent helper
├── models/                  # Pydantic data models
│   ├── agents/
│   │   ├── output.py        # All agent output types (CV, JobAnalysis, etc.)
│   │   └── deps.py          # Agent dependency types
│   └── workflow.py          # ResumeTailorResult
├── memory/                  # SQLite resume memory
│   ├── models.py            # Domain models (ResolvedOriginalResume, etc.)
│   ├── parser.py            # PydanticAIResumeParser (adapter pattern)
│   ├── repository.py        # Abstract ResumeMemoryRepository interface
│   ├── sqlite_repository.py # SQLite implementation
│   └── service.py           # ResumeMemoryService (orchestration)
├── tools/                   # Agent tools + helpers
│   ├── playwright.py        # read_job_content_file (agent tool)
│   └── job_scraper_helpers.py  # HTML parsers, placeholder detection, cleanup
└── utils/                   # Utility functions (no LLM calls)
    ├── cv_diff.py           # Pure-Python CVDiff + GapAnalysis
    ├── markdown_writer.py   # generate_resume, generate_report_markdown
    ├── resume_converter.py  # DOCX/PDF → Markdown (markitdown)
    ├── resume_output_converter.py
    ├── pdf_converter.py     # markdown_to_pdf
    └── validate_inputs.py   # Standalone validator (not used by Typer CLI)

tests/                       # Test suite
├── conftest.py              # Fixtures; disables real LLM calls
├── factories.py             # Test data factories
├── memory/                  # Memory layer tests
│   ├── test_models.py
│   ├── test_service.py
│   └── test_sqlite_repository.py
├── workflows/               # Workflow integration tests
│   └── test_resume_tailor_workflow.py
├── test_cli_typer.py        # CLI integration tests
├── test_cv_diff.py          # CVDiff + GapAnalysis tests
├── test_job_scraper.py      # Job scraper agent tests
├── test_job_scraper_helpers.py  # HTML parsing / placeholder tests
├── test_quality_gate.py     # Quality gate tests
├── test_quality_gate_models.py
├── test_resume_converter.py
├── test_resume_output_converter.py
├── test_parsing_determinism.py
├── test_verbose_agent.py
├── test_smoke.py            # Basic import / smoke checks
└── test_main.py

files/                       # Runtime data
└── resume_memory.sqlite3    # SQLite database (auto-created)

output/                      # Default output directory (gitignored)

docs/                        # Documentation
├── DEVELOPER.md             # This file
└── superpowers/             # Design specs and implementation plans
    ├── specs/               # Design specs
    └── plans/               # Implementation plans
```

## Development Workflow

### Virtual Environment & Dependencies

```bash
uv sync              # Install production + dev deps
uv add <pkg>         # Add a new production dependency
uv add --dev <pkg>   # Add a new dev dependency
```

### Running Tests

```bash
# Full suite
uv run pytest -v

# Specific test file
uv run pytest -v tests/test_cv_diff.py

# With coverage
uv run pytest --cov=resume_tailorator --cov-report=term-missing

# Watch mode (requires pytest-watch)
ptw
```

**Important**: Tests run with `ALLOW_MODEL_REQUESTS = False` (set in `conftest.py`), so no real LLM calls are made. All tests use a dummy `OPENAI_API_KEY`.

### Linting & Formatting

```bash
uv run ruff check .          # Lint
uv run ruff check --fix .    # Auto-fix lint issues
uv run ruff format .         # Format code
```

### Running the CLI During Development

```bash
# Direct invocation (bypasses console script)
uv run python resume_tailorator/main.py tailor <URL> <PATH>

# Or via the registered console script
uv run resume-tailor tailor <URL> <PATH>

# With verbose streaming
uv run resume-tailor tailor <URL> <PATH> --verbose

# With debug output
uv run resume-tailor tailor <URL> <PATH> --debug
```

## Architecture Overview

See **[ARCHITECTURE.md](../ARCHITECTURE.md)** for the full system architecture document.

Key concepts:
- **6-stage pipeline**: Parse → Analyze → Write → Review → Audit → Report
- **Inner loop**: Write → Review (up to 3 iterations) → Audit (up to 3 write attempts total)
- **Quality gates**: Shared `quality_gate_agent` scores each pipeline agent's output 0–10
- **Content-hash caching**: Resume parsing is cached by SHA-256 hash + parser version
- **Pure-Python diffs**: CVDiff and GapAnalysis are computed deterministically, not by LLM

## Progress Reporting

The `resume_tailorator/reporting/` package provides a lightweight, context-local progress reporting abstraction.

**Protocol and context resolution:**
- `ProgressReporter` is a `Protocol` (structural interface) defined in `reporting/base.py`.
- The active reporter is stored in a `contextvars.ContextVar`; call `get_active_reporter()` to retrieve it and `use_reporter(reporter)` (a context manager) to activate one for the current async context.
- `run_agent()` in `workflows/agents.py` emits lifecycle events (stage start/complete, token streaming) to the active reporter.

**Implementations:**
- `NullReporter` — no-op; used in tests and when no reporter is set.
- `LiveDashboard` — the default in normal runs. In a TTY it renders an updating Rich panel; in a non-TTY (CI, pipes) it falls back to plain line-by-line logging.
- `VerboseReporter` — used with `--verbose`. Streams agent thinking and output tokens directly to stdout without a live panel.

**Known TTY interleaving limitation:** the workflow contains bare `print()` calls that can interleave with the `LiveDashboard` Rich live display in an interactive terminal, garbling the visual output (correctness is unaffected). This does not occur in non-TTY mode or with `--verbose`. A future follow-up should route all workflow `print()` calls through the active reporter to eliminate the conflict.

## Speed Levers

Four independent mechanisms reduce end-to-end latency:

1. **Parallel parse∥analyze**: on a cold cache the Resume Parser and Job Analyst stages run concurrently via `asyncio.gather`.
2. **Advisory quality gate**: the quality gate is now single-pass and advisory — it scores once and only re-runs the agent when the score falls below the configurable `--gate-threshold` (default 6). The gate is skipped entirely for Parser and Analyst.
3. **Trimmed configurable loops**: the write/review retry defaults are 2 write attempts × 1 review iteration (down from 3×3). Both are adjustable via `--write-attempts` and `--review-iterations`.
4. **Per-agent model tuning**: `set_agent_models(fast=..., strong=...)` / `resolve_model(agent_name)` in `workflows/agents.py` let mechanical agents (Parser, Analyst) use a faster/cheaper model tier while heavier agents stay on the strong tier. The `--fast` CLI flag activates all four levers simultaneously.

## How to Add a New Pipeline Agent

1. **Define the output model** in `models/agents/output.py`:
   ```python
   class MyAgentOutput(BaseModel):
       field1: str
       field2: list[str]
   ```

2. **Create the agent** in `workflows/agents.py`:
   ```python
   my_agent = Agent(
       MODEL_NAME,
       model_settings=MODEL_SETTINGS,
       system_prompt="You are a...\nRules:\n1. ...",
       output_type=MyAgentOutput,
       retries=5,
   )
   ```

3. **Add quality gate validator** (optional but recommended):
   ```python
   _my_qs = _QualityState()

   @my_agent.output_validator
   async def _validate_my_agent(ctx: RunContext[None], output: MyAgentOutput) -> MyAgentOutput:
       _my_qs.last_output = output
       result = await run_agent(
           quality_gate_agent,
           f"Role: My Agent\nOutput:\n{output.model_dump_json(indent=2)}",
           usage=ctx.usage,
           usage_limits=USAGE_LIMITS,
       )
       check = result.output
       if check.score < 9:
           raise ModelRetry(
               f"Score: {check.score}/10. Improvements needed:\n"
               + "\n".join(f"- {i}" for i in check.improvements)
           )
       return output
   ```

4. **Wire into the workflow** in `workflows/__init__.py` (`ResumeTailorWorkflow`):
   - Add a new stage string to `STAGES`
   - Add `_set_stage` and `_complete_stage` calls
   - Integrate into `run()` with fallback handling:
     ```python
     except UnexpectedModelBehavior:
         if _my_qs.last_output is not None:
             print("⚠️ My Agent quality gate exhausted — using best available output")
             my_output = _my_qs.last_output
         else:
             print("⚠️ My Agent quality gate exhausted with no fallback — skipping")
             my_output = None
     ```

5. **Write tests** in `tests/`:
   - Unit tests for the output model validation
   - Integration tests for the workflow stage
   - Use `conftest.py` patterns for mocking LLM calls

## How to Add a New CLI Option

1. Add parameter to the Typer command in `main.py`:
   ```python
   @app.command()
   def tailor(
       ...,
       my_option: str = typer.Option("default", help="Description"),
   ) -> int:
   ```

2. Thread through to `_tailor_impl` or `_re_tailor_impl`.

3. Add tests in `test_cli_typer.py`.

## Releasing

Uses [commitizen](https://commitizen-tools.github.io/commitizen/) for versioning:

```bash
cz bump                 # Bump version, update CHANGELOG, create tag
git push --follow-tags  # Push release
```

The release workflow is automated via GitHub Actions (see `docs/superpowers/plans/2026-05-10-release-automation.md`).

## Key Design Principles

1. **Authenticity First**: Generated content must sound human, not AI-generated
2. **No Hallucinations**: Never add information not present in original CV
3. **ATS Optimization**: Incorporate keywords naturally while maintaining readability
4. **Quality Over Quantity**: Better to highlight relevant experience than pad with fluff
5. **Validation Pipeline**: Every output passes through auditor and reviewer checks
6. **Graceful Degradation**: On quality gate exhaustion, use last available output instead of crashing
7. **Deterministic Where Possible**: CVDiff and GapAnalysis are computed in pure Python, not by LLM
