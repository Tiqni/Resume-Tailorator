# Workflow Feedback & Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the resume-tailoring pipeline a live progress dashboard (deep token stream on `--verbose`) and cut wall-clock time via four speed levers.

**Architecture:** Introduce one seam — a `ProgressReporter` protocol resolved through a `contextvars.ContextVar` — so the workflow emits lifecycle events instead of printing. Two reporters (`LiveDashboard` default, `VerboseReporter` for `--verbose`) render those events. Layer four speed levers on top: parallelize Parser ∥ Analyst, make the quality gate single-pass advisory (and drop it for Parser/Analyst), trim retry loops, and per-agent model tuning.

**Tech Stack:** Python 3.13, pydantic-ai 1.24, Rich 14, Typer, pytest (`anyio` asyncio backend). Run tests with `uv run pytest`. Real LLM calls are blocked in tests via `models.ALLOW_MODEL_REQUESTS = False` (see `tests/conftest.py`); all agent calls are monkeypatched.

**Design doc:** `docs/superpowers/specs/2026-05-30-workflow-feedback-and-speed-design.md`

---

## File Structure

**New files:**
- `resume_tailorator/reporting/__init__.py` — public exports.
- `resume_tailorator/reporting/base.py` — `ProgressReporter` protocol, `NullReporter`, the active-reporter `ContextVar` + `get_active_reporter()` / `use_reporter()`.
- `resume_tailorator/reporting/dashboard.py` — `LiveDashboard` (Rich `Live` table; non-TTY degrade).
- `resume_tailorator/reporting/verbose.py` — `VerboseReporter` (dashboard + token stream).
- `tests/reporting/__init__.py`, `tests/reporting/test_base.py`, `tests/reporting/test_dashboard.py`, `tests/reporting/test_verbose.py`
- `tests/workflows/test_reporter_events.py`, `tests/workflows/test_parallel_parse_analyze.py`

**Modified files:**
- `resume_tailorator/workflows/agents.py` — `run_agent` emits reporter events + resolves per-agent model; quality-gate config + single-pass advisory validators; drop Parser/Analyst validators; lower `retries`.
- `resume_tailorator/workflows/__init__.py` — emit reporter stage events; extract `_parse_resume` / `_analyze_job`; parallelize them; configurable loop counts + gate config.
- `resume_tailorator/main.py` — new CLI flags; build reporter; pass config into the workflow.
- `tests/test_verbose_agent.py` — update for the reporter-driven `run_agent`.

---

## Task 1: `ProgressReporter` protocol + `NullReporter` + active-reporter contextvar

**Files:**
- Create: `resume_tailorator/reporting/base.py`
- Create: `resume_tailorator/reporting/__init__.py`
- Create: `tests/reporting/__init__.py`
- Test: `tests/reporting/test_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/reporting/__init__.py` (empty), then `tests/reporting/test_base.py`:

```python
"""Tests for the ProgressReporter seam."""

from resume_tailorator.reporting.base import (
    NullReporter,
    ProgressReporter,
    get_active_reporter,
    use_reporter,
)


class RecordingReporter:
    """Test double that records the event sequence."""

    wants_tokens = False

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def stage_start(self, stage: str) -> None:
        self.events.append(("stage_start", stage))

    def stage_done(self, stage: str, *, success: bool = True) -> None:
        self.events.append(("stage_done", stage, success))

    def agent_start(self, label: str, prompt: str) -> None:
        self.events.append(("agent_start", label))

    def agent_retry(self, label: str, reason: str) -> None:
        self.events.append(("agent_retry", label))

    def quality_score(self, label: str, score: int) -> None:
        self.events.append(("quality_score", label, score))

    def token(self, label: str, text: str, kind: str) -> None:
        self.events.append(("token", label, text, kind))

    def agent_done(self, label: str, elapsed: float) -> None:
        self.events.append(("agent_done", label))

    def note(self, msg: str) -> None:
        self.events.append(("note", msg))


def test_null_reporter_satisfies_protocol():
    reporter = NullReporter()
    assert isinstance(reporter, ProgressReporter)
    assert reporter.wants_tokens is False


def test_null_reporter_methods_are_noops():
    reporter = NullReporter()
    # Should not raise.
    reporter.stage_start("X")
    reporter.stage_done("X", success=True)
    reporter.agent_start("A", "prompt")
    reporter.agent_retry("A", "why")
    reporter.quality_score("A", 7)
    reporter.token("A", "hi", "output")
    reporter.agent_done("A", 1.0)
    reporter.note("note")


def test_default_active_reporter_is_null():
    assert isinstance(get_active_reporter(), NullReporter)


def test_use_reporter_sets_and_restores():
    rec = RecordingReporter()
    outer = get_active_reporter()
    with use_reporter(rec):
        assert get_active_reporter() is rec
    assert get_active_reporter() is outer


def test_recording_reporter_satisfies_protocol():
    assert isinstance(RecordingReporter(), ProgressReporter)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/reporting/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_tailorator.reporting'`

- [ ] **Step 3: Write minimal implementation**

Create `resume_tailorator/reporting/base.py`:

```python
"""ProgressReporter seam: decouples workflow logic from how progress is shown."""

from __future__ import annotations

import contextlib
import contextvars
from typing import Iterator, Protocol, runtime_checkable


@runtime_checkable
class ProgressReporter(Protocol):
    """Sink for pipeline lifecycle events. All methods are best-effort."""

    #: When True, run_agent streams token-level deltas to this reporter.
    wants_tokens: bool

    def stage_start(self, stage: str) -> None: ...
    def stage_done(self, stage: str, *, success: bool = True) -> None: ...
    def agent_start(self, label: str, prompt: str) -> None: ...
    def agent_retry(self, label: str, reason: str) -> None: ...
    def quality_score(self, label: str, score: int) -> None: ...
    def token(self, label: str, text: str, kind: str) -> None: ...
    def agent_done(self, label: str, elapsed: float) -> None: ...
    def note(self, msg: str) -> None: ...


class NullReporter:
    """Does nothing. The default when no reporter is installed."""

    wants_tokens = False

    def stage_start(self, stage: str) -> None: ...
    def stage_done(self, stage: str, *, success: bool = True) -> None: ...
    def agent_start(self, label: str, prompt: str) -> None: ...
    def agent_retry(self, label: str, reason: str) -> None: ...
    def quality_score(self, label: str, score: int) -> None: ...
    def token(self, label: str, text: str, kind: str) -> None: ...
    def agent_done(self, label: str, elapsed: float) -> None: ...
    def note(self, msg: str) -> None: ...


_active_reporter: contextvars.ContextVar[ProgressReporter] = contextvars.ContextVar(
    "active_reporter", default=NullReporter()
)


def get_active_reporter() -> ProgressReporter:
    """Return the reporter installed for the current async context."""
    return _active_reporter.get()


@contextlib.contextmanager
def use_reporter(reporter: ProgressReporter) -> Iterator[ProgressReporter]:
    """Install `reporter` as active for the duration of the `with` block."""
    token = _active_reporter.set(reporter)
    try:
        yield reporter
    finally:
        _active_reporter.reset(token)
```

Create `resume_tailorator/reporting/__init__.py`:

```python
from resume_tailorator.reporting.base import (
    NullReporter,
    ProgressReporter,
    get_active_reporter,
    use_reporter,
)

__all__ = [
    "NullReporter",
    "ProgressReporter",
    "get_active_reporter",
    "use_reporter",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/reporting/test_base.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add resume_tailorator/reporting/__init__.py resume_tailorator/reporting/base.py tests/reporting/
git commit -m "feat(reporting): add ProgressReporter seam with NullReporter and contextvar"
```

---

## Task 2: Refactor `run_agent` to emit reporter events + resolve per-agent model

This replaces the direct `_console` printing in `run_agent` with reporter events, and resolves the model per agent label. Default model behavior is unchanged (fast tier == strong tier == current model until configured in Task 9).

**Files:**
- Modify: `resume_tailorator/workflows/agents.py:37-96` (the `run_agent` function) and the imports/module constants near the top.
- Test: `tests/test_verbose_agent.py` (rewrite)

- [ ] **Step 1: Write the failing test**

Replace the entire contents of `tests/test_verbose_agent.py`:

