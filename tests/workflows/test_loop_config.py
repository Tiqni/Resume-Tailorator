"""Loop counts are configurable and default to trimmed values."""

from resume_tailorator.workflows import ResumeTailorWorkflow


def test_default_loop_counts_are_trimmed():
    wf = ResumeTailorWorkflow()
    assert wf.max_write_attempts == 2
    assert wf.max_review_iterations == 1


def test_loop_counts_overridable_in_constructor():
    wf = ResumeTailorWorkflow(write_attempts=3, review_iterations=2)
    assert wf.max_write_attempts == 3
    assert wf.max_review_iterations == 2
