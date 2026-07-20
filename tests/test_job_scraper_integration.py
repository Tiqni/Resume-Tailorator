"""Integration tests for job scraper within _tailor_impl().

Coverage:
- Deterministic fetch errors handled gracefully (timeout, network failure)
- Empty cleanup output detected and rejected
- Job posting content flows correctly to workflow
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer import Exit as TyperExit

from resume_tailorator.tools.job_scraper import RawScrape
from tests.factories import make_cv, make_result

pytestmark = pytest.mark.anyio

CLEANED_JOB_MD = (
    "# Senior Software Engineer\n\nRequirements: Python, distributed systems."
)


# ---------------------------------------------------------------------------
# Mock setup
# ---------------------------------------------------------------------------


def _setup_mocks(
    *,
    cleaned_markdown: str | None = None,
    fetch_error: BaseException | None = None,
    passed: bool = True,
    save_side_effect=None,
):
    """Set up mocks for _tailor_impl() dependencies.

    Scraping is now a two-step flow: a deterministic ``fetch_job_markdown``
    followed by the ``job_scraper_agent`` cleanup pass that returns a ``str``.
    ``fetch_error`` simulates the deterministic fetch failing; ``cleaned_markdown``
    sets the cleanup agent's string output (defaults to ``CLEANED_JOB_MD``).
    """
    cv = make_cv()
    workflow_result = make_result(passed=passed)

    mock_workflow = MagicMock()
    mock_workflow.run = AsyncMock(return_value=workflow_result)

    mock_generate_resume = MagicMock(return_value="/fake/output/resume.md")

    if fetch_error is not None:
        mock_fetch = AsyncMock(side_effect=fetch_error)
    else:
        mock_fetch = AsyncMock(
            return_value=RawScrape(
                markdown_raw="raw body markdown",
                source_text="<html>...</html>",
                extraction_strategy="markitdown",
            )
        )

    agent_output = CLEANED_JOB_MD if cleaned_markdown is None else cleaned_markdown
    mock_scraper_run = AsyncMock(return_value=MagicMock(output=agent_output))

    mock_svc = MagicMock()
    resolved = MagicMock()
    resolved.source = MagicMock(id="src-123")
    resolved.cv = cv
    mock_svc.aresolve_original_resume = AsyncMock(return_value=resolved)

    if save_side_effect is not None:
        mock_svc.save_tailored_resume = MagicMock(side_effect=save_side_effect)
    else:
        mock_svc.save_tailored_resume = MagicMock(return_value=MagicMock(id="job-456"))

    mocks = {
        "workflow": mock_workflow,
        "generate_resume": mock_generate_resume,
        "fetch": mock_fetch,
        "scraper_run": mock_scraper_run,
        "service": mock_svc,
    }

    patches = [
        patch("resume_tailorator.main.fetch_job_markdown", mock_fetch),
        patch("resume_tailorator.main.job_scraper_agent.run", mock_scraper_run),
        patch(
            "resume_tailorator.main.ResumeTailorWorkflow",
            return_value=mock_workflow,
        ),
        patch("resume_tailorator.main.generate_resume", mock_generate_resume),
        patch(
            "resume_tailorator.main.SQLiteResumeMemoryRepository",
            return_value=MagicMock(),
        ),
        patch(
            "resume_tailorator.main.PydanticAIResumeParser",
            return_value=MagicMock(),
        ),
        patch(
            "resume_tailorator.main.ResumeMemoryService",
            return_value=mock_svc,
        ),
    ]

    return patches, mocks


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_scraper_empty_output_rejected(tmp_path, monkeypatch) -> None:
    """Exit with error when scraper returns whitespace-only markdown."""
    resume_file = tmp_path / "resume.md"
    resume_file.write_text("# Jane Doe\nPython developer.")

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    monkeypatch.chdir(tmp_path)

    patches, mocks = _setup_mocks(cleaned_markdown="   \n")

    from resume_tailorator.main import _tailor_impl

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        with pytest.raises(TyperExit):
            await _tailor_impl(
                job_url="https://example.com/job/empty",
                resume_path=str(resume_file),
                output_dir=str(output_dir),
                model=None,
            )

    mocks["workflow"].run.assert_not_called()


@pytest.mark.anyio
async def test_scraper_timeout_handled(tmp_path, monkeypatch) -> None:
    """Exit with error on scraper timeout."""
    resume_file = tmp_path / "resume.md"
    resume_file.write_text("# Jane Doe\nPython developer.")

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    monkeypatch.chdir(tmp_path)

    patches, mocks = _setup_mocks(
        fetch_error=TimeoutError("Scraper exceeded 30s timeout")
    )

    from resume_tailorator.main import _tailor_impl

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        with pytest.raises(TyperExit):
            await _tailor_impl(
                job_url="https://slow-site.example.com/job",
                resume_path=str(resume_file),
                output_dir=str(output_dir),
                model=None,
            )

    mocks["workflow"].run.assert_not_called()


@pytest.mark.anyio
async def test_scraper_network_error_handled(tmp_path, monkeypatch) -> None:
    """Exit with error on network failure."""
    resume_file = tmp_path / "resume.md"
    resume_file.write_text("# Jane Doe\nPython developer.")

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    monkeypatch.chdir(tmp_path)

    patches, mocks = _setup_mocks(
        fetch_error=ConnectionError("Failed to connect to host")
    )

    from resume_tailorator.main import _tailor_impl

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        with pytest.raises(TyperExit):
            await _tailor_impl(
                job_url="https://nonexistent.example.com/job",
                resume_path=str(resume_file),
                output_dir=str(output_dir),
                model=None,
            )

    mocks["workflow"].run.assert_not_called()


@pytest.mark.anyio
async def test_scraper_content_flows_to_workflow(tmp_path, monkeypatch) -> None:
    """Scraped job content is correctly forwarded to the workflow."""
    resume_file = tmp_path / "resume.md"
    resume_file.write_text("# Jane Doe\nPython developer.")

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    monkeypatch.chdir(tmp_path)

    expected_keyword = "Kubernetes-Experience-Required-12345"
    patches, mocks = _setup_mocks(
        cleaned_markdown=f"# Platform Engineer\n\nMust have: {expected_keyword}."
    )

    from resume_tailorator.main import _tailor_impl

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        await _tailor_impl(
            job_url="https://example.com/job/platform-engineer",
            resume_path=str(resume_file),
            output_dir=str(output_dir),
            model=None,
        )

    mocks["workflow"].run.assert_called_once()
    call_kwargs = mocks["workflow"].run.call_args.kwargs
    assert expected_keyword in call_kwargs.get("job_content", "")