```python
"""Tests for run_agent(): emits reporter events and streams when wants_tokens."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent

from resume_tailorator.reporting.base import use_reporter
from resume_tailorator.workflows.agents import run_agent
from tests.reporting.test_base import RecordingReporter


class _AsyncIter:
    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


class TestRunAgentNonStreaming:
    @pytest.mark.anyio
    async def test_delegates_to_agent_run_when_reporter_wants_no_tokens(self):
        agent = MagicMock(spec=Agent)
        expected = MagicMock()
        agent.run = AsyncMock(return_value=expected)

        rec = RecordingReporter()  # wants_tokens = False
        with use_reporter(rec):
            result = await run_agent(agent, "prompt", agent_label="A")

        agent.run.assert_awaited_once()
        assert result is expected
        kinds = [e[0] for e in rec.events]
        assert kinds[0] == "agent_start"
        assert "agent_done" in kinds

    @pytest.mark.anyio
    async def test_passes_usage_params(self):
        agent = MagicMock(spec=Agent)
        agent.run = AsyncMock()
        with use_reporter(RecordingReporter()):
            await run_agent(agent, "test", agent_label="A", usage="u", usage_limits="ul")
        agent.run.assert_awaited_once_with("test", usage="u", usage_limits="ul")


class TestRunAgentStreaming:
    @pytest.mark.anyio
    async def test_emits_start_and_done_when_streaming(self):
        agent = MagicMock(spec=Agent)
        agent.run_stream_events = MagicMock(return_value=_AsyncIter([]))
        agent.run = AsyncMock(return_value=MagicMock())

        rec = RecordingReporter()
        rec.wants_tokens = True
        with use_reporter(rec):
            await run_agent(agent, "prompt", agent_label="Writer")

        agent.run_stream_events.assert_called_once_with(
            "prompt", usage=None, usage_limits=None
        )
        kinds = [e[0] for e in rec.events]
        assert kinds[0] == "agent_start"
        assert "agent_done" in kinds


class TestRunAgentFallback:
    @pytest.mark.anyio
    async def test_falls_back_on_stream_error(self):
        agent = MagicMock(spec=Agent)
        fallback = MagicMock()
        agent.run = AsyncMock(return_value=fallback)
        bad = MagicMock()
        bad.__aiter__ = MagicMock(side_effect=RuntimeError("boom"))
        agent.run_stream_events = MagicMock(return_value=bad)

        rec = RecordingReporter()
        rec.wants_tokens = True
        with use_reporter(rec):
            result = await run_agent(agent, "p", agent_label="Writer")

        assert result is fallback
        agent.run.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_verbose_agent.py -v`
Expected: FAIL (run_agent has no reporter behavior yet; `test_emits_start_and_done_when_streaming` and reporter-event assertions fail)

- [ ] **Step 3: Write minimal implementation**

In `resume_tailorator/workflows/agents.py`, add `import time` at the top with the other stdlib imports, and add this import after the existing imports:

```python
from resume_tailorator.reporting.base import get_active_reporter
```

Add these module-level constants just below `MODEL_NAME = "openai:gpt-5-mini"` / `_original_model = MODEL_NAME` (around line 113):

```python
# Per-agent model tiers. Defaults equal MODEL_NAME (no behavior change until
# configured via set_agent_models()). See Task 9.
FAST_MODEL = MODEL_NAME
STRONG_MODEL = MODEL_NAME
_AGENT_TIERS = {
    "Parser": "fast",
    "Analyst": "fast",
    "Quality Gate": "fast",
    "Reviewer": "fast",
    "Writer": "strong",
    "Writer (refine)": "strong",
    "Auditor": "strong",
    "Report": "strong",
    "Cover Letter Writer": "strong",
    "Scraper": "strong",
}


def set_agent_models(*, fast: str | None = None, strong: str | None = None) -> None:
    """Override the fast/strong model tiers used by run_agent."""
    global FAST_MODEL, STRONG_MODEL
    if fast is not None:
        FAST_MODEL = fast
    if strong is not None:
        STRONG_MODEL = strong


def reset_agent_models() -> None:
    """Reset both tiers to the current MODEL_NAME."""
    global FAST_MODEL, STRONG_MODEL
    FAST_MODEL = MODEL_NAME
    STRONG_MODEL = MODEL_NAME


def resolve_model(agent_label: str) -> str | None:
    """Resolve the model for an agent label, or None to use the agent default."""
    tier = _AGENT_TIERS.get(agent_label, "strong")
    return FAST_MODEL if tier == "fast" else STRONG_MODEL
```

Now replace the whole `run_agent` function (lines 37-96) with:

```python
async def run_agent(
    agent: Agent,
    prompt: str,
    *,
    verbose: bool = False,  # retained for call-site compatibility; reporter drives streaming
    agent_label: str = "",
    usage: Usage | None = None,
    usage_limits: UsageLimits | None = None,
    model: str | None = None,
) -> AgentRunResult:
    """Run an agent, emitting lifecycle/token events to the active reporter."""
    reporter = get_active_reporter()

    run_kwargs: dict = {"usage": usage, "usage_limits": usage_limits}
    resolved = model if model is not None else resolve_model(agent_label)
    if resolved is not None:
        run_kwargs["model"] = resolved

    reporter.agent_start(agent_label, prompt)
    start = time.monotonic()

    if not reporter.wants_tokens:
        result = await agent.run(prompt, **run_kwargs)
        reporter.agent_done(agent_label, time.monotonic() - start)
        return result

    try:
        result = None
        async for event in agent.run_stream_events(prompt, **run_kwargs):
            if isinstance(event, AgentRunResultEvent):
                result = event.result
            elif isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta):
                    reporter.token(agent_label, event.delta.content_delta, "output")
                elif isinstance(event.delta, ThinkingPartDelta):
                    reporter.token(agent_label, event.delta.content_delta, "thinking")

        if result is None:
            result = await agent.run(prompt, **run_kwargs)

        reporter.agent_done(agent_label, time.monotonic() - start)
        return result

    except (KeyboardInterrupt, asyncio.CancelledError):
        raise
    except (ModelRetry, UnexpectedModelBehavior):
        raise
    except Exception:
        logger.warning(
            "verbose_stream_failed_falling_back",
            extra={"agent_label": agent_label},
            exc_info=True,
        )
        reporter.note(f"Stream interrupted for [{agent_label}], falling back...")
        result = await agent.run(prompt, **run_kwargs)
        reporter.agent_done(agent_label, time.monotonic() - start)
        return result
```

Note: `model` is now a key in `run_kwargs` only when resolved is not None. Because defaults make `resolve_model` return `MODEL_NAME` (a valid model string), `run_kwargs` will include `model=MODEL_NAME`. That is harmless and equals the agents' construction model. The `test_passes_usage_params` test asserts `agent.run` is called *without* `model`; to keep that test valid, guard the default: only add `model` when it differs from the agent's own. Simplest: in `resolve_model`, return `None` when `FAST_MODEL == STRONG_MODEL == MODEL_NAME` (the unconfigured state):

```python
def resolve_model(agent_label: str) -> str | None:
    if FAST_MODEL == STRONG_MODEL == MODEL_NAME:
        return None  # unconfigured: let each agent use its own model
    tier = _AGENT_TIERS.get(agent_label, "strong")
    return FAST_MODEL if tier == "fast" else STRONG_MODEL
```

Use this version of `resolve_model` (replacing the one shown earlier in this step).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_verbose_agent.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `uv run pytest -q`
Expected: PASS (existing workflow tests still pass; they call `run_agent` indirectly via monkeypatched `agent.run`, and the default reporter is `NullReporter` so `wants_tokens` is False)

- [ ] **Step 6: Commit**

```bash
git add resume_tailorator/workflows/agents.py tests/test_verbose_agent.py
git commit -m "feat(reporting): run_agent emits reporter events and resolves per-agent model"
```

---

## Task 3: `LiveDashboard` reporter

A Rich `Live` table updated in place. Degrades to plain line logging when stdout is not a TTY. Tracks per-stage status/elapsed and retry/gate counts; keeps a single rolling "current activity" line.

**Files:**
- Create: `resume_tailorator/reporting/dashboard.py`
- Test: `tests/reporting/test_dashboard.py`

- [ ] **Step 1: Write the failing test**

