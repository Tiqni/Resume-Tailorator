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
