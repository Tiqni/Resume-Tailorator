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