Create `tests/reporting/test_dashboard.py`:

```python
"""Tests for LiveDashboard reporter."""

import io

from rich.console import Console

from resume_tailorator.reporting.base import ProgressReporter
from resume_tailorator.reporting.dashboard import LiveDashboard


def _console(force_terminal: bool) -> Console:
    return Console(file=io.StringIO(), force_terminal=force_terminal, width=80)


def test_satisfies_protocol():
    assert isinstance(LiveDashboard(console=_console(False)), ProgressReporter)


def test_wants_tokens_false():
    assert LiveDashboard(console=_console(True)).wants_tokens is False


def test_non_tty_degrades_to_line_logging():
    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=80)
    dash = LiveDashboard(console=console)
    assert dash.is_live is False  # no Rich Live when not a TTY
    with dash:
        dash.stage_start("PARSING_RESUME")
        dash.stage_done("PARSING_RESUME", success=True)
    text = out.getvalue()
    assert "PARSING_RESUME" in text or "Parse Resume" in text


def test_tracks_retry_and_score_counts():
    dash = LiveDashboard(console=_console(False))
    with dash:
        dash.stage_start("WRITING_CV")
        dash.agent_start("Writer", "prompt")
        dash.agent_retry("Writer", "score 4")
        dash.quality_score("Writer", 7)
        dash.agent_done("Writer", 1.23)
    assert dash.retry_counts.get("Writer") == 1
    assert dash.last_scores.get("Writer") == 7


def test_render_table_lists_all_stages():
    dash = LiveDashboard(console=_console(False), stages=["PARSING_RESUME", "WRITING_CV"])
    table = dash.render()  # returns a Rich renderable; should not raise
    console = _console(False)
    console.print(table)
    assert table is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/reporting/test_dashboard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_tailorator.reporting.dashboard'`

- [ ] **Step 3: Write minimal implementation**

Create `resume_tailorator/reporting/dashboard.py`:

```python
"""LiveDashboard: a Rich Live status panel for the tailoring pipeline."""

from __future__ import annotations

import time

from rich.console import Console
from rich.live import Live
from rich.table import Table

DEFAULT_STAGES = [
    "PARSING_RESUME",
    "ANALYZING_JOB",
    "WRITING_CV",
    "REVIEWING_CV",
    "AUDITING_CV",
    "GENERATING_REPORT",
]

_LABELS = {
    "PARSING_RESUME": "Parse Resume",
    "ANALYZING_JOB": "Analyze Job",
    "WRITING_CV": "Write CV",
    "REVIEWING_CV": "Review CV",
    "AUDITING_CV": "Audit CV",
    "GENERATING_REPORT": "Generate Report",
}

_ICONS = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}


class LiveDashboard:
    """Renders pipeline progress as an in-place table when stdout is a TTY,
    and as plain line logging otherwise."""

    wants_tokens = False

    def __init__(
        self,
        console: Console | None = None,
        stages: list[str] | None = None,
    ) -> None:
        self.console = console or Console()
        self.stages = stages or list(DEFAULT_STAGES)
        self.status: dict[str, str] = {s: "pending" for s in self.stages}
        self.started_at: dict[str, float] = {}
        self.elapsed: dict[str, float] = {}
        self.retry_counts: dict[str, int] = {}
        self.last_scores: dict[str, int] = {}
        self.activity: str = ""
        self.is_live: bool = bool(self.console.is_terminal)
        self._live: Live | None = None

    # --- context management ---
    def __enter__(self) -> "LiveDashboard":
        if self.is_live:
            self._live = Live(
                self.render(), console=self.console, refresh_per_second=8
            )
            self._live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._live is not None:
            self._live.update(self.render())
            self._live.__exit__(*exc)
            self._live = None

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self.render())

    def _log(self, msg: str) -> None:
        """Plain-line output used in non-TTY mode."""
        if not self.is_live:
            self.console.print(msg)

    # --- rendering ---
    def render(self) -> Table:
        table = Table(title="📊 Pipeline", expand=False)
        table.add_column("")
        table.add_column("Stage")
        table.add_column("Status")
        table.add_column("Elapsed", justify="right")
        table.add_column("Notes")
        for stage in self.stages:
            status = self.status.get(stage, "pending")
            icon = _ICONS.get(status, "?")
            label = _LABELS.get(stage, stage)
            secs = self.elapsed.get(stage)
            elapsed = f"{secs:.1f}s" if secs is not None else ""
            notes = []
            for agent_label, n in self.retry_counts.items():
                if n:
                    notes.append(f"{agent_label}: {n} retr{'y' if n == 1 else 'ies'}")
            note = ", ".join(notes) if status == "running" else ""
            table.add_row(icon, label, status.upper(), elapsed, note)
        caption = self.activity[:80]
        if caption:
            table.caption = f"… {caption}"
        return table

    # --- ProgressReporter protocol ---
    def stage_start(self, stage: str) -> None:
        if stage in self.status:
            self.status[stage] = "running"
            self.started_at[stage] = time.monotonic()
        self._log(f"🔄 {_LABELS.get(stage, stage)}: RUNNING")
        self._refresh()

    def stage_done(self, stage: str, *, success: bool = True) -> None:
        if stage in self.status:
            self.status[stage] = "done" if success else "failed"
            if stage in self.started_at:
                self.elapsed[stage] = time.monotonic() - self.started_at[stage]
        icon = "✅" if success else "❌"
        self._log(f"{icon} {_LABELS.get(stage, stage)}: DONE")
        self._refresh()

    def agent_start(self, label: str, prompt: str) -> None:
        self.activity = f"{label} working…"
        self._refresh()

    def agent_retry(self, label: str, reason: str) -> None:
        self.retry_counts[label] = self.retry_counts.get(label, 0) + 1
        self.activity = f"{label} retry: {reason}"
        self._log(f"🔁 {label} retry: {reason}")
        self._refresh()

    def quality_score(self, label: str, score: int) -> None:
        self.last_scores[label] = score
        self.activity = f"{label} quality score: {score}/10"
        self._refresh()

    def token(self, label: str, text: str, kind: str) -> None:
        # Dashboard ignores token-level deltas (wants_tokens is False).
        return

    def agent_done(self, label: str, elapsed: float) -> None:
        self.activity = f"{label} done ({elapsed:.1f}s)"
        self._refresh()

    def note(self, msg: str) -> None:
        self.activity = msg
        self._log(msg)
        self._refresh()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/reporting/test_dashboard.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Export from package**

Edit `resume_tailorator/reporting/__init__.py` to add the dashboard:

```python
from resume_tailorator.reporting.base import (
    NullReporter,
    ProgressReporter,
    get_active_reporter,
    use_reporter,
)
from resume_tailorator.reporting.dashboard import LiveDashboard

__all__ = [
    "LiveDashboard",
    "NullReporter",
    "ProgressReporter",
    "get_active_reporter",
    "use_reporter",
]
```

- [ ] **Step 6: Commit**

```bash
git add resume_tailorator/reporting/dashboard.py resume_tailorator/reporting/__init__.py tests/reporting/test_dashboard.py
git commit -m "feat(reporting): add LiveDashboard reporter with non-TTY degradation"
```

---

## Task 4: `VerboseReporter` reporter

Extends the dashboard with the token firehose. To avoid fighting Rich `Live` nesting, `VerboseReporter` does **not** run a `Live` panel; it prints a status snapshot at each stage transition and streams tokens inline (today's green-output / cyan-thinking style). `wants_tokens` is True so `run_agent` streams.

**Files:**
- Create: `resume_tailorator/reporting/verbose.py`
- Test: `tests/reporting/test_verbose.py`

- [ ] **Step 1: Write the failing test**

Create `tests/reporting/test_verbose.py`:

```python
"""Tests for VerboseReporter."""

import io

from rich.console import Console

from resume_tailorator.reporting.base import ProgressReporter
from resume_tailorator.reporting.verbose import VerboseReporter


def _console() -> tuple[Console, io.StringIO]:
    out = io.StringIO()
    return Console(file=out, force_terminal=False, width=100), out


def test_satisfies_protocol():
    console, _ = _console()
    assert isinstance(VerboseReporter(console=console), ProgressReporter)


def test_wants_tokens_true():
    console, _ = _console()
    assert VerboseReporter(console=console).wants_tokens is True


