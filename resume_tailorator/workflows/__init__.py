import asyncio
import sys
from datetime import datetime, timezone

from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.usage import RunUsage

from resume_tailorator.models.agents.output import CV, CVDiff, FinalReport, JobAnalysis
from resume_tailorator.models.workflow import ResumeTailorResult
from resume_tailorator.reporting.base import (
    NullReporter,
    ProgressReporter,
    use_reporter,
)
from resume_tailorator.utils.cv_diff import compute_cv_diff, compute_gap_analysis
from resume_tailorator.workflows.agents import (
    USAGE_LIMITS,
    _analyst_qs,
    _auditor_qs,
    _parser_qs,
    _writer_qs,
    analyst_agent,
    auditor_agent,
    report_agent,
    resume_parser_agent,
    reviewer_agent,
    run_agent,
    writer_agent,
    apply_model_override,
    get_model,
)


class UserAbortedError(Exception):
    """Raised when the user explicitly aborts at an interactive checkpoint."""


class ResumeTailorWorkflow:
    MAX_RETRIES = 3
    max_review_iterations = 1
    max_write_attempts = 2

    # Pipeline stages for status tracking
    STAGES = [
        "PARSING_RESUME",
        "ANALYZING_JOB",
        "WRITING_CV",
        "REVIEWING_CV",
        "AUDITING_CV",
        "GENERATING_REPORT",
    ]

    def __init__(
        self,
        write_attempts: int | None = None,
        review_iterations: int | None = None,
        interactive: bool = False,
    ):
        self._current_stage: str | None = None
        self._stage_status: dict[str, str] = {stage: "pending" for stage in self.STAGES}
        self._reporter: ProgressReporter = NullReporter()
        self._interactive = interactive
        if write_attempts is not None:
            self.max_write_attempts = write_attempts
        if review_iterations is not None:
            self.max_review_iterations = review_iterations

    def _set_stage(self, stage: str) -> None:
        """Mark current stage as running, previous as done."""
        if self._current_stage and self._current_stage in self._stage_status:
            if self._stage_status[self._current_stage] == "running":
                self._stage_status[self._current_stage] = "done"
                self._reporter.stage_done(self._current_stage, success=True)
        self._current_stage = stage
        if stage in self._stage_status:
            self._stage_status[stage] = "running"
        self._reporter.stage_start(stage)

    def _complete_stage(self, stage: str, success: bool = True) -> None:
        """Mark a stage as completed or failed."""
        if stage in self._stage_status:
            self._stage_status[stage] = "failed" if not success else "done"
        self._reporter.stage_done(stage, success=success)

    def _human_checkpoint(
        self,
        header: str,
        details: list[str],
        choices: list[tuple[str, str]],
        default: str = "c",
    ) -> tuple[str, str]:
        """Present an interactive checkpoint and return (action_key, feedback_text).

        Returns (default, "") immediately when non-interactive or stdin is not a TTY.
        Loops on unrecognized input. Loops on empty feedback when "f" is selected.
        """
        if not self._interactive:
            return (default, "")
        if not sys.stdin.isatty():
            self._reporter.log("⚠️  Interactive checkpoint skipped (stdin is not a TTY — using default)")
            return (default, "")

        valid_keys = {key for key, _ in choices}

        while True:
            print(f"\n{header}")
            for line in details:
                print(f"  {line}")
            print("\nWhat would you like to do?")
            for key, label in choices:
                print(f"  [{key}] {label}")
            print()
            raw = input(f"Choice [{default}]: ").strip().lower() or default

            if raw not in valid_keys:
                print(f"Unrecognized choice '{raw}'. Please choose from: {', '.join(sorted(valid_keys))}")
                continue

            if raw == "f":
                while True:
                    feedback = input("Your feedback/instructions: ").strip()
                    if feedback:
                        return ("f", feedback)
                    print("Feedback cannot be empty. Please provide your instructions.")

            return (raw, "")

    async def _parse_resume(self, resume_text: str, debug: bool, verbose: bool) -> CV:
        """Parse the original resume into a CV. Raises on hard failure."""
        usage = RunUsage()
        original_cv: CV | None = None
        original_cv_result = None
        for attempt in range(self.MAX_RETRIES):
            try:
                original_cv_result = await run_agent(
                    resume_parser_agent,
                    f"Parse this resume into structured format:\n\n{resume_text}",
                    verbose=verbose,
                    agent_label="Parser",
                    usage=usage,
                    usage_limits=USAGE_LIMITS,
                )
                if original_cv_result.output is None:
                    raise ValueError("Resume parsing returned None")
                if (
                    original_cv_result.output.full_name
                    and original_cv_result.output.experience
                ):
                    original_cv = original_cv_result.output
                    break
                self._reporter.log(
                    f"⚠️ Attempt {attempt + 1}/{self.MAX_RETRIES}: Incomplete resume parse, retrying..."
                )
            except UnexpectedModelBehavior:
                if _parser_qs.last_output is not None:
                    self._reporter.log(
                        "⚠️  Resume Parser failed — using best available output"
                    )
                    original_cv = _parser_qs.last_output
                    break
                raise
            except Exception as e:
                self._reporter.log(
                    f"⚠️ Attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}"
                )
                if attempt == self.MAX_RETRIES - 1:
                    raise
        if original_cv is None:
            if original_cv_result is None or original_cv_result.output is None:
                raise RuntimeError("Failed to parse original resume after retries.")
            original_cv = original_cv_result.output
        self._parse_usage = usage
        return original_cv

    async def _analyze_job(
        self, job_analysis_prompt: str, verbose: bool
    ) -> JobAnalysis:
        """Analyze the job posting. Raises on hard failure."""
        usage = RunUsage()
        job_analysis = None
        job_analysis_result = None
        for attempt in range(self.MAX_RETRIES):
            try:
                job_analysis_result = await run_agent(
                    analyst_agent,
                    job_analysis_prompt,
                    verbose=verbose,
                    agent_label="Analyst",
                    usage=usage,
                    usage_limits=USAGE_LIMITS,
                )
                if job_analysis_result.output is None:
                    raise ValueError("Job analysis data is None")
                if (
                    job_analysis_result.output.job_title
                    and job_analysis_result.output.company_name
                ):
                    job_analysis = job_analysis_result.output
                    break
                self._reporter.log(
                    f"⚠️ Attempt {attempt + 1}/{self.MAX_RETRIES}: Incomplete job data, retrying..."
                )
            except UnexpectedModelBehavior:
                if _analyst_qs.last_output is not None:
                    self._reporter.log(
                        "⚠️  Job Analyst failed — using best available output"
                    )
                    job_analysis = _analyst_qs.last_output
                    break
                raise
            except Exception as e:
                self._reporter.log(
                    f"⚠️ Attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}"
                )
                if attempt == self.MAX_RETRIES - 1:
                    raise
        if job_analysis is None:
            if job_analysis_result is None or job_analysis_result.output is None:
                raise RuntimeError("Failed to get complete job analysis after retries.")
            job_analysis = job_analysis_result.output
        self._analyze_usage = usage
        self._analyst_result = job_analysis_result  # used later for gap analysis
        return job_analysis

    async def run(
        self,
        resume_text: str,
        job_content_file_path: str | None = None,
        job_content: str | None = None,
        model: str | None = None,
        *,
        pre_parsed_cv: CV | None = None,
        debug: bool = False,
        verbose: bool = False,
        reporter: ProgressReporter | None = None,
    ) -> ResumeTailorResult:
        """Run the resume tailoring workflow.

        Installs `reporter` (or a NullReporter) as the active progress reporter
        for the duration of the run, then delegates to _run_impl.
        """
        self._reporter = reporter or NullReporter()
        try:
            with use_reporter(self._reporter):
                return await self._run_impl(
                    resume_text,
                    job_content_file_path=job_content_file_path,
                    job_content=job_content,
                    model=model,
                    pre_parsed_cv=pre_parsed_cv,
                    debug=debug,
                    verbose=verbose,
                )
        finally:
            self._reporter = NullReporter()

    async def _run_impl(
        self,
        resume_text: str,
        job_content_file_path: str | None = None,
        job_content: str | None = None,
        model: str | None = None,
        *,
        pre_parsed_cv: CV | None = None,
        debug: bool = False,
        verbose: bool = False,
    ) -> ResumeTailorResult:
        # Override model if specified. Idempotent with the CLI layer, which calls
        # apply_model_override before the scraper/parser so they honour --model too.
        # A bare --model pins every tier; --fast's distinct tiers are preserved.
        apply_model_override(model)
        self._reporter.log(f"🤖 Using model: {model or get_model()}")

        self._reporter.log("🚀 STARTING MULTI-AGENT PIPELINE\n")

        total_usage = RunUsage()

        # --- STEPS 0 & 1: PARSE RESUME ∥ ANALYZE JOB (concurrent on cold cache) ---
        # Build the job-analysis prompt first (cheap, synchronous).
        if job_content:
            job_analysis_prompt = f"Analyze the following job posting and extract structured job data:\n\n{job_content}"
        elif job_content_file_path:
            job_analysis_prompt = (
                f"Analyze the job content located at this file path {job_content_file_path} "
                f"and extract structured job data."
            )
        else:
            sys.exit(
                "❌ No job content provided. Supply either job_content or job_content_file_path."
            )

        self._parse_usage = RunUsage()
        self._analyze_usage = RunUsage()
        self._analyst_result = None

        self._set_stage("PARSING_RESUME")
        original_cv: CV | None = None

        try:
            if pre_parsed_cv is not None:
                self._reporter.log(
                    "♻️  Using cached parsed resume (skipping AI parsing)"
                )
                original_cv = pre_parsed_cv
                self._complete_stage("PARSING_RESUME")
                self._set_stage("ANALYZING_JOB")
                job_analysis = await self._analyze_job(job_analysis_prompt, verbose)
            else:
                # Parse and analyze run concurrently — show BOTH as running.
                # Mark ANALYZING_JOB running directly (do NOT use _set_stage,
                # which would prematurely flip the in-flight PARSING_RESUME to
                # done before the gather completes).
                self._stage_status["ANALYZING_JOB"] = "running"
                self._current_stage = "ANALYZING_JOB"
                self._reporter.stage_start("ANALYZING_JOB")
                original_cv, job_analysis = await asyncio.gather(
                    self._parse_resume(resume_text, debug, verbose),
                    self._analyze_job(job_analysis_prompt, verbose),
                )
                self._complete_stage("PARSING_RESUME")
        except UnexpectedModelBehavior:
            self._complete_stage("PARSING_RESUME", success=False)
            self._complete_stage("ANALYZING_JOB", success=False)
            sys.exit(
                "❌ Resume parsing or job analysis failed: the agent did not return "
                "usable output after retries."
            )
        except (RuntimeError, ValueError) as e:
            self._complete_stage("ANALYZING_JOB", success=False)
            sys.exit(f"❌ {e}")

        # Merge per-branch usage into the run total.
        total_usage.incr(self._parse_usage)
        total_usage.incr(self._analyze_usage)

        self._complete_stage("ANALYZING_JOB")
        self._reporter.log(f"   ✅ Resume Parsed: {original_cv.full_name}")
        self._reporter.log(
            f"   📋 Found {len(original_cv.skills)} skills, {len(original_cv.experience)} work experiences\n"
        )
        self._reporter.log(
            f"   ✅ Job Analyzed: {job_analysis.job_title} at {job_analysis.company_name}"
        )
        self._reporter.log(f"   🎯 Keywords found: {job_analysis.keywords_to_target}\n")

        original_cv_json = original_cv.model_dump_json()
        job_data_json = job_analysis.model_dump_json()

        # --- STEP 2: WRITE + REVIEW + AUDIT LOOP (with optional feedback retry) ---
        user_feedback: str = ""
        feedback_attempts_remaining: int = 1

        while True:
            new_cv: CV | None = None
            audit = None
            review = None
            audit_passed = False

            for write_attempt in range(self.max_write_attempts):
                self._set_stage("WRITING_CV")
                self._reporter.log(
                    f"🤖 Agent 2 (Writer): Tailoring CV (Attempt {write_attempt + 1}/{self.max_write_attempts})..."
                )
                if write_attempt == 0:
                    self._reporter.log(
                        f"   [Debug] Original CV has {len(original_cv.skills)} skills"
                    )
                    writer_prompt = f"""
Here is the Job Analysis:
{job_data_json}

Here is the Original CV (structured):
{original_cv_json}

Rewrite the CV to match the Job Analysis. Use ONLY the information from the Original CV.
Rephrase and reorganize to highlight relevant experience, but do NOT add new skills or experiences.
"""
                else:
                    self._reporter.log("   🔄 Retrying with audit feedback...")
                    issues_text = "\n".join(
                        [
                            f"- [{getattr(i, 'severity', 'Unknown')}] {getattr(i, 'issue', str(i))} -> {getattr(i, 'suggestion', '')}"
                            for i in getattr(audit, "issues", [])
                        ]
                    )
                    writer_prompt = f"""
The previous CV draft failed the audit. Here is the feedback:

Audit Feedback: {getattr(audit, "feedback_summary", "")}

Issues to fix:
{issues_text}

Here is the Job Analysis:
{job_data_json}

Here is the Original CV (structured):
{original_cv_json}

CRITICAL RULES:
1. ONLY use skills and experience from the Original CV - DO NOT add new skills
2. Fix all the issues mentioned in the audit feedback
3. Ensure all job requirements are addressed using ONLY existing skills from the original CV
4. Avoid AI clichés and use natural language
5. You may rephrase existing content but cannot add new information

Rewrite the CV to match the Job Analysis while addressing all audit feedback.
"""

                if user_feedback:
                    writer_prompt += (
                        f"\n\n---\n"
                        f"**Additional instructions from the user:**\n{user_feedback}\n"
                    )

                try:
                    writer_result = await run_agent(
                        writer_agent,
                        writer_prompt,
                        verbose=verbose,
                        agent_label="Writer",
                        usage=total_usage,
                        usage_limits=USAGE_LIMITS,
                    )
                    new_cv = writer_result.output or None
                except UnexpectedModelBehavior:
                    if _writer_qs.last_output is not None:
                        self._reporter.log(
                            "⚠️  CV Writer quality gate exhausted — using best available output"
                        )
                        new_cv = _writer_qs.last_output
                    else:
                        self._reporter.log(
                            "⚠️  CV Writer quality gate exhausted with no fallback — skipping tailoring"
                        )
                        new_cv = None

                if new_cv is None:
                    if write_attempt == self.max_write_attempts - 1:
                        self._complete_stage("WRITING_CV", success=False)
                        break  # exhausted retries — report phase still runs below
                    continue

                self._complete_stage("WRITING_CV")
                self._reporter.log(
                    f"   ✅ CV Drafted. Summary: {new_cv.summary[:100]}...\n"
                )

                # --- STEP 2.5: QUALITY REVIEW (Agent 2.5) ---
                self._set_stage("REVIEWING_CV")
                for review_iteration in range(self.max_review_iterations):
                    self._reporter.log(
                        f"🤖 Agent 2.5 (Reviewer): Checking CV quality (Iteration {review_iteration + 1}/{self.max_review_iterations})..."
                    )

                    review_prompt = f"""
Review this CV against job requirements:

CV: {new_cv.model_dump_json() if hasattr(new_cv, "model_dump_json") else str(new_cv)}
Job Analysis: {job_data_json}

Assess quality and suggest improvements if needed.
"""

                    try:
                        review_result = await run_agent(
                            reviewer_agent,
                            review_prompt,
                            verbose=verbose,
                            agent_label="Reviewer",
                            usage=total_usage,
                            usage_limits=USAGE_LIMITS,
                        )
                        review = review_result.output

                        if review is None:
                            self._reporter.log(
                                "   ⚠️ Review returned None, skipping quality check\n"
                            )
                            break

                        self._reporter.log(
                            f"   📊 Quality Score: {review.quality_score}/10"
                        )

                        if review.strengths:
                            self._reporter.log(
                                f"   ✨ Strengths: {', '.join(review.strengths[:2])}"
                            )

                        if (
                            review.needs_improvement
                            and review_iteration < self.max_review_iterations - 1
                        ):
                            self._reporter.log(
                                "   🔄 Quality improvements needed, refining...\n"
                            )

                            suggestions_text = "\n".join(
                                f"- {s}" for s in review.specific_suggestions
                            )

                            improvement_prompt = f"""
Improve this CV based on reviewer feedback:

Current CV: {new_cv.model_dump_json() if hasattr(new_cv, "model_dump_json") else str(new_cv)}
Original CV: {original_cv_json}
Job Analysis: {job_data_json}

Specific improvements to address:
{suggestions_text}

CRITICAL RULES:
1. ONLY use information from the Original CV - DO NOT add new skills or experiences
2. Apply the suggestions to improve quality and relevance
3. Maintain accuracy and honesty
4. Use natural language, avoid AI clichés
5. Keep all dates and facts accurate

Focus on better highlighting relevant experience and incorporating job keywords naturally.
"""

                            refined_result = await run_agent(
                                writer_agent,
                                improvement_prompt,
                                verbose=verbose,
                                agent_label="Writer (refine)",
                                usage=total_usage,
                                usage_limits=USAGE_LIMITS,
                            )
                            if refined_result.output:
                                new_cv = refined_result.output
                                self._reporter.log("   ✅ CV refined based on feedback\n")
                            else:
                                self._reporter.log(
                                    "   ⚠️ Refinement returned None, keeping current CV\n"
                                )
                                break
                        else:
                            if review.needs_improvement:
                                self._reporter.log("   ℹ️ Max review iterations reached\n")
                            else:
                                self._reporter.log("   ✅ Quality check passed!\n")
                            break

                    except Exception as e:
                        self._reporter.log(
                            f"   ⚠️ Review failed: {e}, continuing with current CV\n"
                        )
                        break

                # --- STEP 3: AUDIT (Agent 3) ---
                self._set_stage("AUDITING_CV")
                new_cv_json = (
                    new_cv.model_dump_json()
                    if hasattr(new_cv, "model_dump_json")
                    else str(new_cv)
                )

                self._reporter.log(
                    "🤖 Agent 3 (Auditor): Validating for hallucinations and AI-speak..."
                )
                audit_prompt = f"""
ORIGINAL CV (structured):
{original_cv_json}

NEW GENERATED CV (structured):
{new_cv_json}

JOB REQUIREMENTS:
{job_data_json}

Compare the two structured CVs carefully. Ensure that:
1. No new skills appear in the new CV that weren't in the original
2. No new companies or roles were invented
3. All experiences in the new CV can be traced back to the original
4. The language is professional and not AI-generated sounding
5. The new CV properly targets the job requirements using only original information
"""
                try:
                    audit_result = await run_agent(
                        auditor_agent,
                        audit_prompt,
                        verbose=verbose,
                        agent_label="Auditor",
                        usage=total_usage,
                        usage_limits=USAGE_LIMITS,
                    )
                    audit = audit_result.output
                except UnexpectedModelBehavior:
                    if _auditor_qs.last_output is not None:
                        self._reporter.log(
                            "⚠️  Auditor quality gate exhausted — using best available output"
                        )
                        audit = _auditor_qs.last_output
                    else:
                        self._reporter.log(
                            "⚠️  Auditor quality gate exhausted with no fallback — skipping audit"
                        )
                        audit = None

                if audit is None:
                    self._reporter.log(
                        f"   ⚠️ Audit result is None on attempt {write_attempt + 1}"
                    )
                    self._complete_stage("AUDITING_CV", success=False)
                    if write_attempt < self.max_write_attempts - 1:
                        self._reporter.log("   🔄 Will retry...\n")
                        continue
                    else:
                        self._reporter.log("   ❌ Max attempts reached\n")
                        break

                audit_passed = getattr(audit, "passed", False)
                if audit_passed:
                    self._complete_stage("AUDITING_CV")
                    self._reporter.log(
                        f"   ✅ Audit passed on attempt {write_attempt + 1}!\n"
                    )
                    break  # exit loop — report phase runs below
                else:
                    self._reporter.log(f"   ⚠️ Audit failed on attempt {write_attempt + 1}")
                    if write_attempt < self.max_write_attempts - 1:
                        self._reporter.log("   🔄 Will retry with feedback...\n")
                    else:
                        self._complete_stage("AUDITING_CV", success=False)
                        self._reporter.log("   ❌ Max attempts reached\n")

            # Print audit report regardless of pass/fail
            self._reporter.log("\n" + "=" * 30)
            self._reporter.log("📋 FINAL AUDIT REPORT")
            self._reporter.log("=" * 30)

            if audit is None:
                self._reporter.log("⚠️ Warning: No audit result available")
            else:
                passed_display = getattr(audit, "passed", None)
                hallucination_score = getattr(audit, "hallucination_score", None)
                ai_cliche_score = getattr(audit, "ai_cliche_score", None)
                feedback_summary = getattr(audit, "feedback_summary", "")

                self._reporter.log(f"Passed: {passed_display}")
                self._reporter.log(
                    f"Hallucination Score (0 is best): {hallucination_score}"
                )
                self._reporter.log(f"AI Cliche Score (0 is best): {ai_cliche_score}")
                self._reporter.log(f"Feedback: {feedback_summary}")

                issues = getattr(audit, "issues", []) or []
                if issues:
                    self._reporter.log("\n⚠️ Issues Found:")
                    for i in issues:
                        sev = getattr(i, "severity", "Unknown")
                        issue_text = getattr(i, "issue", str(i))
                        suggestion = getattr(i, "suggestion", "")
                        self._reporter.log(f" - [{sev}] {issue_text} -> {suggestion}")

            # --- HOOK 1: interactive checkpoint on audit failure ---
            if not audit_passed:
                hook1_details: list[str] = []
                if audit:
                    hook1_details.append(f"Feedback: {audit.feedback_summary}")
                    hook1_details.append(f"Hallucination score: {audit.hallucination_score}/10")
                    hook1_details.append(f"AI cliché score: {audit.ai_cliche_score}/10")
                    for issue in (getattr(audit, "issues", []) or []):
                        sev = getattr(issue, "severity", "Unknown")
                        issue_text = getattr(issue, "issue", str(issue))
                        hook1_details.append(f"  [{sev}] {issue_text}")

                if feedback_attempts_remaining > 0:
                    hook1_choices = [
                        ("c", "Continue and save the audit-failed result"),
                        ("f", "Provide feedback/solution and retry once"),
                        ("q", "Quit without saving"),
                    ]
                else:
                    hook1_choices = [
                        ("c", "Continue and save the audit-failed result"),
                        ("q", "Quit without saving"),
                    ]

                action, feedback_text = self._human_checkpoint(
                    header="⚠️  CV Audit Failed — all retry attempts exhausted.",
                    details=hook1_details,
                    choices=hook1_choices,
                    default="c",
                )
                if action == "q":
                    raise UserAbortedError("User aborted after audit failure.")
                if action == "f":
                    user_feedback = feedback_text
                    feedback_attempts_remaining -= 1
                    self._reporter.log("🔄 Re-running write/audit cycle with your instructions...\n")
                    continue  # outer while loop — restarts write/audit + report

            # === REPORT PHASE — always runs ===
            final_report: FinalReport | None = None
            self._set_stage("GENERATING_REPORT")
            try:
                self._reporter.log(
                    "\n🤖 Agent 5 (Report Writer): Generating self-review report..."
                )

                cv_diff = (
                    compute_cv_diff(original_cv, new_cv) if new_cv is not None else CVDiff()
                )
                gap_analysis = compute_gap_analysis(
                    original_cv,
                    new_cv,
                    self._analyst_result.output
                    if self._analyst_result and self._analyst_result.output
                    else JobAnalysis(),
                )

                review_json = review.model_dump_json() if review is not None else "N/A"
                audit_json = audit.model_dump_json() if audit is not None else "N/A"

                report_prompt = f"""
CV Diff: {cv_diff.model_dump_json()}
Gap Analysis: {gap_analysis.model_dump_json()}
Audit Result: {audit_json}
Review Result: {review_json}
Job Analysis: {job_data_json}
"""

                report_result = await run_agent(
                    report_agent,
                    report_prompt,
                    verbose=verbose,
                    agent_label="Report",
                    usage=total_usage,
                    usage_limits=USAGE_LIMITS,
                )
                narrative = report_result.output

                final_report = FinalReport(
                    job_title=job_analysis.job_title,
                    company_name=job_analysis.company_name,
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    overall_recommendation=narrative.overall_recommendation,
                    match_score=narrative.match_score,
                    what_changed=cv_diff,
                    gaps=gap_analysis,
                    suggestions_to_strengthen=narrative.suggestions_to_strengthen,
                    audit_summary=narrative.audit_summary,
                    recommendation_rationale=narrative.recommendation_rationale,
                    passed=audit_passed,
                )

                # --- HOOK 2: interactive checkpoint on weak match ---
                if final_report.overall_recommendation == "Weak Match":
                    gap = final_report.gaps
                    total_kw = len(gap.covered_keywords) + len(gap.missing_keywords)
                    hook2_details = [
                        f"Match score: {final_report.match_score}/100",
                        f"Keyword coverage: {len(gap.covered_keywords)}/{total_kw} ({gap.keyword_coverage_percent:.1f}%)",
                    ]
                    if gap.missing_hard_skills:
                        hook2_details.append(f"Missing hard skills: {', '.join(gap.missing_hard_skills)}")
                    if gap.missing_soft_skills:
                        hook2_details.append(f"Missing soft skills: {', '.join(gap.missing_soft_skills)}")
                    if gap.missing_keywords:
                        hook2_details.append(f"Missing keywords: {', '.join(gap.missing_keywords)}")

                    if feedback_attempts_remaining > 0:
                        hook2_choices = [
                            ("c", "Continue and save anyway"),
                            ("f", "Provide feedback/solution and re-run tailoring once"),
                            ("q", "Quit without saving"),
                        ]
                    else:
                        hook2_choices = [
                            ("c", "Continue and save anyway"),
                            ("q", "Quit without saving"),
                        ]

                    action, feedback_text = self._human_checkpoint(
                        header="⚠️  Weak Match — the resume may not pass ATS screening for this role.",
                        details=hook2_details,
                        choices=hook2_choices,
                        default="c",
                    )
                    if action == "q":
                        raise UserAbortedError("User aborted after weak match.")
                    if action == "f":
                        user_feedback = feedback_text
                        feedback_attempts_remaining -= 1
                        self._reporter.log("🔄 Re-running write/audit cycle with your instructions...\n")
                        continue  # outer while loop

                self._complete_stage("GENERATING_REPORT")
                self._reporter.log("   ✅ Report generated.\n")

            except UserAbortedError:
                raise  # propagate quit/abort decisions, don't swallow them
            except Exception as e:
                self._complete_stage("GENERATING_REPORT", success=False)
                self._reporter.log(f"   ⚠️ Report generation failed: {e}\n")

            break  # exit feedback retry loop

        self._stage_status["GENERATING_REPORT"] = "done" if final_report else "failed"

        # Build audit_report dict for backward compatibility
        audit_report_dict: dict = {
            "passed": audit_passed,
            "hallucination_score": getattr(audit, "hallucination_score", None)
            if audit
            else None,
            "ai_cliche_score": getattr(audit, "ai_cliche_score", None)
            if audit
            else None,
            "feedback_summary": getattr(audit, "feedback_summary", "") if audit else "",
            "issues": [
                {
                    "severity": getattr(i, "severity", "Unknown"),
                    "issue": getattr(i, "issue", str(i)),
                    "suggestion": getattr(i, "suggestion", ""),
                }
                for i in (getattr(audit, "issues", []) or [])
            ],
        }

        return ResumeTailorResult(
            company_name=job_analysis.company_name,
            job_title=job_analysis.job_title,
            tailored_resume=(
                new_cv.model_dump_json()
                if new_cv and hasattr(new_cv, "model_dump_json")
                else str(new_cv)
                if new_cv
                else ""
            ),
            audit_report=audit_report_dict,
            passed=audit_passed,
            final_report=final_report,
        )
