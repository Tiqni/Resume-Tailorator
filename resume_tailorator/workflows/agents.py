import asyncio
import logging
import os
import time
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    ModelRetry,
    PartDeltaEvent,
    RunContext,
)
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import TextPartDelta, ThinkingPartDelta
from pydantic_ai.models import infer_model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import Usage, UsageLimits
from rich.console import Console

from resume_tailorator.models.agents.output import (
    AuditResult,
    CV,
    JobAnalysis,
    QualityCheckResult,
    ReviewResult,
    FinalReport,
)
from resume_tailorator.reporting.base import get_active_reporter

logger = logging.getLogger(__name__)
_console = Console()


def _safe_report(fn: Any, *args: Any, **kwargs: Any) -> None:
    """Invoke a best-effort reporter method, swallowing display errors.

    ProgressReporter methods are documented as best-effort: a buggy or custom
    reporter must never abort the agent run or the pipeline. Cancellation still
    propagates.
    """
    try:
        fn(*args, **kwargs)
    except (KeyboardInterrupt, asyncio.CancelledError):
        raise
    except Exception:
        logger.debug("reporter_call_failed", exc_info=True)


async def run_agent(
    agent: Agent,
    prompt: str,
    *,
    verbose: bool = False,  # retained for call-site compatibility; reporter drives streaming
    agent_label: str = "",
    usage: Usage | None = None,
    usage_limits: UsageLimits | None = None,
    model: str | None = None,
) -> AgentRunResult:
    """Run an agent, emitting lifecycle/token events to the active reporter."""
    reporter = get_active_reporter()

    run_kwargs: dict[str, Any] = {"usage": usage, "usage_limits": usage_limits}
    resolved = model if model is not None else resolve_model(agent_label)
    if resolved is not None:
        run_kwargs["model"] = resolved

    _safe_report(reporter.agent_start, agent_label, prompt)
    start = time.monotonic()

    try:
        wants_tokens = reporter.wants_tokens
    except Exception:
        logger.debug("reporter_call_failed", exc_info=True)
        wants_tokens = False

    if not wants_tokens:
        result = await agent.run(prompt, **run_kwargs)
        _safe_report(reporter.agent_done, agent_label, time.monotonic() - start)
        return result

    try:
        result = None
        async for event in agent.run_stream_events(prompt, **run_kwargs):
            if isinstance(event, AgentRunResultEvent):
                result = event.result
            elif isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta):
                    _safe_report(
                        reporter.token, agent_label, event.delta.content_delta, "output"
                    )
                elif isinstance(event.delta, ThinkingPartDelta):
                    _safe_report(
                        reporter.token,
                        agent_label,
                        event.delta.content_delta,
                        "thinking",
                    )

        if result is None:
            result = await agent.run(prompt, **run_kwargs)

        _safe_report(reporter.agent_done, agent_label, time.monotonic() - start)
        return result

    except (KeyboardInterrupt, asyncio.CancelledError):
        raise
    except (ModelRetry, UnexpectedModelBehavior):
        raise
    except Exception:
        logger.warning(
            "verbose_stream_failed_falling_back",
            extra={"agent_label": agent_label},
            exc_info=True,
        )
        _safe_report(
            reporter.note, f"Stream interrupted for [{agent_label}], falling back..."
        )
        result = await agent.run(prompt, **run_kwargs)
        _safe_report(reporter.agent_done, agent_label, time.monotonic() - start)
        return result


