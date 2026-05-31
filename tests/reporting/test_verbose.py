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
    assert "Parse Resume" in text


def test_stage_done_failure_prints_x():
    console, out = _console()
    rep = VerboseReporter(console=console, stages=["AUDITING_CV"])
    rep.stage_done("AUDITING_CV", success=False)
    assert "❌" in out.getvalue()


def test_prompt_with_brackets_not_interpreted_as_markup():
    console, out = _console()
    rep = VerboseReporter(console=console)
    rep.agent_start("Writer", "use [bold] and [/dim] in resume")
    text = out.getvalue()
    assert "[bold]" in text  # printed literally, not interpreted


def test_log_writes_to_console():
    console, out = _console()
    VerboseReporter(console=console).log("verbose-status-line")
    assert "verbose-status-line" in out.getvalue()
