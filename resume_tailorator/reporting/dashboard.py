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
        retry_summary = ", ".join(
            f"{agent_label}: {n} retr{'y' if n == 1 else 'ies'}"
            for agent_label, n in self.retry_counts.items()
            if n
        )
        for stage in self.stages:
            status = self.status.get(stage, "pending")
            icon = _ICONS.get(status, "?")
            label = _LABELS.get(stage, stage)
            secs = self.elapsed.get(stage)
            elapsed = f"{secs:.1f}s" if secs is not None else ""
            note = retry_summary if status == "running" else ""
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
        self._log(f"{icon} {_LABELS.get(stage, stage)}: {'DONE' if success else 'FAILED'}")
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