class _QualityState(BaseModel):
    """Holds the last output from one pipeline agent for fallback recovery."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    last_output: Any = None


_parser_qs = _QualityState()
_analyst_qs = _QualityState()
_writer_qs = _QualityState()
_auditor_qs = _QualityState()
_cover_qs = _QualityState()

MODEL_NAME = "openai:gpt-5-mini"
_original_model = MODEL_NAME


def _build_default_model() -> Any:
    """Build the default model object without requiring credentials at import.

    Passing a model *string* to ``Agent(...)`` makes pydantic-ai construct the
    provider's HTTP client immediately, which needs e.g. ``OPENAI_API_KEY`` even
    for a user running ``--model=ollama:...`` who has no OpenAI key. We instead
    build the default model here: with the real key when present, otherwise with
    a placeholder so import always succeeds. Agents still carry a *defined* model
    (required for ``Agent.override`` in tests and for per-run model overrides),
    but the placeholder key only matters if this default OpenAI model is actually
    used at run time — i.e. no ``--model`` override and no ``OPENAI_API_KEY`` —
    in which case OpenAI returns a clear authentication error.
    """
    if os.environ.get("OPENAI_API_KEY"):
        return infer_model(MODEL_NAME)
    # No key: build the OpenAI default with a placeholder so import never fails.
    _bare_name = MODEL_NAME.partition(":")[2] or MODEL_NAME
    return OpenAIChatModel(
        _bare_name, provider=OpenAIProvider(api_key="missing-openai-api-key")
    )


# Shared default model object reused by every agent below (see run_agent /
# resolve_model for how a --model override replaces it at run time).
_DEFAULT_MODEL = _build_default_model()

# Per-agent model tiers. Defaults equal MODEL_NAME (no behavior change until
# configured via set_agent_models()).
FAST_MODEL = MODEL_NAME
STRONG_MODEL = MODEL_NAME
_AGENT_TIERS = {
    "Parser": "fast",
    "Analyst": "fast",
    "Quality Gate": "fast",
    "Reviewer": "fast",
    "Writer": "strong",
    "Writer (refine)": "strong",
    "Auditor": "strong",
    "Report": "strong",
    "Cover Letter Writer": "strong",
    "Scraper": "fast",  # job_scraper_agent: cleanup pass on clean Markdown
}


def set_agent_models(*, fast: str | None = None, strong: str | None = None) -> None:
    """Override the fast/strong model tiers used by run_agent."""
    global FAST_MODEL, STRONG_MODEL
    if fast is not None:
        FAST_MODEL = fast
    if strong is not None:
        STRONG_MODEL = strong


def reset_agent_models() -> None:
    """Reset both tiers to the import-time default model (_original_model)."""
    global FAST_MODEL, STRONG_MODEL
    FAST_MODEL = _original_model
    STRONG_MODEL = _original_model


def agent_models_configured() -> bool:
    """True once set_agent_models() has moved a tier off the import-time default."""
    return not (FAST_MODEL == STRONG_MODEL == _original_model)


def resolve_model(agent_label: str) -> str | None:
    """Resolve the model for an agent label, or None to use the agent default."""
    if not agent_models_configured():
        return None  # unconfigured: let each agent use its own default model
    tier = _AGENT_TIERS.get(agent_label, "strong")
    return FAST_MODEL if tier == "fast" else STRONG_MODEL


def get_model() -> str:
    """Get the currently active model name."""
    return MODEL_NAME


def set_model(model: str) -> None:
    """Override the model for all agents."""
    global MODEL_NAME
    MODEL_NAME = model


def reset_model() -> None:
    """Reset model to the original default."""
    global MODEL_NAME
    MODEL_NAME = _original_model


def apply_model_override(model: str | None) -> None:
    """Point every agent tier at ``model`` unless tiers are already configured.

    Idempotent and safe to call before any agent runs, so the early pipeline
    stages (job scraper, cache resume-parser) honour --model just like the
    in-workflow agents. A no-op when ``model`` is falsy. When --fast (or an
    explicit set_agent_models call) has already configured distinct tiers, those
    are preserved — only the default MODEL_NAME is updated.
    """
    if not model:
        return
    set_model(model)
    if not agent_models_configured():
        set_agent_models(fast=model, strong=model)


MODEL_SETTINGS: dict = {}
USAGE_LIMITS = UsageLimits(request_limit=1000)

# Quality-gate config. Advisory mode: score once, retry only when broken.
QUALITY_GATE_ENABLED = True
QUALITY_GATE_THRESHOLD = 6  # raise ModelRetry only when score < threshold


def set_quality_gate(*, enabled: bool, threshold: int) -> None:
    global QUALITY_GATE_ENABLED, QUALITY_GATE_THRESHOLD
    QUALITY_GATE_ENABLED = enabled
    QUALITY_GATE_THRESHOLD = threshold


def reset_quality_gate() -> None:
    global QUALITY_GATE_ENABLED, QUALITY_GATE_THRESHOLD
    QUALITY_GATE_ENABLED = True
    QUALITY_GATE_THRESHOLD = 6


async def _score_output(role: str, label: str, payload: str, ctx) -> int | None:
    """Run the quality gate once and emit the score. Returns the score or None
    when the gate is disabled."""
    if not QUALITY_GATE_ENABLED:
        return None
    result = await run_agent(
        quality_gate_agent,
        f"Role: {role}\nOutput:\n{payload}",
        agent_label="Quality Gate",
        usage=getattr(ctx, "usage", None),
        usage_limits=USAGE_LIMITS,
    )
    score = result.output.score
    get_active_reporter().quality_score(label, score)
    if score < QUALITY_GATE_THRESHOLD:
        get_active_reporter().agent_retry(
            label, f"quality score {score} < {QUALITY_GATE_THRESHOLD}"
        )
        raise ModelRetry(
            f"Score: {score}/10. Improvements needed:\n"
            + "\n".join(f"- {i}" for i in result.output.improvements)
        )
    return score


# --- Quality Gate Agent ---
# Universal reviewer: scores any pipeline agent's output 0-10 and requests improvements.
quality_gate_agent = Agent(
    _DEFAULT_MODEL,
    model_settings=MODEL_SETTINGS,
    system_prompt="""You are a strict Quality Gate Reviewer for a resume tailoring pipeline.
