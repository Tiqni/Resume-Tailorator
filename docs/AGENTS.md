# Agent Reference — Resume Tailorator

Companion to the root [AGENTS.md](../AGENTS.md). This file provides detailed reference for AI agents working on this codebase.

## Agent Inventory

### Pipeline Agents (`workflows/agents.py`)

| # | Variable | Output Type | Retries | Quality Gate | Used In |
|---|----------|-------------|:-------:|:---:|---------|
| 0 | `job_scraper_agent` | `ScrapedJobPosting` | 3 | No (tool-based) | CLI pre-pipeline |
| 1 | `resume_parser_agent` | `CV` | 5 | Yes | Pipeline stage 1 |
| 2 | `analyst_agent` | `JobAnalysis` | 5 | Yes | Pipeline stage 2 |
| 3 | `writer_agent` | `CV` | 5 | Yes | Pipeline stage 3 + refinement |
| 4 | `reviewer_agent` | `ReviewResult` | 5 | No | Pipeline stage 4 |
| 5 | `auditor_agent` | `AuditResult` | 5 | Yes | Pipeline stage 5 |
| 6 | `report_agent` | `FinalReport` | 5 | No | Pipeline stage 6 |
| — | `cover_letter_writer_agent` | `str` | 5 | Yes | Not wired |
| — | `quality_gate_agent` | `QualityCheckResult` | 2 | N/A | Validator for all gated agents |
| — | `scraper_agent` | `JobAnalysis` | 5 | No | Legacy; not used by CLI |

### Quality Gate Validator Functions

| Validator | Guards | Fallback State |
|-----------|--------|----------------|
| `_validate_resume_parser` | `resume_parser_agent` | `_parser_qs` |
| `_validate_analyst` | `analyst_agent` | `_analyst_qs` |
| `_validate_writer` | `writer_agent` | `_writer_qs` |
| `_validate_auditor` | `auditor_agent` | `_auditor_qs` |
| `_validate_cover_letter_writer` | `cover_letter_writer_agent` | `_cover_qs` |

## Agent Tools

### `job_scraper_agent` Tools

| Tool | Type | Signature |
|------|------|-----------|
| `fetch_webpage` | `@tool` (async) | `(ctx, url: str, timeout: int = 30) -> str` |
| `validate_extraction` | `@tool_plain` | `(raw_html: str, extracted_markdown: str) -> dict` |

### Legacy Tool

| Tool | Type | Agent |
|------|------|-------|
| `read_job_content_file` | `@tool` (async) | `scraper_agent` (legacy) |

## System Prompts Quick Reference

### Resume Parser — Key Rules
1. Extract ALL information accurately — leave nothing behind
2. Extract skills from EVERY section (summary, experience, projects, certs, education, publications)
3. For senior resumes, expect 40+ individual skills
4. Do NOT add or modify any information
5. CRITICAL: Preserve ALL hyperlinks in `[text](url)` format

### Writer — Key Rules
1. ONLY use skills, experiences, and information from the Original CV
2. You may REPHRASE but DO NOT add new skills or experiences
3. Highlight relevant experiences matching job requirements
4. Use keywords from job analysis naturally within existing content
5. Avoid AI clichés: "orchestrated", "spearheaded", "leveraged", "synergy", "tapestry"
6. Group relevant skills at the top of the skills section
7. CRITICAL: Preserve ALL hyperlinks from Original CV

### Auditor — Validation Checks
1. HALLUCINATION: No new skills/companies/roles/experiences invented; every bullet must trace to original
2. AI CLICHÉ: Flag "orchestrated", "spearheaded", "leveraged", "synergy", "tapestry", "dynamic", "innovative"
3. HYPERLINK PRESERVATION: All links present in `[text](url)` format — not plain text
4. RELEVANCE: CV highlights experiences matching job
5. QUALITY: Proper structure, quantifiable achievements, consistent dates

**Pass Criteria**: Hallucination score ≤ 2, AI cliché score ≤ 3, all hyperlinks preserved

## Model Configuration

```python
MODEL_NAME = "openai:gpt-5-mini"  # Default
# Override via:
set_model("openai:gpt-4o-mini")
# Reset to default:
reset_model()
```

Shared settings:
```python
MODEL_SETTINGS: dict = {}
USAGE_LIMITS = UsageLimits(request_limit=1000)
```

## Fallback Pattern

Each quality-gated agent uses this pattern:

```python
_my_qs = _QualityState()  # Module-level, holds last_output

@my_agent.output_validator
async def _validate_my_agent(ctx, output):
    _my_qs.last_output = output
    result = await run_agent(quality_gate_agent, f"Role: ...\nOutput:\n{json}")
    if result.output.score < 9:
        raise ModelRetry(f"Score: {score}/10...")
    return output
```

In the workflow (`__init__.py`):
```python
try:
    result = await run_agent(my_agent, prompt, ...)
    output = result.output
except UnexpectedModelBehavior:
    if _my_qs.last_output is not None:
        output = _my_qs.last_output  # Fallback
    else:
        output = None  # No fallback available
```

## Data Model Dependency Graph

```
CV ─────────────────────────────────┐
WorkExperience (nested in CV)       │
JobAnalysis ────────────────────────┤
ScrapedJobPosting (CLI only)        │
                                    ▼
                        writer_agent ──→ CV (tailored)
                                          │
                    ┌─────────────────────┤
                    ▼                     ▼
            reviewer_agent         auditor_agent
                    │                     │
                    ▼                     ▼
            ReviewResult            AuditResult
                    │                     │
                    └─────────┬───────────┘
                              ▼
              compute_cv_diff()  → CVDiff
              compute_gap_analysis() → GapAnalysis
                              │
                              ▼
                      report_agent → FinalReport
                              │
                              ▼
                      ResumeTailorResult
```

## Helper Functions

### `run_agent()` (in `workflows/agents.py`)

```python
async def run_agent(
    agent: Agent,
    prompt: str,
    *,
    verbose: bool = False,
    agent_label: str = "",
    usage: Usage | None = None,
    usage_limits: UsageLimits | None = None,
) -> AgentRunResult:
```

When `verbose=True`, streams `TextPartDelta` and `ThinkingPartDelta` events to console via Rich. Falls back to non-streaming on error.

### Model Management

```python
get_model() -> str         # Returns current MODEL_NAME
set_model(model: str)      # Override MODEL_NAME globally
reset_model()              # Reset to original default
```

## Workflow Constants

| Constant | Value | Meaning |
|----------|-------|---------|
| `MAX_RETRIES` | 3 | Max pipeline stage retries |
| `max_review_iterations` | 3 | Max review-refinement iterations per write |
| `max_write_attempts` | 3 | Max write→review→audit outer loop retries |

## Pipeline Stages

```python
STAGES = [
    "PARSING_RESUME",
    "ANALYZING_JOB",
    "WRITING_CV",
    "REVIEWING_CV",
    "AUDITING_CV",
    "GENERATING_REPORT",
]
```

Each stage tracks: `pending` → `running` → `done` / `failed`.
