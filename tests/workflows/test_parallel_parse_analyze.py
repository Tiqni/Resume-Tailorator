"""Parser and Analyst run concurrently on a cold cache."""

import asyncio

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
            ReviewResult(
                quality_score=9,
                needs_improvement=False,
                specific_suggestions=[],
                strengths=["ok"],
            )
        )

    async def run_auditor(*a, **k):
        return DummyRunResult(
            AuditResult(
                passed=True,
                hallucination_score=0,
                ai_cliche_score=0,
                issues=[],
                feedback_summary="ok",
            )
        )

    monkeypatch.setattr(
        "resume_tailorator.workflows.agents.resume_parser_agent.run", run_parser
    )
    monkeypatch.setattr(
        "resume_tailorator.workflows.agents.analyst_agent.run", run_analyst
    )
    monkeypatch.setattr(
        "resume_tailorator.workflows.agents.writer_agent.run", run_writer
    )
    monkeypatch.setattr(
        "resume_tailorator.workflows.agents.reviewer_agent.run", run_reviewer
    )
    monkeypatch.setattr(
        "resume_tailorator.workflows.agents.auditor_agent.run", run_auditor
    )
    monkeypatch.setattr(
        "resume_tailorator.workflows.agents.report_agent.run", run_auditor
    )

    rec = RecordingReporter()
    result = await ResumeTailorWorkflow().run(
        "resume markdown text",
        job_content="A job posting",
        reporter=rec,
    )

    assert in_flight["max"] == 2  # parser and analyst overlapped
    assert result.company_name == "Acme"
    parse_dones = [
        e for e in rec.events if e[0] == "stage_done" and e[1] == "PARSING_RESUME"
    ]
    assert len(parse_dones) == 1  # completed exactly once, no premature/double emit
    parse_starts = [
        e for e in rec.events if e[0] == "stage_start" and e[1] == "PARSING_RESUME"
    ]
    assert len(parse_starts) == 1