Score the output of the agent whose role is specified in the prompt, on a scale of 0 to 10.
Scoring criteria by role:
  - Resume Parser: completeness, no data loss, correctly structured fields
  - Job Analyst: keyword coverage, clear requirement identification, no omissions
  - CV Writer: no hallucinations, ATS keywords incorporated naturally, human tone, no clichés
  - Auditor: thorough hallucination check, specific cliché identification, actionable feedback
  - Cover Letter Writer: authentic human voice, no AI clichés, specific to the role, concise
Score the output honestly from 0 to 10 based on the criteria above.
A score of 9 or 10 means excellent; 6 to 8 means acceptable; below 6 means the
output is broken and must be regenerated.
Always provide reasoning, and list specific improvements whenever the score is below 9.""",
    output_type=QualityCheckResult,
    retries=2,
)

# --- Agent 1: The Job Analyst ---
# Responsibility: Turn Markdown or raw text into a structured JobAnalysis object.
analyst_agent = Agent(
    _DEFAULT_MODEL,
    model_settings=MODEL_SETTINGS,
    system_prompt="""
    You are an expert Technical Recruiter.
    Your job is to analyze a raw job posting and extract structured data.
    Identify the core requirements, not just the 'nice to haves'.
    Look for 'hidden' keywords that ATS systems might scan for.
    """,
    output_type=JobAnalysis,
    retries=2,
)

# --- Agent 1.5: The Resume Parser ---
# Responsibility: Parse markdown resume into structured CV object
resume_parser_agent = Agent(
    _DEFAULT_MODEL,
    model_settings=MODEL_SETTINGS,
    system_prompt="""
    You are an expert Resume Parser.
    Your job is to parse a resume in Markdown format and extract ALL information into a structured format.

    RULES:
    1. Extract ALL information accurately from the markdown resume — leave nothing behind
    2. Extract skills from EVERY section: summary, experience bullets, projects, certifications,
       education, and publications — not just a dedicated "Skills" section
    3. Every technical term, framework, language, tool, methodology, platform, protocol,
       database, and soft skill mentioned anywhere in the resume is a skill — capture it
    4. For a senior professional resume, expect to extract 40+ individual skills
    5. Do NOT add or modify any information — preserve the exact wording
    6. Structure work experience with company, role, dates, and highlight bullets
    7. Include all projects with their descriptions
    8. Preserve all education entries, certifications, and publications
    9. CRITICAL: Preserve ALL hyperlinks in their original markdown format [text](url).
       Never convert clickable links to plain text or bare URLs. Links can appear in
       summary, projects, publications, experience highlights, or any other field.
    """,
    output_type=CV,
    retries=2,
)

# --- Agent 2: The Writer ---
# Responsibility: Rewrite the CV based on the Analysis.
writer_agent = Agent(
    _DEFAULT_MODEL,
    model_settings=MODEL_SETTINGS,
    system_prompt="""
    You are a Senior Resume Writer.
    Input: A structured CV object and a Job Analysis.
    Task: Rewrite the CV to target the Job Analysis while preserving all original information.

    CRITICAL RULES:
    1. ONLY use skills, experiences, and information from the Original CV - DO NOT invent anything
    2. You may REPHRASE existing content to align with job keywords, but DO NOT add new skills or experiences
    3. Highlight relevant experiences that match the job requirements
    4. Use keywords from the job analysis naturally within existing content
    5. Use active voice and quantifiable achievements
    6. Avoid AI clichés like "orchestrated", "spearheaded", "leveraged", "synergy", "tapestry"
    7. Keep a professional but natural tone
    8. Maintain chronological order and accurate dates
    9. If the original CV lacks a required skill, do NOT add it - focus on highlighting transferable skills instead
    10. Group all the skills so that the most relevant skills to the job are at the top of the skills section
    11. CRITICAL: Preserve ALL hyperlinks from the Original CV in their exact markdown format [text](url).
        Never convert clickable links to plain text, bare URLs, or parenthetical URLs.
        You may rephrase the surrounding text, but the link syntax must stay intact.
    """,
    output_type=CV,
    retries=2,
)

# --- Agent 3: The Auditor ---
# Responsibility: Compare Original vs New to catch lies and AI-speak.
auditor_agent = Agent(
    _DEFAULT_MODEL,
    model_settings=MODEL_SETTINGS,
    system_prompt="""
    You are a strict Compliance Auditor and Resume Quality Checker.
    Input: Original CV (structured), New CV (structured), and Job Analysis.

    Your task is to ensure the new CV is honest, professional, and well-targeted.

    VALIDATION CHECKS:
    
    1. HALLUCINATION CHECK (CRITICAL):
       - Verify NO new skills were added that don't exist in the original CV
       - Verify NO new companies, roles, or experiences were invented
       - Verify NO exaggerated dates or responsibilities
       - Each bullet point in the new CV must trace back to the original
       - Score: 0 = perfect, 10 = severe hallucinations
    
    2. AI CLICHÉ CHECK:
       - Flag overused AI phrases: "orchestrated", "spearheaded", "leveraged", "synergy", "tapestry", "dynamic", "innovative" (when overused)
       - Check for robotic or unnatural language
       - Ensure human-like, professional tone
       - Score: 0 = natural, 10 = very robotic
    
    3. HYPERLINK PRESERVATION CHECK:
       - Verify ALL hyperlinks from the original CV are present in the new CV
       - Verify links use the correct markdown format [text](url) — not plain text or bare URLs
       - Flag any missing or broken link as a critical issue in the issues list
       - No separate score field exists for this check — use issues and passed to reflect results
    
    4. RELEVANCE CHECK:
       - Verify the CV highlights experiences matching job requirements
       - Check if job keywords are naturally incorporated
       - Ensure the most relevant skills are prominent
    
    5. QUALITY CHECK:
       - Verify proper structure and formatting
       - Check for clear, quantifiable achievements
       - Ensure consistency in dates and information
    
    PASS CRITERIA:
    - Hallucination score must be 0-2 (minor rephrasing acceptable)
    - AI cliché score must be 0-3 (minimal AI language)
    - All hyperlinks from the original CV must be preserved in [text](url) format
    - All critical issues must be resolved
    
    Return a detailed structured Audit Result with specific issues and actionable suggestions.
    """,
    output_type=AuditResult,
    retries=2,
)

# --- Agent 4: The Cover Letter Writer ---
# Responsibility: Write a personalized, human-sounding cover letter.
cover_letter_writer_agent = Agent(
    _DEFAULT_MODEL,
    model_settings=MODEL_SETTINGS,
    system_prompt="""
    You are an experienced Career Coach specializing in authentic, human cover letters.
    Input: A structured CV object and a Job Analysis.
    Task: Write a compelling cover letter that sounds genuinely human, not AI-generated.

    CRITICAL RULES:
    1. Write in a conversational, authentic tone - like a real person explaining why they're interested
    2. AVOID AI clichés at all costs: "leverage", "spearhead", "orchestrate", "passion for", "excited to bring", "dynamic", "synergy", "game-changer", "cutting-edge"
    3. Use simple, direct language - no corporate jargon or buzzwords
    4. Tell a brief, specific story connecting your experience to the role
    5. Reference actual projects or experiences from the CV (don't invent)
    6. Show you understand the company/role without generic flattery
    7. Keep it concise (3-4 short paragraphs max)
    8. Use contractions occasionally (I'm, I've, don't) to sound natural
    9. Vary sentence structure - mix short and longer sentences
    10. End with a simple, confident close (no "I look forward to hearing from you")

    STRUCTURE:
    - Opening: Why this specific role/company interests you (be specific, not generic)
    - Body: 1-2 examples of relevant experience with concrete details
    - Close: Brief statement of fit and next step

    TONE: Professional but personable. Write like you're explaining to a friend why you're applying.
    """,
    output_type=str,  # or create a CoverLetter pydantic model if you want structured output
    retries=2,
)


# --- Agent 3.5: The Reviewer ---
# Responsibility: Review quality and suggest specific improvements
reviewer_agent = Agent(
    _DEFAULT_MODEL,
    model_settings=MODEL_SETTINGS,
    system_prompt="""
    You are a Senior Resume Quality Reviewer.
    Input: A tailored CV and Job Analysis.
    Task: Review the CV quality and provide specific, actionable improvement suggestions.

    REVIEW CRITERIA:
    1. KEYWORD OPTIMIZATION:
       - Are critical job keywords naturally incorporated?
       - Are technical skills highlighted effectively?
       
    2. IMPACT & ACHIEVEMENTS:
       - Are accomplishments quantified where possible?
       - Is impact clearly demonstrated?
       
    3. RELEVANCE:
       - Is irrelevant content minimized?
       - Are most relevant experiences prioritized?
       
    4. CLARITY & READABILITY:
       - Is language clear and concise?
       - Are bullet points scannable?
       
    5. ATS COMPATIBILITY:
       - Is formatting ATS-friendly?
       - Are keywords in context?

    Return structured feedback with:
    - quality_score (0-10): Overall quality rating
    - needs_improvement (bool): True if score < 8
    - specific_suggestions (list): Concrete improvements needed
    - strengths (list): What's working well
    """,
    output_type=ReviewResult,  # You'll need to create this model
    retries=5,
)


# --- Agent 5: The Report Writer ---
# Responsibility: Write the narrative section of the self-review report.
# Receives pre-computed CVDiff, GapAnalysis, AuditResult, ReviewResult, and
# JobAnalysis as structured JSON. Produces only narrative fields (factual diff
# and gap data are injected by the workflow, not generated by the LLM).
report_agent = Agent(
    _DEFAULT_MODEL,
    model_settings=MODEL_SETTINGS,
    system_prompt="""
    You are a Career Advisor writing a clear, honest self-review report.

    You receive pre-computed structured data about:
    - What changed between the original and tailored CV (CVDiff JSON)
    - Skill and keyword gaps vs. job requirements (GapAnalysis JSON)
    - Audit quality scores: hallucination and AI-cliché (AuditResult JSON)
    - Quality review scores (ReviewResult JSON)
    - Job requirements (JobAnalysis JSON)

    Your job is to produce ONLY the following narrative fields:
    1. overall_recommendation: exactly one of "Strong Match", "Partial Match", or "Weak Match"
       - "Strong Match": keyword_coverage_percent >= 80 AND missing_hard_skills <= 1
       - "Partial Match": keyword_coverage_percent >= 50 OR missing_hard_skills <= 3
       - "Weak Match": everything else
    2. match_score (0-100): base it primarily on keyword_coverage_percent,
       subtract 5 points per missing hard skill, subtract 2 per missing soft skill.
    3. suggestions_to_strengthen: 2-4 concrete, actionable items the candidate can do
       to close the gaps (certifications, side projects, courses, etc.)
    4. audit_summary: one paragraph in plain English summarising the hallucination
       score and AI-cliché score from the AuditResult.
    5. recommendation_rationale: one honest paragraph explaining your overall_recommendation.
       Be direct. Do not sugarcoat weak matches.

    CRITICAL RULES:
    - Never use AI clichés: "orchestrated", "spearheaded", "leveraged", "synergy",
      "tapestry", "dynamic", "innovative", "cutting-edge", "game-changer".
    - Do not repeat the raw JSON back. Synthesise it into human-readable text.
    - Be concise: audit_summary and recommendation_rationale should each be 2-4 sentences.

    You also receive raw structured JSON in the user prompt. For the following fields,
    copy them VERBATIM from the JSON input — do NOT reinterpret, summarise, or alter them:
    - what_changed: copy the CVDiff JSON object exactly as provided
    - gaps: copy the GapAnalysis JSON object exactly as provided
    - job_title: copy the job title string exactly as provided
    - company_name: copy the company name string exactly as provided
    - generated_at: copy the ISO 8601 timestamp string exactly as provided

    For the `passed` field: set it to true if BOTH of the following are true:
    - AuditResult.passed is true (hallucination_score <= 2 and clique_score <= 2)
    - overall_recommendation is "Strong Match" or "Partial Match"
    Otherwise set passed to false.
    """,
    output_type=FinalReport,
    retries=5,
)


# ---------------------------------------------------------------------------
# Quality Gate Validators
# ---------------------------------------------------------------------------


@auditor_agent.output_validator
async def _validate_auditor(ctx: RunContext[None], output: AuditResult) -> AuditResult:
    _auditor_qs.last_output = output
    await _score_output("Auditor", "Auditor", output.model_dump_json(indent=2), ctx)
    return output


job_scraper_agent = Agent(
    _DEFAULT_MODEL,
    model_settings=MODEL_SETTINGS,
    output_type=str,
    retries=3,
)


@job_scraper_agent.system_prompt
async def build_scraper_instructions() -> str:
    """System prompt: isolate the job posting from already-clean Markdown."""
    return """You clean up a job posting that has already been converted to Markdown.

The Markdown you receive is the FULL page body, so it surrounds the real posting
with navigation, cookie/consent banners, search bars, "related jobs", social
links, and footer boilerplate.

Your task: return ONLY the job posting as clean Markdown.

CRITICAL RULES:
1. Never invent or add information. Only keep and lightly tidy what is present.
2. Remove site chrome: nav menus, cookie/consent banners, search bars,
   related/similar jobs, social/share links, and footers.
3. Keep the role title, company, location, description, responsibilities,
   requirements, and benefits.
4. Preserve wording. Do not paraphrase, summarize, or editorialize.
5. Output Markdown only. No commentary and no code fences."""


@cover_letter_writer_agent.output_validator
async def _validate_cover_letter_writer(ctx: RunContext[None], output: str) -> str:
    _cover_qs.last_output = output
    await _score_output("Cover Letter Writer", "Cover Letter Writer", output, ctx)
    return output


@writer_agent.output_validator
async def _validate_writer(ctx: RunContext[None], output: CV) -> CV:
    _writer_qs.last_output = output
    await _score_output("CV Writer", "Writer", output.model_dump_json(indent=2), ctx)
    return output
