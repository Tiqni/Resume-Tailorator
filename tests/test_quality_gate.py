"""Tests for per-agent quality gate validators."""

import pytest
import resume_tailorator.workflows.agents as agents_mod
from pydantic_ai import models
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.test import TestModel
from resume_tailorator.models.agents.output import CV, QualityCheckResult, WorkExperience
from resume_tailorator.reporting.base import use_reporter
from tests.reporting.test_base import RecordingReporter

models.ALLOW_MODEL_REQUESTS = False

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SAMPLE_CV = {
    "full_name": "Jane Smith",
    "contact_info": "jane@example.com",
    "summary": "Software engineer with 5 years experience.",
    "skills": ["Python", "FastAPI"],
    "projects": [],
    "experience": [
        {
            "company": "Acme Corp",
            "role": "Engineer",
            "dates": "2020-2023",
            "highlights": ["Built REST APIs"],
        }
    ],
    "education": ["BSc Computer Science"],
    "certifications": [],
    "publications": [],
}

QC_PASS = {"score": 9, "reasoning": "Good output.", "improvements": []}
QC_FAIL = {"score": 5, "reasoning": "Needs improvement.", "improvements": ["Fix tone"]}


@pytest.fixture(autouse=True)
def reset_quality_states():
    """Reset all _QualityState singletons before and after each test."""
    from resume_tailorator.workflows.agents import (
        _analyst_qs,
        _auditor_qs,
        _cover_qs,
        _parser_qs,
        _writer_qs,
    )

    for qs in (_parser_qs, _analyst_qs, _writer_qs, _auditor_qs, _cover_qs):
        qs.last_output = None
    yield
    for qs in (_parser_qs, _analyst_qs, _writer_qs, _auditor_qs, _cover_qs):
        qs.last_output = None


# ---------------------------------------------------------------------------
# Auditor
# ---------------------------------------------------------------------------

SAMPLE_AUDIT = {
    "passed": True,
    "hallucination_score": 0,
    "ai_cliche_score": 0,
    "issues": [],
    "feedback_summary": "Sound professional and add metrics.",
}


def test_auditor_validator_passes_when_score_9():
    from resume_tailorator.workflows.agents import auditor_agent, quality_gate_agent

    with quality_gate_agent.override(model=TestModel(custom_output_args=QC_PASS)):
        with auditor_agent.override(model=TestModel(custom_output_args=SAMPLE_AUDIT)):
            result = auditor_agent.run_sync("Audit this resume.")

    assert result.output.hallucination_score == 0


def test_auditor_validator_saves_last_output_when_score_low():
    from resume_tailorator.workflows.agents import (
        _auditor_qs,
        auditor_agent,
        quality_gate_agent,
    )

    with quality_gate_agent.override(model=TestModel(custom_output_args=QC_FAIL)):
        with auditor_agent.override(model=TestModel(custom_output_args=SAMPLE_AUDIT)):
            with pytest.raises(UnexpectedModelBehavior):
                auditor_agent.run_sync("Audit this resume.")

    assert _auditor_qs.last_output is not None
    assert _auditor_qs.last_output.hallucination_score == 0


# ---------------------------------------------------------------------------
# Cover Letter Writer
# ---------------------------------------------------------------------------

SAMPLE_COVER_LETTER = "Dear Hiring Manager,\n\nI am excited to apply for the Backend Engineer position at TechCorp.\n\nSincerely,\nJane Smith"


def test_cover_letter_validator_passes_when_score_9():
    from resume_tailorator.workflows.agents import (
        cover_letter_writer_agent,
        quality_gate_agent,
    )

    with quality_gate_agent.override(model=TestModel(custom_output_args=QC_PASS)):
        with cover_letter_writer_agent.override(
            model=TestModel(custom_output_text=SAMPLE_COVER_LETTER)
        ):
            result = cover_letter_writer_agent.run_sync("Write a cover letter.")

    assert "Dear Hiring Manager" in result.output


