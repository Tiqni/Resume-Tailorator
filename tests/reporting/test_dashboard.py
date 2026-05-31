"""Tests for LiveDashboard reporter."""

import io
import time

from rich.console import Console

from resume_tailorator.reporting.base import ProgressReporter
from resume_tailorator.reporting.dashboard import LiveDashboard


def _console(force_terminal: bool) -> Console:
    return Console(file=io.StringIO(), force_terminal=force_terminal, width=80)


def _render_to_text(dash: LiveDashboard) -> str:
    out = io.StringIO()
    Console(file=out, width=120).print(dash.render())
    return out.getvalue()


def test_satisfies_protocol():
    assert isinstance(LiveDashboard(console=_console(False)), ProgressReporter)


def test_wants_tokens_follows_tty():
    # Stream tokens only when there's a live panel to show them on.
    assert LiveDashboard(console=_console(True)).wants_tokens is True
    assert LiveDashboard(console=_console(False)).wants_tokens is False


def test_rich_dunder_returns_renderable():
    dash = LiveDashboard(console=_console(True))
    assert dash.__rich__() is not None


def test_token_updates_rolling_activity_caption():
    dash = LiveDashboard(console=_console(True))
    dash.agent_start("Analyst", "prompt")
    dash.token("Analyst", "Reading the job ", "output")
    dash.token("Analyst", "requirements now", "output")
    assert "requirements now" in _render_to_text(dash)


def test_token_brackets_not_interpreted_as_markup_in_caption():
    dash = LiveDashboard(console=_console(True))
    dash.agent_start("Writer", "p")
    dash.token("Writer", "value [bold] here", "output")
    assert "[bold]" in _render_to_text(dash)  # literal, not parsed as markup


def test_running_stage_elapsed_is_live():
    dash = LiveDashboard(console=_console(True))
    dash.stage_start("ANALYZING_JOB")
    dash.started_at["ANALYZING_JOB"] = time.monotonic() - 3.0  # backdate
    # Running stage shows a live-computed elapsed (~3.0s), not blank.
    assert "3." in _render_to_text(dash)


def test_caption_shows_active_agent_with_ticking_elapsed():
    dash = LiveDashboard(console=_console(True))
    dash.agent_start("Scraper", "prompt")
    dash._agent_started_at = time.monotonic() - 5.0  # backdate
    rendered = _render_to_text(dash)
    assert "Scraper" in rendered
    assert "5s" in rendered or "4s" in rendered


def test_agent_done_clears_active_agent():
    dash = LiveDashboard(console=_console(True))
    dash.agent_start("Auditor", "p")
    dash.agent_done("Auditor", 1.2)
    # After done, the live agent ticker is cleared; the done note shows instead.
    rendered = _render_to_text(dash)
    assert "Auditor done" in rendered


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


def test_stage_done_failure_logs_failed():
    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=80)
    dash = LiveDashboard(console=console)
    with dash:
        dash.stage_start("AUDITING_CV")
        dash.stage_done("AUDITING_CV", success=False)
    assert "FAILED" in out.getvalue()


def test_log_writes_to_console():
    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=80)
    dash = LiveDashboard(console=console)
    dash.log("workflow-status-line")
    assert "workflow-status-line" in out.getvalue()


def test_note_with_brackets_not_interpreted_as_markup():
    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=80)
    dash = LiveDashboard(console=console)  # non-TTY -> _log path
    dash.note("Stream interrupted for [Writer], falling back...")
    assert "[Writer]" in out.getvalue()  # printed literally, not parsed as markup
