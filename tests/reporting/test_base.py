"""Tests for the ProgressReporter seam."""

import pytest

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

    def log(self, msg: str) -> None:
        self.events.append(("log", msg))


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
    with use_reporter(rec):
        assert get_active_reporter() is rec
    assert isinstance(get_active_reporter(), NullReporter)


def test_recording_reporter_satisfies_protocol():
    assert isinstance(RecordingReporter(), ProgressReporter)


def test_use_reporter_restores_on_exception():
    rec = RecordingReporter()
    with pytest.raises(ValueError):
        with use_reporter(rec):
            raise ValueError("boom")
    assert isinstance(get_active_reporter(), NullReporter)


def test_null_reporter_log_prints(capsys):
    NullReporter().log("hello-null")
    assert "hello-null" in capsys.readouterr().out
