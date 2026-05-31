# Workflow Feedback & Speed — Design

**Date:** 2026-05-30
**Status:** Approved (design); pending implementation plan
**Author:** Emad Mokhtar (with Claude)

## Problem

The multi-agent resume-tailoring pipeline is slow, and in default mode the user
waits through long silent gaps with almost no feedback. Two goals, weighted
equally:

1. **Transparency** — keep the user updated with what the agents are thinking and
   doing during a run.
2. **Speed** — cut wall-clock time.

The two are linked: most of the perceived slowness comes from invisible work —
specifically the quality-gate retries that fire on every agent.

## Diagnosis (where the time goes)

The pipeline is sequential and each box is a blocking LLM round-trip:

```
Scraper → Parser → Analyst → [ Writer → Reviewer×(1-3) → Auditor ] ×(1-3 attempts) → Report
```

Two dominant costs:

1. **Quality-gate double-call.** Every generative/extractive agent (Parser,
   Analyst, Writer, Auditor, Cover) has an `output_validator` that fires a
   *second* LLM call (`quality_gate_agent`) demanding a score ≥ 9, and raises
   `ModelRetry` (agent `retries=5`) when it scores lower. One "Writer" step can
   silently become 6–10 LLM calls.
2. **Nested loops.** `write_attempts (3) × review_iterations (3)` lets the
   Writer + Reviewer run up to ~9 times, each followed by an Auditor — all
   sequential.

Feedback: token streaming only happens with `--verbose`. Default mode prints
stage headers, then goes silent during the hidden calls above.

## Decisions

- **Priority:** both goals equally — structural speedups *and* a live feedback
  layer.
- **Feedback UX:** a live status dashboard by default; `--verbose` adds the full
  token-level stream on top (dashboard + deep stream).
- **Speed levers:** all four — parallelize independent agents, conditional
  quality gate, trimmed retry loops, per-agent model tuning.
- **Architecture:** Approach A — a single `ProgressReporter` seam decouples
  workflow logic from presentation; speed levers layer on top.

## Design

### 1. The seam: `ProgressReporter`

A protocol the workflow emits lifecycle events to. The workflow stops calling
`print()` / `_print_pipeline_status()` directly and calls a reporter it was
handed.

```python
class ProgressReporter(Protocol):
    def stage_start(self, stage: str) -> None: ...
    def stage_done(self, stage: str, *, success: bool = True) -> None: ...
    def agent_start(self, label: str, prompt: str) -> None: ...
    def agent_retry(self, label: str, reason: str) -> None: ...     # quality-gate / ModelRetry
    def quality_score(self, label: str, score: int) -> None: ...    # surfaces the gate score
    def token(self, label: str, text: str, kind: str) -> None: ...  # kind: "thinking" | "output"
    def agent_done(self, label: str, elapsed: float) -> None: ...
    def note(self, msg: str) -> None: ...                           # misc one-liners
```

- `run_agent()` is refactored to emit `agent_start` / `token` / `agent_done` to
  the active reporter instead of printing to its own `Console`. Timing via
  `time.monotonic()`.
- `ResumeTailorWorkflow.run` takes a `reporter` parameter, defaulting to a no-op
  `NullReporter`, so existing tests and callers keep working unchanged.
- Reporter calls are best-effort: each is guarded so a display bug can never
  break the pipeline.

### 2. Two reporters

- **`LiveDashboard`** (default): a Rich `Live` panel updated in place — one row
  per stage with `icon · label · status · elapsed · (retry / gate count)`, plus
  a single rolling "current activity" line (latest thinking summary, truncated).
  No token firehose. Auto-degrades to plain line logging when stdout is not a TTY
  (CI / pipes).
- **`VerboseReporter`** (`--verbose`): the dashboard *plus* the full token stream
  (today's green-output / cyan-thinking behavior) in a `Live` `Layout` — status
  table on top, last-N streamed lines below. If `Live` nesting misbehaves, falls
  back to "static status + stream below"; never crashes the run.

Selected in `_run_workflow` based on the `verbose` flag.

### 3. The four speed levers

1. **Parallelize Parser ∥ Analyst.** When there is no cached CV, run
   resume-parse and job-analysis concurrently via `asyncio.gather`, each with its
   **own** `RunUsage` (merged afterward — avoids racing the shared usage object).
   On cache hit, only Analyst runs. Saves one agent's full latency on the cold
   path.
2. **Conditional quality gate.** Remove the `output_validator` from Parser &
   Analyst entirely (structured extraction, already guarded by the workflow's
   completeness checks). For Writer / Auditor / Cover, change the gate from
   "loop until score ≥ 9 (`retries=5`)" to **single-pass advisory**: score once,
   surface it on the dashboard, and re-run **only** when score < a low "broken"
   threshold (default 6), with agent `retries` dropped to 2.
3. **Trim nested loops.** Defaults `write_attempts 3 → 2`,
   `review_iterations 3 → 1` (Reviewer runs once; refine only if
   `needs_improvement`). Both configurable.
4. **Per-agent model tuning.** A model map: mechanical agents (Parser, Analyst,
   Quality-Gate) default to a faster model; generative ones (Writer, Auditor,
   Report) to the strong model — applied via pydantic-ai's per-run `model=`
   override in `run_agent`.
   - Note: today's module-level `set_model` does not re-bind already-constructed
     agents (they capture the model string at import). This lever fixes that by
     overriding the model per run.

### 4. Config surface

New CLI options on `tailor` / `re-tailor`, all defaulting to the values above so
behavior is sensible out of the box:

- `--write-attempts` (default 2)
- `--review-iterations` (default 1)
- `--quality-gate / --no-quality-gate` (default: advisory gate on)
- `--gate-threshold` (default 6)
- `--fast` — convenience flag: loops 2×1, gate advisory, fast models everywhere.

Env-var fallbacks for CI.

### 5. Error handling

- Reporter is best-effort: every call guarded; on failure, log once and degrade
  to plain prints. Non-TTY auto-degrades.
- Speed levers preserve all existing fallbacks (`UnexpectedModelBehavior` →
  last-good output, etc.).
- Parallel `gather`: if one branch raises, the other is awaited / cancelled
  cleanly and the existing per-stage retry / exit logic still applies.

### 6. Testing (TDD)

- `RecordingReporter` test double asserts the workflow emits the correct
  lifecycle event sequence — no LLM calls needed.
- Unit tests: loop-count defaults, gate-threshold decision logic, usage-merge
  after parallel gather, non-TTY degradation.
- Reporters tested against a scripted event stream (snapshot the rendered table).

## Out of scope (YAGNI)

- Web / JSON reporters (the protocol makes them easy later; not built now).
- Overlapping the Scraper with parsing across the main/workflow boundary
  (possible future win; not in this cycle).
- Caching job analysis across runs.

## Affected code

- `resume_tailorator/workflows/agents.py` — `run_agent` reporter wiring; gate
  validators made conditional; per-run model override; lower `retries`.
- `resume_tailorator/workflows/__init__.py` — emit reporter events instead of
  prints; parallelize Parser ∥ Analyst; configurable loop counts.
- `resume_tailorator/main.py` — construct the reporter, pass config flags.
- New module(s) for `ProgressReporter`, `NullReporter`, `LiveDashboard`,
  `VerboseReporter`.
- Tests under `tests/`.
