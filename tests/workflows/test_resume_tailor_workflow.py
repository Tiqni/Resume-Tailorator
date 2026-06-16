"""Workflow contract tests: structured original CV input, no resume_parser_agent calls."""

import pytest

from resume_tailorator.models.agents.output import (
    AuditResult,
    JobAnalysis,
    ReviewResult,
)
from resume_tailorator.workflows import ResumeTailorWorkflow


class DummyRunResult:
    def __init__(self, output):
        self.output = output


@pytest.mark.anyio
async def test_workflow_uses_provided_original_cv_without_reparsing(
    monkeypatch, sample_cv, subtests
) -> None:
    """When provided with a structured CV, the workflow runs end-to-end without errors."""

    async def run_parser(*args, **kwargs):
        return DummyRunResult(sample_cv)

    async def run_analyst(*args, **kwargs):
        return DummyRunResult(
            JobAnalysis(
                job_title="Platform Engineer",
                company_name="Acme",
                summary="Platform role",
                hard_skills=["Python"],
                soft_skills=["Communication"],
                key_responsibilities=["Build systems"],
                keywords_to_target=["Python", "Platform"],
            )
        )

    async def run_writer(*args, **kwargs):
        return DummyRunResult(sample_cv)

    async def run_reviewer(*args, **kwargs):
        return DummyRunResult(
            ReviewResult(
                quality_score=9,
                needs_improvement=False,
                specific_suggestions=[],
                strengths=["Good targeting"],
            )
        )

    async def run_auditor(*args, **kwargs):
        return DummyRunResult(
            AuditResult(
                passed=True,
                hallucination_score=0,
                ai_cliche_score=0,
                issues=[],
                feedback_summary="Looks good",
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

    result = await ResumeTailorWorkflow().run(sample_cv, "files/job_posting.md")

    with subtests.test("job_title"):
        assert result.job_title == "Platform Engineer"

    with subtests.test("company_name"):
        assert result.company_name == "Acme"

    with subtests.test("passed"):
        assert result.passed is True


@pytest.mark.anyio
async def test_analyst_failure_after_retries_exits(monkeypatch, sample_cv) -> None:
    """Analyst failure after all retries exits with a user-facing message."""

    async def run_parser(*args, **kwargs):
        return DummyRunResult(sample_cv)

    async def always_fail(*args, **kwargs):
        raise ValueError("simulated agent unavailable")

    monkeypatch.setattr(
        "resume_tailorator.workflows.agents.resume_parser_agent.run", run_parser
    )
    monkeypatch.setattr(
        "resume_tailorator.workflows.agents.analyst_agent.run", always_fail
    )

    with pytest.raises(SystemExit) as excinfo:
        await ResumeTailorWorkflow().run(sample_cv, "files/job_posting.md")

    # The exit carries a user-facing message that surfaces the underlying error.
    assert "simulated agent unavailable" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Task 1: UserAbortedError + interactive param
# ---------------------------------------------------------------------------

def test_user_aborted_error_is_exception():
    from resume_tailorator.workflows import UserAbortedError
    err = UserAbortedError("test")
    assert isinstance(err, Exception)


def test_workflow_interactive_defaults_false():
    workflow = ResumeTailorWorkflow()
    assert workflow._interactive is False


def test_workflow_accepts_interactive_true():
    workflow = ResumeTailorWorkflow(interactive=True)
    assert workflow._interactive is True


# ---------------------------------------------------------------------------
# Task 2: _human_checkpoint
# ---------------------------------------------------------------------------

def test_checkpoint_non_interactive_returns_default():
    workflow = ResumeTailorWorkflow(interactive=False)
    action, feedback = workflow._human_checkpoint(
        header="Test header",
        details=["detail line"],
        choices=[("c", "Continue"), ("q", "Quit")],
        default="c",
    )
    assert action == "c"
    assert feedback == ""


def test_checkpoint_non_interactive_custom_default():
    workflow = ResumeTailorWorkflow(interactive=False)
    action, feedback = workflow._human_checkpoint(
        header="Test",
        details=[],
        choices=[("c", "Continue"), ("q", "Quit")],
        default="q",
    )
    assert action == "q"
    assert feedback == ""


def test_checkpoint_non_tty_returns_default(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    workflow = ResumeTailorWorkflow(interactive=True)
    action, feedback = workflow._human_checkpoint(
        header="Test",
        details=[],
        choices=[("c", "Continue"), ("q", "Quit")],
    )
    assert action == "c"
    assert feedback == ""


def test_checkpoint_non_tty_input_never_called(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(AssertionError("input called")))
    workflow = ResumeTailorWorkflow(interactive=True)
    action, _ = workflow._human_checkpoint(
        header="Test", details=[], choices=[("c", "Continue")]
    )
    assert action == "c"


def test_checkpoint_quit_choice(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "q")
    workflow = ResumeTailorWorkflow(interactive=True)
    action, feedback = workflow._human_checkpoint(
        header="Test",
        details=["Some detail"],
        choices=[("c", "Continue"), ("q", "Quit")],
    )
    assert action == "q"
    assert feedback == ""


def test_checkpoint_invalid_then_valid_input(monkeypatch):
    responses = iter(["x", "q"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    workflow = ResumeTailorWorkflow(interactive=True)
    action, feedback = workflow._human_checkpoint(
        header="Test",
        details=[],
        choices=[("c", "Continue"), ("q", "Quit")],
    )
    assert action == "q"
    assert feedback == ""


def test_checkpoint_empty_feedback_re_prompts(monkeypatch):
    responses = iter(["f", "", "my instructions"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    workflow = ResumeTailorWorkflow(interactive=True)
    action, feedback = workflow._human_checkpoint(
        header="Test",
        details=[],
        choices=[("c", "Continue"), ("f", "Provide feedback"), ("q", "Quit")],
    )
    assert action == "f"
    assert feedback == "my instructions"


def test_checkpoint_feedback_returned_directly(monkeypatch):
    responses = iter(["f", "emphasize Python"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    workflow = ResumeTailorWorkflow(interactive=True)
    action, feedback = workflow._human_checkpoint(
        header="Test",
        details=[],
        choices=[("c", "Continue"), ("f", "Provide feedback"), ("q", "Quit")],
    )
    assert action == "f"
    assert feedback == "emphasize Python"


# ---------------------------------------------------------------------------
# Shared helpers for interactive checkpoint integration tests
# ---------------------------------------------------------------------------

from resume_tailorator.models.agents.output import (
    FinalReport,
    CVDiff,
    GapAnalysis,
)


def _make_failing_audit():
    return AuditResult(
        passed=False,
        hallucination_score=3,
        ai_cliche_score=5,
        issues=[],
        feedback_summary="Missing key skills from job description.",
    )


def _make_passing_audit():
    return AuditResult(
        passed=True,
        hallucination_score=0,
        ai_cliche_score=1,
        issues=[],
        feedback_summary="Looks good.",
    )


def _make_weak_report_narrative():
    return FinalReport(
        job_title="Engineer",
        company_name="Acme",
        generated_at="2026-01-01T00:00:00Z",
        overall_recommendation="Weak Match",
        match_score=35,
        what_changed=CVDiff(),
        gaps=GapAnalysis(
            covered_keywords=["Python"],
            missing_keywords=["Kubernetes"],
            missing_hard_skills=["Kubernetes"],
            missing_soft_skills=[],
            keyword_coverage_percent=50.0,
        ),
        suggestions_to_strengthen=["Add Kubernetes"],
        audit_summary="Passed",
        recommendation_rationale="Low coverage",
        passed=True,
    )


def _make_strong_report_narrative():
    return FinalReport(
        job_title="Engineer",
        company_name="Acme",
        generated_at="2026-01-01T00:00:00Z",
        overall_recommendation="Strong Match",
        match_score=90,
        what_changed=CVDiff(),
        gaps=GapAnalysis(covered_keywords=["Python", "SQL"], keyword_coverage_percent=100.0),
        suggestions_to_strengthen=[],
        audit_summary="Passed",
        recommendation_rationale="Excellent coverage",
        passed=True,
    )


def _base_agent_mocks(monkeypatch, sample_cv, *, auditor_result, report_narrative=None):
    """Patch all agents. auditor_result can be a single AuditResult or a list for sequential calls."""

    async def run_analyst(*args, **kwargs):
        return DummyRunResult(
            JobAnalysis(
                job_title="Engineer",
                company_name="Acme",
                summary="Platform role",
                hard_skills=["Python", "Kubernetes"],
                soft_skills=["Communication"],
                key_responsibilities=["Build"],
                keywords_to_target=["Python", "Kubernetes"],
            )
        )

    async def run_writer(*args, **kwargs):
        return DummyRunResult(sample_cv)

    async def run_reviewer(*args, **kwargs):
        return DummyRunResult(
            ReviewResult(quality_score=9, needs_improvement=False, specific_suggestions=[], strengths=[])
        )

    if isinstance(auditor_result, list):
        call_idx = {"n": 0}

        async def run_auditor(*args, **kwargs):
            idx = min(call_idx["n"], len(auditor_result) - 1)
            call_idx["n"] += 1
            return DummyRunResult(auditor_result[idx])
    else:
        async def run_auditor(*args, **kwargs):
            return DummyRunResult(auditor_result)

    if report_narrative is not None:
        async def run_report(*args, **kwargs):
            return DummyRunResult(report_narrative)
        monkeypatch.setattr("resume_tailorator.workflows.agents.report_agent.run", run_report)

    async def run_parser(*args, **kwargs):
        return DummyRunResult(sample_cv)
    monkeypatch.setattr("resume_tailorator.workflows.agents.resume_parser_agent.run", run_parser)
    monkeypatch.setattr("resume_tailorator.workflows.agents.analyst_agent.run", run_analyst)
    monkeypatch.setattr("resume_tailorator.workflows.agents.writer_agent.run", run_writer)
    monkeypatch.setattr("resume_tailorator.workflows.agents.reviewer_agent.run", run_reviewer)
    monkeypatch.setattr("resume_tailorator.workflows.agents.auditor_agent.run", run_auditor)


# ---------------------------------------------------------------------------
# Task 4: Hook 1 — audit failure
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_non_interactive_never_prompts(monkeypatch, sample_cv):
    """Non-interactive workflow with audit failure never calls input()."""
    monkeypatch.setattr(
        "builtins.input",
        lambda _: (_ for _ in ()).throw(AssertionError("input() was called in non-interactive mode")),
    )
    _base_agent_mocks(monkeypatch, sample_cv, auditor_result=_make_failing_audit())

    result = await ResumeTailorWorkflow(interactive=False, write_attempts=1).run(
        sample_cv, job_content="job description"
    )
    assert result.passed is False


@pytest.mark.anyio
async def test_interactive_audit_failure_quit(monkeypatch, sample_cv):
    """With interactive=True and audit failure, choosing 'q' raises UserAbortedError."""
    from resume_tailorator.workflows import UserAbortedError

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "q")
    _base_agent_mocks(monkeypatch, sample_cv, auditor_result=_make_failing_audit())

    with pytest.raises(UserAbortedError):
        await ResumeTailorWorkflow(interactive=True, write_attempts=1).run(
            sample_cv, job_content="job description"
        )


@pytest.mark.anyio
async def test_interactive_audit_failure_continue(monkeypatch, sample_cv):
    """With interactive=True and audit failure, choosing 'c' completes the run (passed=False)."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "c")
    _base_agent_mocks(monkeypatch, sample_cv, auditor_result=_make_failing_audit())

    result = await ResumeTailorWorkflow(interactive=True, write_attempts=1).run(
        sample_cv, job_content="job description"
    )
    assert result.passed is False


@pytest.mark.anyio
async def test_interactive_audit_failure_feedback_then_pass(monkeypatch, sample_cv):
    """Feedback retries the cycle; second cycle passes audit."""
    writer_prompts = []

    async def run_writer_capture(*args, **kwargs):
        writer_prompts.append(args[0] if args else "")
        return DummyRunResult(sample_cv)

    _base_agent_mocks(
        monkeypatch,
        sample_cv,
        auditor_result=[_make_failing_audit(), _make_passing_audit()],
    )
    monkeypatch.setattr("resume_tailorator.workflows.agents.writer_agent.run", run_writer_capture)

    responses = iter(["f", "Emphasize Python and avoid leverage"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = await ResumeTailorWorkflow(interactive=True, write_attempts=1).run(
        sample_cv, job_content="job description"
    )

    assert result.passed is True
    assert len(writer_prompts) >= 2
    assert "Emphasize Python and avoid leverage" in writer_prompts[1]


@pytest.mark.anyio
async def test_interactive_audit_failure_feedback_still_fails_then_continue(monkeypatch, sample_cv):
    """After feedback retry still fails, only c/q offered; choosing 'c' completes normally."""
    _base_agent_mocks(
        monkeypatch,
        sample_cv,
        auditor_result=_make_failing_audit(),
    )

    responses = iter(["f", "my instructions", "c"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = await ResumeTailorWorkflow(interactive=True, write_attempts=1).run(
        sample_cv, job_content="job description"
    )
    assert result.passed is False


@pytest.mark.anyio
async def test_interactive_audit_failure_feedback_still_fails_then_quit(monkeypatch, sample_cv):
    """After feedback retry still fails, choosing 'q' at second checkpoint raises UserAbortedError."""
    from resume_tailorator.workflows import UserAbortedError

    _base_agent_mocks(
        monkeypatch,
        sample_cv,
        auditor_result=_make_failing_audit(),
    )

    responses = iter(["f", "my instructions", "q"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    with pytest.raises(UserAbortedError):
        await ResumeTailorWorkflow(interactive=True, write_attempts=1).run(
            sample_cv, job_content="job description"
        )


# ---------------------------------------------------------------------------
# Task 5: Hook 2 — weak match
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_interactive_weak_match_quit(monkeypatch, sample_cv):
    """Audit passes but Weak Match report → 'q' raises UserAbortedError."""
    from resume_tailorator.workflows import UserAbortedError

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "q")
    _base_agent_mocks(
        monkeypatch,
        sample_cv,
        auditor_result=_make_passing_audit(),
        report_narrative=_make_weak_report_narrative(),
    )

    with pytest.raises(UserAbortedError):
        await ResumeTailorWorkflow(interactive=True, write_attempts=1).run(
            sample_cv, job_content="job description"
        )


@pytest.mark.anyio
async def test_interactive_weak_match_continue(monkeypatch, sample_cv):
    """Audit passes but Weak Match report → 'c' completes run."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "c")
    _base_agent_mocks(
        monkeypatch,
        sample_cv,
        auditor_result=_make_passing_audit(),
        report_narrative=_make_weak_report_narrative(),
    )

    result = await ResumeTailorWorkflow(interactive=True, write_attempts=1).run(
        sample_cv, job_content="job description"
    )
    assert result.passed is True  # audit passed; only report is weak


@pytest.mark.anyio
async def test_interactive_weak_match_feedback_then_strong(monkeypatch, sample_cv):
    """Feedback triggers a re-run; second cycle produces Strong Match."""
    writer_prompts = []

    async def run_writer_capture(*args, **kwargs):
        writer_prompts.append(args[0] if args else "")
        return DummyRunResult(sample_cv)

    report_call = {"n": 0}

    async def run_report_alternating(*args, **kwargs):
        report_call["n"] += 1
        if report_call["n"] == 1:
            return DummyRunResult(_make_weak_report_narrative())
        return DummyRunResult(_make_strong_report_narrative())

    _base_agent_mocks(
        monkeypatch,
        sample_cv,
        auditor_result=_make_passing_audit(),
    )
    monkeypatch.setattr("resume_tailorator.workflows.agents.writer_agent.run", run_writer_capture)
    monkeypatch.setattr("resume_tailorator.workflows.agents.report_agent.run", run_report_alternating)

    responses = iter(["f", "emphasize Python"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = await ResumeTailorWorkflow(interactive=True, write_attempts=1).run(
        sample_cv, job_content="job description"
    )

    assert result.passed is True
    assert len(writer_prompts) >= 2
    assert "emphasize Python" in writer_prompts[1]


@pytest.mark.anyio
async def test_interactive_weak_match_feedback_still_weak_then_continue(monkeypatch, sample_cv):
    """After feedback retry still Weak Match, second checkpoint offers only c/q; 'c' completes."""
    _base_agent_mocks(
        monkeypatch,
        sample_cv,
        auditor_result=_make_passing_audit(),
        report_narrative=_make_weak_report_narrative(),
    )

    responses = iter(["f", "my instructions", "c"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = await ResumeTailorWorkflow(interactive=True, write_attempts=1).run(
        sample_cv, job_content="job description"
    )
    assert result.passed is True


@pytest.mark.anyio
async def test_checkpoint_non_tty_auto_continues(monkeypatch, sample_cv):
    """With non-TTY stdin, checkpoints auto-continue regardless of interactive flag."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr(
        "builtins.input",
        lambda _: (_ for _ in ()).throw(AssertionError("input() called on non-TTY")),
    )
    _base_agent_mocks(
        monkeypatch,
        sample_cv,
        auditor_result=_make_failing_audit(),
    )

    result = await ResumeTailorWorkflow(interactive=True, write_attempts=1).run(
        sample_cv, job_content="job description"
    )
    assert result.passed is False