def test_cover_letter_validator_saves_last_output_when_score_low():
    from resume_tailorator.workflows.agents import (
        _cover_qs,
        cover_letter_writer_agent,
        quality_gate_agent,
    )

    with quality_gate_agent.override(model=TestModel(custom_output_args=QC_FAIL)):
        with cover_letter_writer_agent.override(
            model=TestModel(custom_output_text=SAMPLE_COVER_LETTER)
        ):
            with pytest.raises(UnexpectedModelBehavior):
                cover_letter_writer_agent.run_sync("Write a cover letter.")

    assert _cover_qs.last_output is not None
    assert "Dear Hiring Manager" in _cover_qs.last_output


# ---------------------------------------------------------------------------
# CV Writer
# ---------------------------------------------------------------------------


def test_writer_validator_passes_when_score_9():
    from resume_tailorator.workflows.agents import writer_agent, quality_gate_agent

    with quality_gate_agent.override(model=TestModel(custom_output_args=QC_PASS)):
        with writer_agent.override(model=TestModel(custom_output_args=SAMPLE_CV)):
            result = writer_agent.run_sync("Tailor this resume.")

    assert result.output.full_name == "Jane Smith"


def test_writer_validator_saves_last_output_when_score_low():
    from resume_tailorator.workflows.agents import (
        _writer_qs,
        writer_agent,
        quality_gate_agent,
    )

    with quality_gate_agent.override(model=TestModel(custom_output_args=QC_FAIL)):
        with writer_agent.override(model=TestModel(custom_output_args=SAMPLE_CV)):
            with pytest.raises(UnexpectedModelBehavior):
                writer_agent.run_sync("Tailor this resume.")

    assert _writer_qs.last_output is not None
    assert _writer_qs.last_output.full_name == "Jane Smith"


def test_quality_state_singletons_importable():
    """Verify _QualityState singletons are importable from workflows.agents."""
    from resume_tailorator.workflows.agents import (
        _analyst_qs,
        _auditor_qs,
        _parser_qs,
        _writer_qs,
    )

    for qs in (_parser_qs, _analyst_qs, _writer_qs, _auditor_qs):
        assert hasattr(qs, "last_output")
        assert qs.last_output is None


def test_quality_state_accepts_cv_assignment():
    """Verify _QualityState can store and retrieve CV objects."""
    from resume_tailorator.workflows.agents import _parser_qs

    from resume_tailorator.models.agents.output import CV, WorkExperience

    cv = CV(
        full_name="Test User",
        contact_info="test@example.com",
        summary="Summary text.",
        skills=["Python"],
        experience=[
            WorkExperience(
                company="X Corp", role="Engineer", dates="2020", highlights=[]
            )
        ],
        education=["BSc Computer Science"],
    )
    _parser_qs.last_output = cv
    assert _parser_qs.last_output.full_name == "Test User"


# ---------------------------------------------------------------------------
# Advisory Gate (Task 7)
# ---------------------------------------------------------------------------


def _cv_for_gate() -> CV:
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
        out = await agents_mod._validate_writer(ctx, _cv_for_gate())

    assert isinstance(out, CV)
    assert ("quality_score", "Writer", 7) in rec.events
    agents_mod.reset_quality_gate()


@pytest.mark.anyio
async def test_advisory_gate_retries_below_threshold(monkeypatch):
    """Score < threshold: raises ModelRetry once and emits agent_retry."""
    from pydantic_ai import ModelRetry

    agents_mod.set_quality_gate(enabled=True, threshold=6)

    async def fake_gate(*a, **k):
        class R:
            output = QualityCheckResult(score=3, reasoning="bad", improvements=["fix"])
        return R()

    monkeypatch.setattr(agents_mod, "run_agent", fake_gate)

    rec = RecordingReporter()
    ctx = type("Ctx", (), {"usage": None})()
    with use_reporter(rec):
        with pytest.raises(ModelRetry):
            await agents_mod._validate_writer(ctx, _cv_for_gate())
    assert ("quality_score", "Writer", 3) in rec.events
    assert ("agent_retry", "Writer") in rec.events
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
    out = await agents_mod._validate_writer(ctx, _cv_for_gate())
    assert isinstance(out, CV)
    assert called["n"] == 0
    agents_mod.reset_quality_gate()


def test_parser_and_analyst_have_no_output_validator():
    """Parser and Analyst no longer run a quality gate."""
    assert not agents_mod.resume_parser_agent._output_validators
    assert not agents_mod.analyst_agent._output_validators
