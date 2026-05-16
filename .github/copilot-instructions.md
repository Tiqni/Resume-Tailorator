# Resume Tailorator - GitHub Copilot Instructions

## Project Overview

Resume Tailorator is a multi-agent AI system that analyzes job postings and tailors resumes to match specific job requirements while maintaining authenticity and avoiding AI-generated clichés.

## Core Architecture

### Agent-Based Workflow

The system uses a multi-agent pipeline. Job scraping runs **before** the pipeline in the CLI:

**Pre-pipeline (CLI):** 0. **Job Scraper Agent** (`job_scraper_agent`) — Fetches job posting content via Playwright + LLM extraction

**Pipeline** (in `ResumeTailorWorkflow`):

1. **Resume Parser Agent** — Parses Markdown/DOCX/PDF resumes into structured `CV` data
2. **Job Analyst Agent** — Extracts structured job requirements from scraped markdown
3. **CV Writer Agent** — Tailors CV to match job requirements
4. **Reviewer Agent** — Scores CV quality and suggests improvements (up to 3 iterations per write)
5. **Auditor Agent** — Validates for hallucinations and AI clichés (failed audit → retry from Writer)
6. **Report Generator Agent** — Compiles self-review report with CVDiff and gap analysis

The **Write → Review → Audit inner loop**: Write → Review (up to 3 iterations) → Audit. If audit fails, the entire loop retries from Write (up to 3 write attempts).

**Bonus (not wired)**: 7. **Cover Letter Writer Agent** — Defined but not integrated into the main workflow.

### Quality Gate System

Every core pipeline agent has an `@output_validator` that calls the `quality_gate_agent` to score output 0–10. Score < 9 triggers `ModelRetry` with corrective feedback. On quality gate exhaustion (`UnexpectedModelBehavior` is caught), the system falls back to the last available output stored in a `_QualityState` instance (`_parser_qs`, `_analyst_qs`, `_writer_qs`, `_auditor_qs`, `_cover_qs`) — graceful degradation instead of fatal failure.

### Technology Stack

- **Framework**: `pydantic-ai` for agent orchestration
- **LLM**: OpenAI GPT (configurable; default `MODEL_NAME = "openai:gpt-5-mini"` at module level in `agents.py`)
- **Models**: Pydantic v2 for structured outputs
- **Tools**: Playwright for web scraping

## Coding Guidelines

### Agent Development

- All agents must use structured `output_type` from `models.agents.output`
- Retries vary by role: quality gate uses `retries=2`, scraper uses `retries=3`, pipeline agents use `retries=5`
- System prompts must be explicit about avoiding AI clichés
- Always validate that agents don't hallucinate information
- Pipeline agents use `@output_validator` decorators that call `quality_gate_agent` for scoring
- Quality gate validators store last output in `_QualityState` instances for fallback on exhaustion

### Data Models

- Use Pydantic v2 models for all structured data
- Models defined in `models/agents/output.py` and `models/workflow.py`
- Key output models: `CV`, `WorkExperience`, `JobAnalysis`, `AuditResult`, `AuditIssue`, `ReviewResult`, `CVDiff`, `ExperienceChange`, `GapAnalysis`, `FinalReport`, `QualityCheckResult`, `ScrapedJobPosting`, `CoverLetter`
- Workflow result: `ResumeTailorResult` (in `models/workflow.py`)
- `CVDiff` and `GapAnalysis` are computed in **pure Python** by `utils/cv_diff.py` — not by any LLM agent
- See `ARCHITECTURE.md` for the full data model reference

### Anti-Hallucination Rules

When writing or modifying agents:

- **NEVER** invent skills, experiences, or qualifications
- **ONLY** rephrase existing content from original CV
- Include explicit validation checks in auditor
- Score hallucinations: 0 = perfect, 10 = severe

### AI Cliché Blacklist

Avoid these terms in generated content:

- "orchestrated", "spearheaded", "leveraged"
- "synergy", "tapestry", "dynamic"
- "innovative", "cutting-edge", "game-changer"
- "passion for", "excited to bring"

### File Organization

- Agents: `workflows/agents.py`
- Workflow orchestration: `workflows/__init__.py` (`ResumeTailorWorkflow`)
- Data models: `models/agents/output.py` (agent outputs), `models/agents/deps.py` (dependencies)
- Workflow result: `models/workflow.py` (`ResumeTailorResult`)
- Tools: `tools/playwright.py` (file reading), `tools/job_scraper_helpers.py` (HTML parsing, placeholder detection)
- Memory: `memory/service.py` (`ResumeMemoryService`), `memory/sqlite_repository.py`
- Utils: `utils/cv_diff.py` (pure-Python diff/gap), `utils/resume_converter.py` (DOCX/PDF→MD)
- Memory DB: `files/resume_memory.sqlite3`
- Output: `output/<company>-<job>/`

