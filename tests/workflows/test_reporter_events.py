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
    assert "REVIEWING_CV" in starts
    assert "AUDITING_CV" in starts
    assert "GENERATING_REPORT" in starts
    assert any(e[0] == "stage_done" for e in rec.events)