def test_streams_tokens_to_console():
    console, out = _console()
    rep = VerboseReporter(console=console)
    rep.agent_start("Writer", "the prompt text")
    rep.token("Writer", "Hello ", "output")
    rep.token("Writer", "world", "output")
    rep.agent_done("Writer", 0.5)
    text = out.getvalue()
    assert "Writer" in text
    assert "Hello world" in text


def test_prints_prompt_preview():
    console, out = _console()
    rep = VerboseReporter(console=console)
    rep.agent_start("Analyst", "X" * 500)
    text = out.getvalue()
    assert "Prompt:" in text


def test_stage_transitions_print_status():
    console, out = _console()
    rep = VerboseReporter(console=console, stages=["PARSING_RESUME"])
    rep.stage_start("PARSING_RESUME")
    rep.stage_done("PARSING_RESUME", success=True)
    text = out.getvalue()
    assert "Parse Resume" in text or "PARSING_RESUME" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/reporting/test_verbose.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_tailorator.reporting.verbose'`

- [ ] **Step 3: Write minimal implementation**

Create `resume_tailorator/reporting/verbose.py`:

```python
"""VerboseReporter: dashboard-style status snapshots plus a token firehose."""

from __future__ import annotations

from rich.console import Console

from resume_tailorator.reporting.dashboard import _LABELS, DEFAULT_STAGES


class VerboseReporter:
    """Streams full agent thinking/output token-by-token and prints a status
    line at each stage transition. Used for `--verbose`."""

    wants_tokens = True

    def __init__(
        self,
        console: Console | None = None,
        stages: list[str] | None = None,
    ) -> None:
        self.console = console or Console()
        self.stages = stages or list(DEFAULT_STAGES)

    def stage_start(self, stage: str) -> None:
        label = _LABELS.get(stage, stage)
        self.console.print(f"\n[bold]▶ {label}[/bold]")

    def stage_done(self, stage: str, *, success: bool = True) -> None:
        label = _LABELS.get(stage, stage)
        icon = "✅" if success else "❌"
        self.console.print(f"[dim]{icon} {label} done[/dim]")

    def agent_start(self, label: str, prompt: str) -> None:
        if label:
            self.console.print(f"\n[dim yellow]♨️  [{label}][/dim yellow]")
        preview = prompt[:300] + ("..." if len(prompt) > 300 else "")
        self.console.print(f"[dim italic]Prompt: {preview}[/dim italic]")

    def agent_retry(self, label: str, reason: str) -> None:
        self.console.print(f"[yellow]🔁 {label} retry: {reason}[/yellow]")

    def quality_score(self, label: str, score: int) -> None:
        self.console.print(f"[cyan]📊 {label} quality score: {score}/10[/cyan]")

    def token(self, label: str, text: str, kind: str) -> None:
        style = "dim cyan" if kind == "thinking" else "green"
        self.console.print(text, end="", style=style, markup=False)

    def agent_done(self, label: str, elapsed: float) -> None:
        self.console.print()  # newline after streamed tokens
        self.console.print(f"[dim]· {label} done ({elapsed:.1f}s)[/dim]")

    def note(self, msg: str) -> None:
        self.console.print(f"[yellow]{msg}[/yellow]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/reporting/test_verbose.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Export from package**

Edit `resume_tailorator/reporting/__init__.py` to add `VerboseReporter`:

```python
from resume_tailorator.reporting.verbose import VerboseReporter
```

and add `"VerboseReporter"` to `__all__`.

- [ ] **Step 6: Commit**

```bash
git add resume_tailorator/reporting/verbose.py resume_tailorator/reporting/__init__.py tests/reporting/test_verbose.py
git commit -m "feat(reporting): add VerboseReporter with token firehose"
```

---

## Task 5: Workflow emits reporter events

Install a reporter for the run and replace the workflow's own `print()` status output with reporter `stage_start`/`stage_done` calls. The textual `print()`s describing intermediate results stay for now (they are harmless and the dashboard runs above them in TTY mode); the key change is wrapping `run()` in `use_reporter(...)` and emitting stage events so the dashboard updates.

**Files:**
- Modify: `resume_tailorator/workflows/__init__.py` — `run()` signature + body.
- Test: `tests/workflows/test_reporter_events.py`

- [ ] **Step 1: Write the failing test**

Create `tests/workflows/test_reporter_events.py`:

```python
"""The workflow emits the expected reporter stage events."""

import pytest

from resume_tailorator.models.agents.output import (
    AuditResult,
    JobAnalysis,
    ReviewResult,
)
from resume_tailorator.workflows import ResumeTailorWorkflow
from tests.reporting.test_base import RecordingReporter


class DummyRunResult:
    def __init__(self, output):
        self.output = output


