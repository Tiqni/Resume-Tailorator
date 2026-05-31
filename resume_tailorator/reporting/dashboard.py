"""LiveDashboard: a Rich Live status panel for the tailoring pipeline."""

from __future__ import annotations

import time

from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.table import Table

# Braille spinner frames; advanced by wall-clock so the panel animates even
# while an agent is mid-call and emitting no tokens (e.g. during a tool call).
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

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
    and as plain line logging otherwise.

    In a TTY the panel is alive: the running stage's elapsed time ticks, a
    spinner advances, and a rolling snippet of the active agent's latest output
    is shown in the caption — without dumping the full token firehose (that is
    what VerboseReporter / ``--verbose`` is for)."""

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
        # Only ask run_agent to stream tokens when there's a live panel to show
        # them on; in non-TTY mode streaming would be wasted work.
        self.wants_tokens: bool = self.is_live
        # Currently-running agent (for the live caption ticker).
        self._agent_label: str = ""
        self._agent_started_at: float | None = None
        self._stream_tail: str = ""
        self._live: Live | None = None

    def __rich__(self) -> Table:
        # Re-evaluated by Rich on every Live refresh, so the timer/spinner tick.
        return self.render()

    # --- context management ---
    def __enter__(self) -> "LiveDashboard":
        if self.is_live:
            # Pass self (not a static table) so each auto-refresh re-renders.
            self._live = Live(self, console=self.console, refresh_per_second=8)
            self._live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._live is not None:
            self._live.refresh()
            self._live.__exit__(*exc)
            self._live = None

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.refresh()

    def _log(self, msg: str) -> None:
        """Plain-line output used in non-TTY mode."""
        if not self.is_live:
            # markup=False: messages (e.g. note's "...[Writer]...") may contain
            # bracket characters that Rich would otherwise parse as markup.
            self.console.print(msg, markup=False)

    # --- rendering ---
    def render(self) -> Table:
        table = Table(title="📊 Pipeline", expand=False)
        table.add_column("")
        table.add_column("Stage")
        table.add_column("Status")
        table.add_column("Elapsed", justify="right")
        table.add_column("Notes")
        retry_summary = ", ".join(
            f"{agent_label}: {n} retr{'y' if n == 1 else 'ies'}"
            for agent_label, n in self.retry_counts.items()
            if n
        )
        now = time.monotonic()
        for stage in self.stages:
            status = self.status.get(stage, "pending")
            icon = _ICONS.get(status, "?")
            label = _LABELS.get(stage, stage)
            secs = self.elapsed.get(stage)
            if secs is None and status == "running" and stage in self.started_at:
                secs = now - self.started_at[stage]  # live ticking elapsed
            elapsed = f"{secs:.1f}s" if secs is not None else ""
            note = retry_summary if status == "running" else ""
            table.add_row(icon, label, status.upper(), elapsed, note)
        table.caption = self._caption(now)
        return table

    def _caption(self, now: float) -> str:
        """Live caption: spinner + active agent + ticking elapsed + latest output."""
        frame = _SPINNER[int(now * 10) % len(_SPINNER)]
        parts: list[str] = []
        if self._agent_label and self._agent_started_at is not None:
            parts.append(f"{self._agent_label} · {now - self._agent_started_at:.0f}s")
            if self._stream_tail:
                parts.append(self._stream_tail)
        elif self.activity:
            parts.append(self.activity)
        body = " · ".join(parts)
        # escape(): the stream tail is arbitrary model output and may contain
        # bracket characters that Rich would otherwise parse as markup.
        return escape(f"{frame} {body}" if body else frame)

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
        self._log(f"{icon} {_LABELS.get(stage, stage)}: {'DONE' if success else 'FAILED'}")
        self._refresh()

    def agent_start(self, label: str, prompt: str) -> None:
        self._agent_label = label
        self._agent_started_at = time.monotonic()
        self._stream_tail = ""
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
        # Keep a short, single-line rolling tail of the latest streamed text.
        # No _refresh per token — the Live auto-refresh redraws at its own rate.
        self._stream_tail = (self._stream_tail + text).replace("\n", " ")[-80:]

    def agent_done(self, label: str, elapsed: float) -> None:
        self._agent_label = ""
        self._agent_started_at = None
        self._stream_tail = ""
        self.activity = f"{label} done ({elapsed:.1f}s)"
        self._refresh()

    def note(self, msg: str) -> None:
        self.activity = msg
        self._log(msg)
        self._refresh()

    def log(self, msg: str) -> None:
        # Workflow status line. console.print is managed by Rich Live (renders
        # above the panel when live); markup=False because workflow strings are
        # plain text that may contain bracket characters.
        self.console.print(msg, markup=False)
