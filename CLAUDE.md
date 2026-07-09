# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Resume Tailorator is a `pydantic-ai` multi-agent CLI that scrapes a job posting, tailors a resume to it without inventing facts, audits for hallucinations/clichés, and writes a self-review report.

## Before pushing (MANDATORY)

**Always** run the full lint + format + test gate and confirm it passes **before every `git push` or PR** — no exceptions, whether or not the user reminds you:

```bash
uv run ruff format . && uv run ruff check --fix . && uv run ruff format --check . && uv run ruff check . && uv run pytest
```

`ruff format .` and `ruff check --fix .` auto-fix what they can; the `--check`/no-`--fix` reruns then fail loudly on anything left. Do not push if any step is non-zero — CI enforces `ruff check`, `ruff format --check`, and pytest (the pytest step runs under `set -o pipefail`, so its `tee` does **not** mask a failing exit code).

## Commands

Always use `uv` — never bare `python`, `python3`, or `pip`.

```bash
uv sync                                  # install dev deps (Python 3.13+)
uv run pytest -q                         # full test suite
uv run pytest tests/workflows/test_model_tuning.py -q          # one file
uv run pytest -k "quality_gate and fallback" -q               # by name
uv run ruff check .                       # lint
uv run ruff format .                      # format
uv run resume-tailor tailor <JOB_URL> <RESUME_PATH> [--model … --fast -v -d]
uv run resume-tailor re-tailor <JOB_ID> "<RECOMMENDATIONS>"
graphify update .                         # refresh the knowledge graph after code changes (AST-only, no API cost)
```

Tests never hit a real LLM: `tests/conftest.py` sets `models.ALLOW_MODEL_REQUESTS = False` and a dummy `OPENAI_API_KEY`. Async tests use `pytest-anyio` (`@pytest.mark.anyio`). CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`, and pytest with coverage on every PR to `main`. There are no pre-commit hooks, so run `uv run ruff check . && uv run ruff format --check . && uv run pytest` yourself before pushing. (Note: CI currently pipes pytest through `tee`, which masks the exit code — a green CI check does not guarantee tests passed; read the run log.)

**Worktrees**: `AGENTS.md` asks that feature work happen in an isolated git worktree, keeping `main` pristine. Commit/push only when the user asks.

## Big-picture architecture

The flow spans several files; the order is **not** all inside the workflow:

1. **`main.py`** (Typer CLI: `tailor`, `re-tailor`) — converts the resume (DOCX/PDF→Markdown via `utils/resume_converter.py`), resolves the original resume from memory (cache), **runs the job scraper**, then calls `ResumeTailorWorkflow.run()`. Scraping happens here, *before* the pipeline — not in the workflow.
2. **`workflows/__init__.py`** (`ResumeTailorWorkflow`) — the 6-stage pipeline (Parser → Analyst → Writer → Reviewer → Auditor → Report) with the **Write→Review→Audit** retry loop. `CVDiff`/`GapAnalysis` for the report are computed in **pure Python** (`utils/cv_diff.py`), not by an LLM.
3. **`workflows/agents.py`** — every agent is a module-level `pydantic-ai` `Agent` singleton, plus all the run/model/quality-gate machinery. This is the file most changes touch.
4. **`memory/`** — `ResumeMemoryService` over a SQLite repo (`files/resume_memory.sqlite3`); stores the original resume + each tailored output, and content-hash caches parsed CVs.
5. **`models/agents/output.py`** — Pydantic v2 output types that are the contracts between stages (`CV`, `JobAnalysis`, `AuditResult`, `ReviewResult`, `FinalReport`, `ScrapedJobPosting`, `QualityCheckResult`).

### Model selection (subtle — spans `main.py` + `agents.py` + `workflows/`)
- All agents are constructed at import with a **shared default model object** built by `_build_default_model()`. It is built *without requiring a live key* (real `OPENAI_API_KEY` if present, else a placeholder) — because passing a model **string** to `Agent(...)` makes pydantic-ai build the provider's HTTP client eagerly, which previously crashed `import` for users running `--model=ollama:…` with no OpenAI key. **Keep agent construction key-free**; do not regress this.
- `--model` / `--fast` mutate **module-level globals** (`MODEL_NAME`, `FAST_MODEL`, `STRONG_MODEL`) via `set_model` / `set_agent_models` / `apply_model_override`. `run_agent(agent, …, agent_label=…)` resolves a per-agent tier model through `resolve_model(label)` (tiers in `_AGENT_TIERS`) and passes it to `agent.run(model=…)`. `resolve_model` returns `None` when unconfigured → the agent's default model is used.
- The CLI calls `apply_model_override(model)` **before** the scraper and cache-parser run, so every stage honors `--model` (those stages run before the workflow would otherwise apply it).
- Because the model state is global+mutable, tests must reset it — `conftest.py` calls `reset_agent_models()` around each test. New tests that set models must reset in a `finally`.

### Quality gate (advisory) and graceful fallback
- Gated agents have an `@output_validator` that runs `quality_gate_agent` to score output 0–10. By default it **re-runs an agent only when the score is below `--gate-threshold` (default 6)**, raising `ModelRetry` with feedback. (Older docs say "< 9"; the code is threshold-driven — trust the code / `set_quality_gate`.)
- On quality-gate exhaustion, `UnexpectedModelBehavior` is caught and the system falls back to the last good output stored in a `_QualityState` instance (`_parser_qs`, `_writer_qs`, `_auditor_qs`, …) instead of failing fatally.

### Reporting
`run_agent` emits lifecycle/token events to the active `ProgressReporter` (installed via `use_reporter`): a Rich `LiveDashboard` by default, or `VerboseReporter` with `-v`. Reporter calls are best-effort and must never abort a run (`_safe_report`).

## Conventions & gotchas

- **Never hallucinate / anti-cliché**: agents may only rephrase existing resume content. The cliché blacklist ("spearheaded", "leveraged", "synergy", "tapestry", "game-changer", …) lives in the system prompts in `agents.py` — keep it consistent if you edit prompts.
- **Retry counts vary per agent** and are set inline in `agents.py` (don't assume a single value — the older docs that claim a uniform `retries=5` are stale).
- **Ollama** requires `OLLAMA_BASE_URL` (e.g. `http://localhost:11434/v1`); pydantic-ai 1.24 has no default. Cloud models (`ollama:…:cloud`) route through the local daemon after `ollama signin`.
- `utils/validate_inputs.py` and the Makefile `run`/`make run` target are **deprecated/broken** — use `uv run resume-tailor …`.
- `cover_letter_writer_agent` and `scraper_agent` exist but are **not wired into the workflow** (`job_scraper_agent` is the one the CLI uses).
- `re-tailor` reuses the stored job posting (no re-scrape); if the original resume file is gone from disk, pass `--resume-path`.

## Deeper references

- `ARCHITECTURE.md` — full data flow, per-agent detail, design decisions.
- `AGENTS.md` — agent dev guide, CLI tables, "add a new agent" checklist.
- `.github/copilot-instructions.md` — overlapping agent conventions and data-model index.
- `README.md` — user-facing usage, all `--model` providers, output layout.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