@pytest.mark.anyio
async def test_workflow_emits_stage_events(monkeypatch, sample_cv):
    async def run_analyst(*a, **k):
        return DummyRunResult(
            JobAnalysis(
                job_title="Platform Engineer",
                company_name="Acme",
                summary="role",
                hard_skills=["Python"],
                soft_skills=["Communication"],
                key_responsibilities=["Build"],
                keywords_to_target=["Python"],
            )
        )

    async def run_writer(*a, **k):
        return DummyRunResult(sample_cv)

    async def run_reviewer(*a, **k):
        return DummyRunResult(
            ReviewResult(quality_score=9, needs_improvement=False, specific_suggestions=[], strengths=["ok"])
        )

    async def run_auditor(*a, **k):
        return DummyRunResult(
            AuditResult(passed=True, hallucination_score=0, ai_cliche_score=0, issues=[], feedback_summary="ok")
        )

    async def run_report(*a, **k):
        from resume_tailorator.models.agents.output import FinalReport, CVDiff, GapAnalysis

        return DummyRunResult(
            FinalReport(
                job_title="Platform Engineer",
                company_name="Acme",
                generated_at="2026-05-30T00:00:00+00:00",
                overall_recommendation="Strong Match",
                match_score=90,
                what_changed=CVDiff(),
                gaps=GapAnalysis(),
                suggestions_to_strengthen=[],
                audit_summary="ok",
                recommendation_rationale="ok",
                passed=True,
            )
        )

    monkeypatch.setattr("resume_tailorator.workflows.agents.analyst_agent.run", run_analyst)
    monkeypatch.setattr("resume_tailorator.workflows.agents.writer_agent.run", run_writer)
    monkeypatch.setattr("resume_tailorator.workflows.agents.reviewer_agent.run", run_reviewer)
    monkeypatch.setattr("resume_tailorator.workflows.agents.auditor_agent.run", run_auditor)
    monkeypatch.setattr("resume_tailorator.workflows.agents.report_agent.run", run_report)

    rec = RecordingReporter()
    await ResumeTailorWorkflow().run(
        "resume text",
        job_content="Some job posting",
        pre_parsed_cv=sample_cv,
        reporter=rec,
    )

    starts = [e[1] for e in rec.events if e[0] == "stage_start"]
    assert "ANALYZING_JOB" in starts
    assert "WRITING_CV" in starts
    assert "GENERATING_REPORT" in starts
    assert any(e[0] == "stage_done" for e in rec.events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/workflows/test_reporter_events.py -v`
Expected: FAIL with `TypeError: run() got an unexpected keyword argument 'reporter'`

- [ ] **Step 3: Write minimal implementation**

In `resume_tailorator/workflows/__init__.py`:

Add imports near the top (after the existing imports):

```python
from resume_tailorator.reporting.base import NullReporter, ProgressReporter, use_reporter
```

Change the `run` signature (line ~86) to accept a reporter:

```python
    async def run(
        self,
        resume_text: str,
        job_content_file_path: str | None = None,
        job_content: str | None = None,
        model: str | None = None,
        *,
        pre_parsed_cv: CV | None = None,
        debug: bool = False,
        verbose: bool = False,
        reporter: ProgressReporter | None = None,
    ) -> ResumeTailorResult:
```

Immediately after the docstring inside `run`, wrap the entire body in a reporter context. The simplest mechanical change: store the reporter on the instance and install it, then delegate to a private `_run_impl`. Add at the very start of `run` (before `# Override model if specified`):

```python
        self._reporter: ProgressReporter = reporter or NullReporter()
        with use_reporter(self._reporter):
            return await self._run_impl(
                resume_text,
                job_content_file_path=job_content_file_path,
                job_content=job_content,
                model=model,
                pre_parsed_cv=pre_parsed_cv,
                debug=debug,
                verbose=verbose,
            )
```

Then rename the existing body from `# Override model if specified` onward into a new method:

```python
    async def _run_impl(
        self,
        resume_text: str,
        job_content_file_path: str | None = None,
        job_content: str | None = None,
        model: str | None = None,
        *,
        pre_parsed_cv: CV | None = None,
        debug: bool = False,
        verbose: bool = False,
    ) -> ResumeTailorResult:
        # (existing body, starting at "if model:" ... through the final return)
```

In `_set_stage` and `_complete_stage`, add reporter emission. Replace `_set_stage`:

```python
    def _set_stage(self, stage: str) -> None:
        """Mark current stage as running, previous as done."""
        if self._current_stage and self._current_stage in self._stage_status:
            if self._stage_status[self._current_stage] == "running":
                self._stage_status[self._current_stage] = "done"
                self._reporter.stage_done(self._current_stage, success=True)
        self._current_stage = stage
        if stage in self._stage_status:
            self._stage_status[stage] = "running"
        self._reporter.stage_start(stage)
```

Replace `_complete_stage`:

```python
    def _complete_stage(self, stage: str, success: bool = True) -> None:
        """Mark a stage as completed or failed."""
        if stage in self._stage_status:
            self._stage_status[stage] = "failed" if not success else "done"
        self._reporter.stage_done(stage, success=success)
```

Initialize `self._reporter` in `__init__` so methods are safe even before `run`:

```python
    def __init__(self):
        self._current_stage: str | None = None
        self._stage_status: dict[str, str] = {stage: "pending" for stage in self.STAGES}
        self._reporter: ProgressReporter = NullReporter()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/workflows/test_reporter_events.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the workflow suite to confirm no regressions**

Run: `uv run pytest tests/workflows/ -q`
Expected: PASS (existing `test_resume_tailor_workflow.py` still passes — it calls `run()` without `reporter`, which defaults to `NullReporter`)

- [ ] **Step 6: Commit**

```bash
git add resume_tailorator/workflows/__init__.py tests/workflows/test_reporter_events.py
git commit -m "feat(workflow): emit reporter stage events via installed ProgressReporter"
```

---

## Task 6: Speed lever — parallelize Parser ∥ Analyst

Extract the resume-parse and job-analysis blocks into private async methods, then run them concurrently with `asyncio.gather` when there is no `pre_parsed_cv`. Each branch uses its own `RunUsage`, merged into `total_usage` afterward.

**Files:**
- Modify: `resume_tailorator/workflows/__init__.py` — STEP 0 + STEP 1 of `_run_impl`.
- Test: `tests/workflows/test_parallel_parse_analyze.py`

- [ ] **Step 1: Write the failing test**

Create `tests/workflows/test_parallel_parse_analyze.py`:

```python
"""Parser and Analyst run concurrently on a cold cache."""

import asyncio

import pytest

from resume_tailorator.models.agents.output import (
    AuditResult,
    JobAnalysis,
    ReviewResult,
)
from resume_tailorator.workflows import ResumeTailorWorkflow


class DummyRunResult:
    def __init__(self, output):
        self.output = output


@pytest.mark.anyio
async def test_parser_and_analyst_overlap(monkeypatch, sample_cv):
    """Both agents should be in-flight at the same time (overlap detected)."""
    in_flight = {"count": 0, "max": 0}

    async def _track(output):
        in_flight["count"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["count"])
        await asyncio.sleep(0.02)
        in_flight["count"] -= 1
        return DummyRunResult(output)

    async def run_parser(*a, **k):
        return await _track(sample_cv)

    async def run_analyst(*a, **k):
        return await _track(
            JobAnalysis(
                job_title="Platform Engineer",
                company_name="Acme",
                summary="role",
                hard_skills=["Python"],
                soft_skills=["Communication"],
                key_responsibilities=["Build"],
                keywords_to_target=["Python"],
            )
        )

    async def run_writer(*a, **k):
        return DummyRunResult(sample_cv)

    async def run_reviewer(*a, **k):
        return DummyRunResult(
            ReviewResult(quality_score=9, needs_improvement=False, specific_suggestions=[], strengths=["ok"])
        )

    async def run_auditor(*a, **k):
        return DummyRunResult(
            AuditResult(passed=True, hallucination_score=0, ai_cliche_score=0, issues=[], feedback_summary="ok")
        )

    monkeypatch.setattr("resume_tailorator.workflows.agents.resume_parser_agent.run", run_parser)
    monkeypatch.setattr("resume_tailorator.workflows.agents.analyst_agent.run", run_analyst)
    monkeypatch.setattr("resume_tailorator.workflows.agents.writer_agent.run", run_writer)
    monkeypatch.setattr("resume_tailorator.workflows.agents.reviewer_agent.run", run_reviewer)
    monkeypatch.setattr("resume_tailorator.workflows.agents.auditor_agent.run", run_auditor)
    monkeypatch.setattr("resume_tailorator.workflows.agents.report_agent.run", run_auditor)

    result = await ResumeTailorWorkflow().run(
        "resume markdown text",
        job_content="A job posting",
    )

    assert in_flight["max"] == 2  # parser and analyst overlapped
    assert result.company_name == "Acme"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/workflows/test_parallel_parse_analyze.py -v`
Expected: FAIL with `assert 1 == 2` (today they run sequentially, so max overlap is 1)

- [ ] **Step 3: Write minimal implementation**

In `resume_tailorator/workflows/__init__.py`, add `import asyncio` at the top.

Extract two private async methods (place them above `run`). They contain the existing retry/fallback logic, each operating on its own `RunUsage`:

```python
    async def _parse_resume(self, resume_text: str, debug: bool, verbose: bool) -> CV:
        """Parse the original resume into a CV. Raises SystemExit on hard failure."""
        usage = RunUsage()
        original_cv: CV | None = None
        original_cv_result = None
        for attempt in range(self.MAX_RETRIES):
            try:
                original_cv_result = await run_agent(
                    resume_parser_agent,
                    f"Parse this resume into structured format:\n\n{resume_text}",
                    verbose=verbose,
                    agent_label="Parser",
                    usage=usage,
                    usage_limits=USAGE_LIMITS,
                )
                if original_cv_result.output is None:
                    raise ValueError("Resume parsing returned None")
                if (
                    original_cv_result.output.full_name
                    and original_cv_result.output.experience
                ):
                    original_cv = original_cv_result.output
                    break
                print(f"⚠️ Attempt {attempt + 1}/{self.MAX_RETRIES}: Incomplete resume parse, retrying...")
            except UnexpectedModelBehavior:
                if _parser_qs.last_output is not None:
                    print("⚠️  Resume Parser quality gate exhausted — using best available output")
                    original_cv = _parser_qs.last_output
                    break
                raise
            except Exception as e:
                print(f"⚠️ Attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}")
                if attempt == self.MAX_RETRIES - 1:
                    raise
        if original_cv is None:
            if original_cv_result is None or original_cv_result.output is None:
                raise RuntimeError("Failed to parse original resume after retries.")
            original_cv = original_cv_result.output
        self._parse_usage = usage
        return original_cv

    async def _analyze_job(self, job_analysis_prompt: str, verbose: bool) -> "JobAnalysis":
        """Analyze the job posting. Raises on hard failure."""
        usage = RunUsage()
        job_analysis = None
        job_analysis_result = None
        for attempt in range(self.MAX_RETRIES):
            try:
                job_analysis_result = await run_agent(
                    analyst_agent,
                    job_analysis_prompt,
                    verbose=verbose,
                    agent_label="Analyst",
                    usage=usage,
                    usage_limits=USAGE_LIMITS,
                )
                if job_analysis_result.output is None:
                    raise ValueError("Job analysis data is None")
                if (
                    job_analysis_result.output.job_title
                    and job_analysis_result.output.company_name
                ):
                    job_analysis = job_analysis_result.output
                    break
                print(f"⚠️ Attempt {attempt + 1}/{self.MAX_RETRIES}: Incomplete job data, retrying...")
            except UnexpectedModelBehavior:
                if _analyst_qs.last_output is not None:
                    print("⚠️  Job Analyst quality gate exhausted — using best available output")
                    job_analysis = _analyst_qs.last_output
                    break
                raise
            except Exception as e:
                print(f"⚠️ Attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}")
                if attempt == self.MAX_RETRIES - 1:
                    raise
        if job_analysis is None:
            if job_analysis_result is None or job_analysis_result.output is None:
                raise RuntimeError("Failed to get complete job analysis after retries.")
            job_analysis = job_analysis_result.output
        self._analyze_usage = usage
        self._analyst_result = job_analysis_result  # used later for gap analysis
        return job_analysis
```

Now in `_run_impl`, replace **STEP 0** and **STEP 1** (the inline parse loop and analyze loop, original lines ~120-263) with the concurrent orchestration. Keep `total_usage = RunUsage()` where it is. Replace from `# --- STEP 0: PARSE ORIGINAL RESUME ---` down to the line `job_data_json = job_analysis.model_dump_json()` with:

```python
        # --- STEPS 0 & 1: PARSE RESUME ∥ ANALYZE JOB (concurrent on cold cache) ---
        # Build the job-analysis prompt first (cheap, synchronous).
        if job_content:
            job_analysis_prompt = (
                f"Analyze the following job posting and extract structured job data:\n\n{job_content}"
            )
        elif job_content_file_path:
            job_analysis_prompt = (
                f"Analyze the job content located at this file path {job_content_file_path} "
                f"and extract structured job data."
            )
        else:
            sys.exit("❌ No job content provided. Supply either job_content or job_content_file_path.")

        self._parse_usage = RunUsage()
        self._analyze_usage = RunUsage()
        self._analyst_result = None

        self._set_stage("PARSING_RESUME")
        original_cv: CV | None = None

        try:
            if pre_parsed_cv is not None:
                print("♻️  Using cached parsed resume (skipping AI parsing)")
                original_cv = pre_parsed_cv
                self._complete_stage("PARSING_RESUME")
                self._set_stage("ANALYZING_JOB")
                job_analysis = await self._analyze_job(job_analysis_prompt, verbose)
            else:
                self._set_stage("ANALYZING_JOB")
                original_cv, job_analysis = await asyncio.gather(
                    self._parse_resume(resume_text, debug, verbose),
                    self._analyze_job(job_analysis_prompt, verbose),
                )
                self._stage_status["PARSING_RESUME"] = "done"
        except UnexpectedModelBehavior:
            self._complete_stage("PARSING_RESUME", success=False)
            self._complete_stage("ANALYZING_JOB", success=False)
            sys.exit("❌ Parsing/analysis quality gate exhausted with no fallback available.")
        except (RuntimeError, ValueError) as e:
            self._complete_stage("ANALYZING_JOB", success=False)
            sys.exit(f"❌ {e}")

        # Merge per-branch usage into the run total.
        total_usage.incr(self._parse_usage)
        total_usage.incr(self._analyze_usage)

        self._complete_stage("ANALYZING_JOB")
        print(f"   ✅ Resume Parsed: {original_cv.full_name}")
        print(f"   📋 Found {len(original_cv.skills)} skills, {len(original_cv.experience)} work experiences\n")
        print(f"   ✅ Job Analyzed: {job_analysis.job_title} at {job_analysis.company_name}")
        print(f"   🎯 Keywords found: {job_analysis.keywords_to_target}\n")
        self._print_pipeline_status()

        original_cv_json = original_cv.model_dump_json()
        job_data_json = job_analysis.model_dump_json()
```

Then, later in `_run_impl`, the report phase references `job_analysis_result.output` for gap analysis (original lines ~552-557). Replace those references with `self._analyst_result`:

```python
            gap_analysis = compute_gap_analysis(
                original_cv,
                new_cv,
                self._analyst_result.output
                if self._analyst_result and self._analyst_result.output
                else JobAnalysis(),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/workflows/test_parallel_parse_analyze.py -v`
Expected: PASS (1 passed; `in_flight["max"] == 2`)

- [ ] **Step 5: Run the workflow suite**

Run: `uv run pytest tests/workflows/ tests/test_main.py -q`
Expected: PASS (the cached-CV path and end-to-end paths still work)

- [ ] **Step 6: Commit**

```bash
git add resume_tailorator/workflows/__init__.py tests/workflows/test_parallel_parse_analyze.py
git commit -m "perf(workflow): run Parser and Analyst concurrently on cold cache"
```

---

## Task 7: Speed lever — conditional, single-pass advisory quality gate

Drop the `output_validator` from Parser & Analyst. Make the remaining validators (Writer, Auditor, Cover) single-pass advisory: score once, emit `quality_score` to the reporter, and raise `ModelRetry` only when score is below a configurable "broken" threshold. Lower agent `retries` to 2. Add module-level config.

**Files:**
- Modify: `resume_tailorator/workflows/agents.py` — gate config; validator bodies; remove Parser/Analyst validators; lower `retries`.
- Test: `tests/test_quality_gate.py` (add cases)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_quality_gate.py` (append; keep existing tests):

```python
import pytest

from resume_tailorator.models.agents.output import CV, QualityCheckResult, WorkExperience
from resume_tailorator.reporting.base import use_reporter
from tests.reporting.test_base import RecordingReporter
import resume_tailorator.workflows.agents as agents_mod


def _cv() -> CV:
    return CV(
        full_name="Jane",
        summary="s",
        skills=["Python"],
        experience=[WorkExperience(company="A", role="Eng", dates="2020", highlights=["x"])],
        education=["BSc"],
    )


@pytest.mark.anyio
async def test_advisory_gate_passes_through_above_threshold(monkeypatch):
    """Score >= threshold: output returned, no ModelRetry."""
    agents_mod.set_quality_gate(enabled=True, threshold=6)

    async def fake_gate(*a, **k):
        class R:
            output = QualityCheckResult(score=7, reasoning="ok", improvements=[])
        return R()

    monkeypatch.setattr(agents_mod, "run_agent", fake_gate)

    rec = RecordingReporter()
    with use_reporter(rec):
        ctx = type("Ctx", (), {"usage": None})()
        out = await agents_mod._validate_writer(ctx, _cv())

    assert isinstance(out, CV)
    assert ("quality_score", "Writer", 7) in rec.events
    agents_mod.reset_quality_gate()


@pytest.mark.anyio
async def test_advisory_gate_retries_below_threshold(monkeypatch):
    """Score < threshold: raises ModelRetry once."""
    from pydantic_ai import ModelRetry

    agents_mod.set_quality_gate(enabled=True, threshold=6)

    async def fake_gate(*a, **k):
        class R:
            output = QualityCheckResult(score=3, reasoning="bad", improvements=["fix"])
        return R()

    monkeypatch.setattr(agents_mod, "run_agent", fake_gate)

    ctx = type("Ctx", (), {"usage": None})()
    with pytest.raises(ModelRetry):
        await agents_mod._validate_writer(ctx, _cv())
    agents_mod.reset_quality_gate()


@pytest.mark.anyio
async def test_disabled_gate_skips_scoring(monkeypatch):
    """Disabled gate returns output without any LLM call."""
    agents_mod.set_quality_gate(enabled=False, threshold=6)
    called = {"n": 0}

    async def fake_gate(*a, **k):
        called["n"] += 1

    monkeypatch.setattr(agents_mod, "run_agent", fake_gate)

    ctx = type("Ctx", (), {"usage": None})()
    out = await agents_mod._validate_writer(ctx, _cv())
    assert isinstance(out, CV)
    assert called["n"] == 0
    agents_mod.reset_quality_gate()


def test_parser_and_analyst_have_no_output_validator():
    """Parser and Analyst no longer run a quality gate."""
    assert not agents_mod.resume_parser_agent._output_validators
    assert not agents_mod.analyst_agent._output_validators
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quality_gate.py -v`
Expected: FAIL (`set_quality_gate` not defined; Parser/Analyst still have validators)

- [ ] **Step 3: Write minimal implementation**

In `resume_tailorator/workflows/agents.py`:

Add gate config below the model config (near `MODEL_SETTINGS`):

```python
# Quality-gate config. Advisory mode: score once, retry only when broken.
QUALITY_GATE_ENABLED = True
QUALITY_GATE_THRESHOLD = 6  # raise ModelRetry only when score < threshold


def set_quality_gate(*, enabled: bool, threshold: int) -> None:
    global QUALITY_GATE_ENABLED, QUALITY_GATE_THRESHOLD
    QUALITY_GATE_ENABLED = enabled
    QUALITY_GATE_THRESHOLD = threshold


def reset_quality_gate() -> None:
    global QUALITY_GATE_ENABLED, QUALITY_GATE_THRESHOLD
    QUALITY_GATE_ENABLED = True
    QUALITY_GATE_THRESHOLD = 6


async def _score_output(role: str, label: str, payload: str, ctx) -> int | None:
    """Run the quality gate once and emit the score. Returns the score or None
    when the gate is disabled."""
    if not QUALITY_GATE_ENABLED:
        return None
    result = await run_agent(
        quality_gate_agent,
        f"Role: {role}\nOutput:\n{payload}",
        agent_label="Quality Gate",
        usage=getattr(ctx, "usage", None),
        usage_limits=USAGE_LIMITS,
    )
    score = result.output.score
    get_active_reporter().quality_score(label, score)
    if score < QUALITY_GATE_THRESHOLD:
        get_active_reporter().agent_retry(
            label, f"quality score {score} < {QUALITY_GATE_THRESHOLD}"
        )
        raise ModelRetry(
            f"Score: {score}/10. Improvements needed:\n"
            + "\n".join(f"- {i}" for i in result.output.improvements)
        )
    return score
```

(This requires `from resume_tailorator.reporting.base import get_active_reporter`, already added in Task 2.)

**Delete** the Parser validator (`_validate_resume_parser`, original lines ~435-453) and the Analyst validator (`_validate_analyst`, original lines ~668-686) entirely.

**Replace** `_validate_writer` body with:

```python
@writer_agent.output_validator
async def _validate_writer(ctx: RunContext[None], output: CV) -> CV:
    _writer_qs.last_output = output
    await _score_output("CV Writer", "Writer", output.model_dump_json(indent=2), ctx)
    return output
```

**Replace** `_validate_auditor` body with:

```python
@auditor_agent.output_validator
async def _validate_auditor(ctx: RunContext[None], output: AuditResult) -> AuditResult:
    _auditor_qs.last_output = output
    await _score_output("Auditor", "Auditor", output.model_dump_json(indent=2), ctx)
    return output
```

**Replace** `_validate_cover_letter_writer` body with:

```python
@cover_letter_writer_agent.output_validator
async def _validate_cover_letter_writer(ctx: RunContext[None], output: str) -> str:
    _cover_qs.last_output = output
    await _score_output("Cover Letter Writer", "Cover Letter Writer", output, ctx)
    return output
```

**Lower retries** on the generative agents (the quality gate no longer loops to 9, so fewer retries are needed): change `retries=5` to `retries=2` on `resume_parser_agent`, `analyst_agent`, `writer_agent`, `auditor_agent`, and `cover_letter_writer_agent`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_quality_gate.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (the workflow's `UnexpectedModelBehavior` fallbacks still apply; Parser/Analyst no longer trigger the gate)

- [ ] **Step 6: Commit**

```bash
git add resume_tailorator/workflows/agents.py tests/test_quality_gate.py
git commit -m "perf(quality-gate): single-pass advisory gate, drop Parser/Analyst gate, lower retries"
```

---

## Task 8: Speed lever — configurable retry-loop counts

Make `write_attempts` and `review_iterations` overridable per run, defaulting to the new trimmed values (2 and 1).

**Files:**
- Modify: `resume_tailorator/workflows/__init__.py` — class defaults + `run`/`_run_impl` params.
- Test: `tests/workflows/test_loop_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/workflows/test_loop_config.py`:

```python
"""Loop counts are configurable and default to trimmed values."""

from resume_tailorator.workflows import ResumeTailorWorkflow


def test_default_loop_counts_are_trimmed():
    wf = ResumeTailorWorkflow()
    assert wf.max_write_attempts == 2
    assert wf.max_review_iterations == 1


def test_loop_counts_overridable_in_constructor():
    wf = ResumeTailorWorkflow(write_attempts=3, review_iterations=2)
    assert wf.max_write_attempts == 3
    assert wf.max_review_iterations == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/workflows/test_loop_config.py -v`
Expected: FAIL (`max_write_attempts` is 3 today; constructor takes no args)

- [ ] **Step 3: Write minimal implementation**

In `resume_tailorator/workflows/__init__.py`, change the class-level defaults:

```python
    MAX_RETRIES = 3
    max_review_iterations = 1
    max_write_attempts = 2
```

Update `__init__` to accept overrides:

```python
    def __init__(self, write_attempts: int | None = None, review_iterations: int | None = None):
        self._current_stage: str | None = None
        self._stage_status: dict[str, str] = {stage: "pending" for stage in self.STAGES}
        self._reporter: ProgressReporter = NullReporter()
        if write_attempts is not None:
            self.max_write_attempts = write_attempts
        if review_iterations is not None:
            self.max_review_iterations = review_iterations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/workflows/test_loop_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the workflow suite**

Run: `uv run pytest tests/workflows/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add resume_tailorator/workflows/__init__.py tests/workflows/test_loop_config.py
git commit -m "perf(workflow): trim default retry loops to 2x1, make configurable"
```

---

## Task 9: Speed lever — per-agent model tuning verification

The mechanism (`resolve_model`, `set_agent_models`) was added in Task 2. This task adds explicit tests proving run_agent applies the resolved model, then wires a public helper through.

**Files:**
- Modify: `resume_tailorator/workflows/agents.py` (only if a fix is needed)
- Test: `tests/workflows/test_model_tuning.py`

- [ ] **Step 1: Write the failing test**

Create `tests/workflows/test_model_tuning.py`:

```python
"""Per-agent model tuning: run_agent passes the resolved model."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent

import resume_tailorator.workflows.agents as agents_mod
from resume_tailorator.reporting.base import use_reporter
from resume_tailorator.workflows.agents import resolve_model, run_agent
from tests.reporting.test_base import RecordingReporter


def test_resolve_model_none_when_unconfigured():
    agents_mod.reset_agent_models()
    assert resolve_model("Parser") is None


def test_resolve_model_uses_tiers_when_configured():
    agents_mod.set_agent_models(fast="openai:gpt-5-nano", strong="openai:gpt-5")
    try:
        assert resolve_model("Parser") == "openai:gpt-5-nano"
        assert resolve_model("Writer") == "openai:gpt-5"
        assert resolve_model("Unknown") == "openai:gpt-5"  # default tier strong
    finally:
        agents_mod.reset_agent_models()


@pytest.mark.anyio
async def test_run_agent_passes_resolved_model():
    agents_mod.set_agent_models(fast="openai:gpt-5-nano", strong="openai:gpt-5")
    try:
        agent = MagicMock(spec=Agent)
        agent.run = AsyncMock(return_value=MagicMock())
        with use_reporter(RecordingReporter()):
            await run_agent(agent, "p", agent_label="Parser")
        _, kwargs = agent.run.call_args
        assert kwargs["model"] == "openai:gpt-5-nano"
    finally:
        agents_mod.reset_agent_models()


@pytest.mark.anyio
async def test_explicit_model_overrides_resolution():
    agent = MagicMock(spec=Agent)
    agent.run = AsyncMock(return_value=MagicMock())
    with use_reporter(RecordingReporter()):
        await run_agent(agent, "p", agent_label="Parser", model="openai:custom")
    _, kwargs = agent.run.call_args
    assert kwargs["model"] == "openai:custom"
```

- [ ] **Step 2: Run test to verify it fails / passes**

Run: `uv run pytest tests/workflows/test_model_tuning.py -v`
Expected: PASS if Task 2 was implemented correctly. If `test_resolve_model_none_when_unconfigured` fails, ensure `resolve_model` returns `None` when `FAST_MODEL == STRONG_MODEL == MODEL_NAME` (see Task 2, Step 3 final note).

- [ ] **Step 3: Commit**

```bash
git add tests/workflows/test_model_tuning.py
git commit -m "test(model-tuning): cover per-agent model resolution in run_agent"
```

---

## Task 10: CLI wiring — flags + build reporter + pass config

Wire the dashboard/verbose reporter and the speed-lever config into `tailor` and `re-tailor`.

**Files:**
- Modify: `resume_tailorator/main.py` — `_run_workflow`, `_tailor_impl`, `tailor`, `_re_tailor_impl`, `re_tailor`.
- Test: `tests/test_cli_typer.py` (add a flags test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_typer.py`:

```python
def test_tailor_accepts_fast_and_gate_flags():
    """New CLI flags are recognized (no error from Typer parsing)."""
    from typer.testing import CliRunner
    from resume_tailorator.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["tailor", "--help"])
    assert result.exit_code == 0
    assert "--fast" in result.output
    assert "--write-attempts" in result.output
    assert "--review-iterations" in result.output
    assert "--no-quality-gate" in result.output or "--quality-gate" in result.output
    assert "--gate-threshold" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_typer.py::test_tailor_accepts_fast_and_gate_flags -v`
Expected: FAIL (flags not present in `--help`)

- [ ] **Step 3: Write minimal implementation**

In `resume_tailorator/main.py`:

Add imports near the top:

```python
from resume_tailorator.reporting import LiveDashboard, VerboseReporter
from resume_tailorator.workflows.agents import set_agent_models, set_quality_gate
```

Add parameters to `_run_workflow` (after `debug: bool = False,`):

```python
    write_attempts: int = 2,
    review_iterations: int = 1,
    quality_gate: bool = True,
    gate_threshold: int = 6,
    reporter=None,
```

Inside `_run_workflow`, replace `workflow = ResumeTailorWorkflow()` with:

```python
    set_quality_gate(enabled=quality_gate, threshold=gate_threshold)
    workflow = ResumeTailorWorkflow(
        write_attempts=write_attempts,
        review_iterations=review_iterations,
    )
```

and pass the reporter into `workflow.run(...)` by adding `reporter=reporter,` to that call's kwargs (alongside the existing `verbose=verbose`).

Add parameters to `_tailor_impl` (after `debug: bool = False,`):

```python
    write_attempts: int = 2,
    review_iterations: int = 1,
    quality_gate: bool = True,
    gate_threshold: int = 6,
    fast: bool = False,
```

At the start of `_tailor_impl` (after the URL validation block), apply `--fast` and build the reporter:

```python
    if fast:
        write_attempts, review_iterations = 2, 1
        quality_gate = True
        gate_threshold = 5
        # Fast tier for mechanical agents; keep strong tier as the chosen model.
        set_agent_models(fast="openai:gpt-5-nano", strong=model or "openai:gpt-5-mini")

    reporter = VerboseReporter(console=console) if verbose else LiveDashboard(console=console)
```

The scraper currently runs via `run_agent` before the workflow. Wrap the scrape + workflow in the reporter context so the dashboard is live for both. Replace the `scrape_result = await run_agent(...)` call site and the `_run_workflow(...)` call so both are inside:

```python
    from resume_tailorator.reporting.base import use_reporter

    with reporter if hasattr(reporter, "__enter__") else _nullcontext():
        with use_reporter(reporter):
            # ... existing scrape block ...
            # ... existing _run_workflow(...) call, passing the new config ...
```

To keep this simple and avoid restructuring the large function, add a tiny helper near the top of `main.py`:

```python
import contextlib

@contextlib.contextmanager
def _nullcontext():
    yield
```

Then pass the config through to `_run_workflow`:

```python
    exit_code, resume_path_out, report_path_out, result = await _run_workflow(
        resume_content,
        job_posting_markdown,
        output_dir,
        model,
        verbose=verbose,
        output_pattern=output_pattern,
        resume_name_pattern=resume_name_pattern,
        pre_parsed_cv=pre_parsed_cv,
        debug=debug,
        write_attempts=write_attempts,
        review_iterations=review_iterations,
        quality_gate=quality_gate,
        gate_threshold=gate_threshold,
        reporter=reporter,
    )
```

Add the Typer options to the `tailor` command (after the `debug` option):

```python
    fast: bool = typer.Option(
        False, "--fast", help="Speed preset: trimmed loops + fast models for mechanical agents"
    ),
    write_attempts: int = typer.Option(2, help="Max writer attempts in the write/audit loop"),
    review_iterations: int = typer.Option(1, help="Max reviewer iterations per write attempt"),
    quality_gate: bool = typer.Option(
        True, "--quality-gate/--no-quality-gate", help="Enable the advisory quality gate"
    ),
    gate_threshold: int = typer.Option(6, help="Re-run an agent only when its quality score is below this"),
```

and forward them in the `tailor` body's `_tailor_impl(...)` call:

```python
            write_attempts=write_attempts,
            review_iterations=review_iterations,
            quality_gate=quality_gate,
            gate_threshold=gate_threshold,
            fast=fast,
```

Repeat the same option additions and forwarding for `re_tailor` / `_re_tailor_impl` (mirror the `tailor` changes: add the same five Typer options, the same five `_re_tailor_impl` params, build the reporter, apply `--fast`, wrap scrape/workflow in `use_reporter`, and pass config to `_run_workflow`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_typer.py::test_tailor_accepts_fast_and_gate_flags -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add resume_tailorator/main.py tests/test_cli_typer.py
git commit -m "feat(cli): add dashboard/verbose reporter and speed-lever flags"
```

---

## Task 11: Docs + smoke verification

Update README/docs to describe the dashboard, `--verbose`, and the speed flags, and do a final manual smoke check.

**Files:**
- Modify: `README.md` (the usage/flags section)
- Modify: `docs/DEVELOPER.md` (note the `ProgressReporter` seam and speed levers)

- [ ] **Step 1: Update README**

Add a short "Live progress & speed" subsection under the usage docs describing: a live dashboard by default, `--verbose` for full token streaming, and the `--fast`, `--write-attempts`, `--review-iterations`, `--quality-gate/--no-quality-gate`, `--gate-threshold` flags. Keep it to ~10 lines, matching the README's existing tone.

- [ ] **Step 2: Update DEVELOPER.md**

Add a paragraph describing the `resume_tailorator/reporting/` package: the `ProgressReporter` protocol resolved via a `contextvars.ContextVar`, `NullReporter`/`LiveDashboard`/`VerboseReporter`, and the four speed levers (parallel parse∥analyze, advisory quality gate, trimmed loops, per-agent model tuning).

- [ ] **Step 3: Run the full suite + lint**

Run: `uv run pytest -q`
Expected: PASS

Run: `uv run ruff check resume_tailorator/ tests/` (if ruff is configured)
Expected: no errors (fix any import-order or unused-import issues introduced)

- [ ] **Step 4: Manual smoke check (no real network)**

Run: `uv run resume-tailor tailor --help`
Expected: the new flags appear; exit code 0.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/DEVELOPER.md
git commit -m "docs: document live progress dashboard and speed flags"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** Section 1 (seam) → Task 1; Section 2 (reporters) → Tasks 3–4; Section 3 levers → Tasks 6 (parallel), 7 (gate), 8 (loops), 9 (models); Section 4 (config/CLI) → Task 10; Section 5 (error handling) → preserved in Tasks 2/6/7 fallbacks; Section 6 (testing) → `RecordingReporter` (Task 1) used throughout.
- **Type consistency:** `ProgressReporter` method names are identical across `NullReporter`, `LiveDashboard`, `VerboseReporter`, `RecordingReporter`, and all call sites (`stage_start`, `stage_done`, `agent_start`, `agent_retry`, `quality_score`, `token`, `agent_done`, `note`). `wants_tokens` is a class attribute on every reporter. `resolve_model`/`set_agent_models`/`reset_agent_models` and `set_quality_gate`/`reset_quality_gate`/`_score_output` are defined in `agents.py` and referenced consistently.
- **Known nuance:** `resolve_model` returns `None` while unconfigured so `run_agent` omits `model=` and each agent uses its construction-time model — this keeps `test_passes_usage_params` valid and preserves current behavior until `--fast`/config opts in.
- **pydantic-ai detail:** the implementer should confirm `Agent.run(..., model=...)` and `RunUsage.incr(other_run_usage)` signatures against pydantic-ai 1.24 (verified present: `RunUsage.incr(incr_usage: RunUsage | RequestUsage)`).