### Testing

- CLI tests: `tests/test_cli_typer.py`, `tests/test_main.py`
- Diff/gap analysis: `tests/test_cv_diff.py`
- Job scraper: `tests/test_job_scraper_helpers.py`, `tests/test_job_scraper.py`
- Quality gates: `tests/test_quality_gate.py`, `tests/test_quality_gate_models.py`
- Resume parsing determinism: `tests/test_parsing_determinism.py`
- Resume conversion: `tests/test_resume_converter.py`
- Memory layer: `tests/memory/test_service.py`, `tests/memory/test_sqlite_repository.py`
- Workflow integration: `tests/workflows/test_resume_tailor_workflow.py`
- Verbose mode: `tests/test_verbose_agent.py`
- Use demo files from `files/` for testing

## Code Style

### Python Standards

- Use type hints for all function parameters and returns
- Follow PEP 8 naming conventions
- Use descriptive variable names (avoid abbreviations)
- Document complex logic with inline comments

### Agent System Prompts

- Start with role definition: "You are a [role]"
- List explicit rules numbered 1, 2, 3...
- Include CRITICAL/IMPORTANT sections for key requirements
- Define clear pass/fail criteria where applicable

### Error Handling

- Agents have built-in retry mechanism (retry counts vary: 2 for quality gate, 3 for scraper, 5 for pipeline agents)
- Handle file I/O errors explicitly
- Validate structured outputs before passing between agents
- `UnexpectedModelBehavior` is caught in the workflow with fallback to `_QualityState.last_output` (graceful degradation)

### CLI Modes

- `--verbose / -v`: Streams agent thinking and output in real-time via `run_agent` helper; falls back to non-streaming on error
- `--debug / -d`: Enable debug output — prints content hash, cache status, first 500 chars of resume; saves converted resume to `resume_debug.md` in job output dir
- `--output-pattern` / `--resume-name-pattern`: Template strings with `{company_name}`, `{job_title}`, `{full_name}`, `{timestamp}` variables

### Content-Hash Caching

- `ResumeMemoryService.aresolve_original_resume` (async, for CLI) hashes resume content with SHA-256
- If content hash + parser version match a stored parsed record, the pre-parsed `CV` is reused — skipping the AI resume parser
- This avoids redundant LLM calls on re-runs with unchanged resume files
- The pre-parsed CV is passed to the workflow via `pre_parsed_cv` parameter

## Common Tasks

### Adding a New Agent

1. Define output model in `models/agents/output.py`
2. Create agent in `workflows/agents.py` with clear system prompt and `@output_validator` if needed
3. Add agent to workflow in `workflows/__init__.py` (`ResumeTailorWorkflow`)
4. Write integration tests in `tests/workflows/`
5. If the agent needs quality gate validation, create a `_QualityState` instance and wire the fallback in the workflow

### Modifying Agent Behavior

- Update system prompt rules
- Test with real job postings from `files/`
- Run auditor agent to validate output quality

### Testing Resume Parsing

- Use Markdown files from `files/` directory
- Verify structured `CV` object contains all original information
- Ensure no data loss during parsing

## Key Principles

1. **Authenticity First**: Generated content must sound human, not AI-generated
2. **No Hallucinations**: Never add information not present in original CV
3. **ATS Optimization**: Incorporate keywords naturally while maintaining readability
4. **Quality Over Quantity**: Better to highlight relevant experience than pad with fluff
5. **Validation Pipeline**: Every output passes through auditor and reviewer checks

## Dependencies

**Production** (from `pyproject.toml`):

- `pydantic-ai>=1.24.0`: Agent framework
- `playwright>=1.56.0`: Web scraping
- `html2text>=2025.4.15`: HTML → Markdown
- `markitdown[docx,pdf]>=0.1.0`: DOCX/PDF → Markdown
- `markdown>=3.10`, `markdown-pdf>=1.10`: Markdown/PDF output
- `python-docx>=1.1.0`: DOCX output
- `typer>=0.25.1`: CLI framework
- `rich>=14.2.0`: Console formatting
- `aiofiles>=25.1.0`: Async file I/O

**Dev dependencies**: `pytest>=8.0.0`, `pytest-anyio>=0.0.0`, `pytest-cov>=7.1.0`, `pytest-subtests>=0.13.0`, `ruff>=0.14.6`, `commitizen>=4.15.1`

**Build**: `hatchling`

**Package manager**: `uv` (Python ≥ 3.13, pinned by `.python-version`)
