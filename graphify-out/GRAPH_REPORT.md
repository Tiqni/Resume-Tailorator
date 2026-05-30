# Graph Report - .  (2026-05-30)

## Corpus Check
- 55 files · ~70,916 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 862 nodes · 1849 edges · 56 communities (46 shown, 10 thin omitted)
- Extraction: 74% EXTRACTED · 26% INFERRED · 0% AMBIGUOUS · INFERRED: 474 edges (avg confidence: 0.53)
- Token cost: 178,223 input · 76,380 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Domain Models & Agent Results|Domain Models & Agent Results]]
- [[_COMMUNITY_Resume Output Converter & Tests|Resume Output Converter & Tests]]
- [[_COMMUNITY_AI Agent Roster|AI Agent Roster]]
- [[_COMMUNITY_MarkdownPDF Writers|Markdown/PDF Writers]]
- [[_COMMUNITY_Output Path Pattern Resolution|Output Path Pattern Resolution]]
- [[_COMMUNITY_Placeholder Detection Tests|Placeholder Detection Tests]]
- [[_COMMUNITY_Resume Input Converter & Tests|Resume Input Converter & Tests]]
- [[_COMMUNITY_CLI Typer Command Tests|CLI Typer Command Tests]]
- [[_COMMUNITY_CLI Workflow Orchestration|CLI Workflow Orchestration]]
- [[_COMMUNITY_Job Scraper Integration Tests|Job Scraper Integration Tests]]
- [[_COMMUNITY_Job Scraper Helper Tests|Job Scraper Helper Tests]]
- [[_COMMUNITY_Audit Result Handling|Audit Result Handling]]
- [[_COMMUNITY_CV Diff & Gap Analysis Tests|CV Diff & Gap Analysis Tests]]
- [[_COMMUNITY_Extraction Validation Tests|Extraction Validation Tests]]
- [[_COMMUNITY_Job Scraper Agent & Tools|Job Scraper Agent & Tools]]
- [[_COMMUNITY_Quality Gate Tests|Quality Gate Tests]]
- [[_COMMUNITY_Resume Format Conversion|Resume Format Conversion]]
- [[_COMMUNITY_CV Diff Data Models|CV Diff Data Models]]
- [[_COMMUNITY_Section Header Detection Tests|Section Header Detection Tests]]
- [[_COMMUNITY_Verbose Agent Streaming Tests|Verbose Agent Streaming Tests]]
- [[_COMMUNITY_CLI Argument & Env Var Tests|CLI Argument & Env Var Tests]]
- [[_COMMUNITY_URL Validation Tests|URL Validation Tests]]
- [[_COMMUNITY_Input Converter Protocol|Input Converter Protocol]]
- [[_COMMUNITY_Parsing Determinism Tests|Parsing Determinism Tests]]
- [[_COMMUNITY_Job Scraper Agent Tests|Job Scraper Agent Tests]]
- [[_COMMUNITY_Extraction Quality Scoring Tests|Extraction Quality Scoring Tests]]
- [[_COMMUNITY_Test Fixtures & Conftest|Test Fixtures & Conftest]]
- [[_COMMUNITY_Placeholder Detection in Scraping|Placeholder Detection in Scraping]]
- [[_COMMUNITY_ScrapedJobPosting Model Tests|ScrapedJobPosting Model Tests]]
- [[_COMMUNITY_Converter Registry Tests|Converter Registry Tests]]
- [[_COMMUNITY_Heading Normalization Tests|Heading Normalization Tests]]
- [[_COMMUNITY_Release Automation & CI|Release Automation & CI]]
- [[_COMMUNITY_Helper Integration Tests|Helper Integration Tests]]
- [[_COMMUNITY_Input Validation|Input Validation]]
- [[_COMMUNITY_HTML-to-Markdown Parsing|HTML-to-Markdown Parsing]]
- [[_COMMUNITY_Report Agent Integration Tests|Report Agent Integration Tests]]
- [[_COMMUNITY_Playwright MCP Tool|Playwright MCP Tool]]
- [[_COMMUNITY_Project Cover Banner|Project Cover Banner]]
- [[_COMMUNITY_Claude Plugin Settings|Claude Plugin Settings]]
- [[_COMMUNITY_Local Permissions Settings|Local Permissions Settings]]
- [[_COMMUNITY_Scraping Failure Handling|Scraping Failure Handling]]
- [[_COMMUNITY_Input Validation Helpers|Input Validation Helpers]]
- [[_COMMUNITY_Main Guard Test|Main Guard Test]]
- [[_COMMUNITY_JobContentDeps Model|JobContentDeps Model]]
- [[_COMMUNITY_Permissions Allowlist|Permissions Allowlist]]
- [[_COMMUNITY_DOCX Heading Plan|DOCX Heading Plan]]
- [[_COMMUNITY_CoverLetter Model|CoverLetter Model]]
- [[_COMMUNITY_html2text Parser|html2text Parser]]
- [[_COMMUNITY_Resume Auto-Detection|Resume Auto-Detection]]
- [[_COMMUNITY_Smoke Test Entry|Smoke Test Entry]]

## God Nodes (most connected - your core abstractions)
1. `CV` - 68 edges
2. `ResumeTailorResult` - 60 edges
3. `FinalReport` - 46 edges
4. `ScrapedJobPosting` - 42 edges
5. `WorkExperience` - 40 edges
6. `OutputConversionFailedError` - 31 edges
7. `JobAnalysis` - 31 edges
8. `detect_placeholder_content()` - 30 edges
9. `InputConverterRegistry` - 30 edges
10. `UnsupportedOutputFormatError` - 27 edges

## Surprising Connections (you probably didn't know these)
- `_tailor_impl()` --implements--> `Parsed CV Content-Addressed Cache`  [INFERRED]
  resume_tailorator/main.py → docs/superpowers/specs/2026-05-08-resume-parsing-determinism-design.md
- `_resolve_pattern()` --implements--> `Job-Specific Output Naming Design`  [INFERRED]
  resume_tailorator/main.py → docs/superpowers/specs/2026-05-06-job-specific-output-naming-design.md
- `_resolve_pattern()` --implements--> `Naming Template Variables`  [INFERRED]
  resume_tailorator/main.py → docs/superpowers/specs/2026-05-06-job-specific-output-naming-design.md
- `SubTests` --uses--> `FinalReport`  [INFERRED]
  tests/test_report_integration.py → resume_tailorator/models/agents/output.py
- `str` --uses--> `ScrapedJobPosting`  [INFERRED]
  tests/test_job_scraper.py → resume_tailorator/models/agents/output.py

## Hyperedges (group relationships)
- **Release Automation: spec + plan + CI/release workflows + changelog** — spec_release_automation, plan_release_automation, ci_yml_ci_workflow, release_yml_release_workflow, changelog_md [INFERRED 0.85]
- **Job-Specific Output Naming pipeline** — main__tailor_impl, main__run_workflow, main__resolve_pattern, main__slugify, spec_job_specific_output_naming [INFERRED 0.85]
- **Resume Parsing Determinism: cache + spec + memory** — spec_resume_parsing_determinism, spec_parsed_cv_cache, main__tailor_impl, readme_resume_memory [INFERRED 0.75]
- **Quality Gate Validator Pattern** — agents_validate_resume_parser, agents_validate_auditor, agents_validate_writer, agents_validate_analyst, agents_validate_cover_letter_writer, agents_quality_gate_agent, agents_run_agent [INFERRED 0.85]
- **Input Converter Registry Dispatch** — resume_converter_inputconverterregistry, resume_converter_docxinputconverter, resume_converter_pdfinputconverter, resume_converter_resumeconverterprotocol [INFERRED 0.85]
- **Output Converter Registry Dispatch** — resume_output_converter_outputconverterregistry, resume_output_converter_markdownoutputconverter, resume_output_converter_pdfoutputconverter, resume_output_converter_docxoutputconverter [INFERRED 0.85]
- **Resume tailoring agent pipeline exercised by workflow test** — workflows_agents_resume_parser_agent, workflows_agents_analyst_agent, workflows_agents_writer_agent, workflows_agents_reviewer_agent, workflows_agents_auditor_agent [INFERRED 0.85]
- **CLI tailor command mocked collaborators** — main_app, workflows_resume_tailor_workflow, workflows_agents_job_scraper_agent, main_generate_resume [INFERRED 0.75]
- **CV diff and gap analysis over CV and JobAnalysis models** — cv_diff_compute_gap_analysis, output_cv, output_jobanalysis [INFERRED 0.75]

## Communities (56 total, 10 thin omitted)

### Community 0 - "Domain Models & Agent Results"
Cohesion: 0.07
Nodes (70): Agent, AgentRunResult, JobContentDeps, AuditResult, CoverLetter, CV, FinalReport, JobAnalysis (+62 more)

### Community 1 - "Resume Output Converter & Tests"
Cohesion: 0.08
Nodes (26): Path, ResumeTailorResult, str, TestBuildResumeMarkdown, TestDocxOutputConverter, TestMarkdownOutputConverter, TestOutputConverterRegistry, TestPdfOutputConverter (+18 more)

### Community 2 - "AI Agent Roster"
Cohesion: 0.06
Nodes (46): analyst_agent, auditor_agent, cover_letter_writer_agent, quality_gate_agent, _QualityState, report_agent, resume_parser_agent, reviewer_agent (+38 more)

### Community 3 - "Markdown/PDF Writers"
Cohesion: 0.10
Nodes (38): ResumeTailorResult, ResolvedOriginalResume, FinalReport, ResumeTailorResult, str, str, ResumeSourceRecord, _make_cv() (+30 more)

### Community 4 - "Output Path Pattern Resolution"
Cohesion: 0.10
Nodes (15): _is_safe_path_component(), Convert text to a filesystem-safe slug., Replace template variables with slugified values from result and CV., Reject path components that could escape the intended directory., _resolve_pattern(), _slugify(), _make_cv(), _make_result() (+7 more)

### Community 5 - "Placeholder Detection Tests"
Cohesion: 0.08
Nodes (21): bool, Real job posting 2 should not be flagged as placeholder., Uppercase 'CLICK HERE' should be detected as placeholder., Mixed case 'Click Here' should be detected as placeholder., Uppercase 'ERROR LOADING' should be detected as placeholder., Short text with leading/trailing whitespace should be placeholder., Short text with newlines should be placeholder., Tests for detect_placeholder_content function. (+13 more)

### Community 6 - "Resume Input Converter & Tests"
Cohesion: 0.12
Nodes (17): TestAutoDetectResume, TestDocxInputConverter, TestExceptionHierarchy, TestPdfInputConverter, auto_detect_resume(), DocxInputConverter, NoResumeFileFoundError, PdfInputConverter (+9 more)

### Community 7 - "CLI Typer Command Tests"
Cohesion: 0.08
Nodes (33): ScrapedJobPosting, _make_cv(), _make_scraped_job(), str, Tests for CLI with Typer - tailor and re-tailor commands., tailor command with invalid URL format should return 1., tailor command with non-existent resume should return 1., tailor command with failed audit should exit 0 (report still generated). (+25 more)

### Community 8 - "CLI Workflow Orchestration"
Cohesion: 0.08
Nodes (27): Agents Roster (workflows/agents.py), Technology Stack, GitHub Copilot Instructions, _audit_result_from_dict(), _print_report_to_console(), _re_tailor_impl(), _resolve_pattern(), _run_workflow() (+19 more)

### Community 9 - "Job Scraper Integration Tests"
Cohesion: 0.07
Nodes (29): mock_scraper(), mock_workflow(), End-to-end integration tests for job scraper workflow.  Tests verify the full pi, Provide a mock workflow., Provide a mock job scraper agent., Test that CLI --job-url triggers scraper before workflow., Test that missing job URL skips scraper., Test that workflow completes successfully with scraped job. (+21 more)

### Community 10 - "Job Scraper Helper Tests"
Cohesion: 0.09
Nodes (17): Tests for job_scraper_helpers module.  Tests for placeholder detection, HTML par, Tests for clean_job_posting_markdown function., Empty string should return empty string., None input should return empty string., Three newlines should collapse to two., Multiple groups of blank lines should each collapse to two., Trailing spaces should be removed from single line., Trailing spaces should be removed from all lines. (+9 more)

### Community 11 - "Audit Result Handling"
Cohesion: 0.19
Nodes (29): AuditIssue, _audit_result_from_dict(), _get_company_slug(), _get_job_fingerprint(), _print_report_to_console(), AuditResult, bool, CV (+21 more)

### Community 12 - "CV Diff & Gap Analysis Tests"
Cohesion: 0.17
Nodes (26): job_analysis(), original_cv(), CV, JobAnalysis, Unit tests for compute_cv_diff and compute_gap_analysis.  These are pure-Python, When writer fails (new_cv is None), coverage defaults to 0%., A tailored version: summary changed, skills reordered, one bullet rephrased., tailored_cv() (+18 more)

### Community 13 - "Extraction Validation Tests"
Cohesion: 0.11
Nodes (15): str, Tests for validate_extraction tool., Test that valid extraction passes validation., Test that quality score is always in valid range., Test that extraction with minimum valid length passes., Test that missing HTML triggers ModelRetry., Test that missing markdown triggers ModelRetry., Test that placeholder content triggers ModelRetry. (+7 more)

### Community 14 - "Job Scraper Agent & Tools"
Cohesion: 0.12
Nodes (23): build_scraper_instructions, fetch_webpage, job_scraper_agent, validate_extraction, clean_job_posting_markdown, detect_placeholder_content, parse_html_with_markitdown, app (+15 more)

### Community 15 - "Quality Gate Tests"
Cohesion: 0.09
Nodes (11): Tests for per-agent quality gate validators., Verify workflow saves output when quality gate retries trigger ModelRetry., Verify quality gate validator saves last_output before exhausting retries., Verify _QualityState singletons are importable from workflows.agents., Verify _QualityState can store and retrieve CV objects., Reset all _QualityState singletons before and after each test., reset_quality_states(), test_quality_state_accepts_cv_assignment() (+3 more)

### Community 16 - "Resume Format Conversion"
Cohesion: 0.15
Nodes (17): generate_resume, markdown_to_pdf, DocxInputConverter, InputConverterRegistry, _is_section_header, _normalize_markdown_headings, OutputConversionFailedError, PdfInputConverter (+9 more)

### Community 17 - "CV Diff Data Models"
Cohesion: 0.25
Nodes (15): CVDiff, ExperienceChange, GapAnalysis, Gap analysis between job requirements and the original CV., Tracks changes made to a single experience entry., Factual diff between the original CV and the tailored CV., CVDiff, GapAnalysis (+7 more)

### Community 18 - "Section Header Detection Tests"
Cohesion: 0.23
Nodes (4): bool, TestIsSectionHeader, _is_section_header(), True if *line* looks like a section header (all caps, no markdown formatting).

### Community 19 - "Verbose Agent Streaming Tests"
Cohesion: 0.14
Nodes (7): _AsyncIter, Tests for run_agent() verbose streaming helper., Minimal async iterator for mocking stream_text() output., When verbose=False, run_agent delegates directly to agent.run()., When verbose=True, run_agent uses run_stream_events and prints to console., TestRunAgentNonVerbose, TestRunAgentVerbose

### Community 20 - "CLI Argument & Env Var Tests"
Cohesion: 0.14
Nodes (8): Tests for CLI argument and environment variable handling., Test that CLI correctly parses --job-url argument., Test that job_url is None when not provided., Test that CLI handles complex URLs with query parameters., Test that JOB_URL environment variable is used as fallback., Test that CLI argument takes precedence over environment variable., Test that job_url defaults to None when env var not set., TestCLIIntegration

### Community 21 - "URL Validation Tests"
Cohesion: 0.14
Nodes (8): Tests for URL validation in fetch_webpage tool., Test that valid HTTPS URL format is recognized., Test that valid HTTP URL format is recognized., Test that URL without protocol is invalid., Test that URL with wrong protocol is invalid., Test that empty URL string is invalid., Test that None URL would raise error., TestURLValidation

### Community 22 - "Input Converter Protocol"
Cohesion: 0.23
Nodes (9): Protocol, Path, str, EmptyConversionResultError, Return converter for extension. Raises UnsupportedFormatError if unknown., Convert input_path and write Markdown to output_path. Returns Markdown string., Raised when conversion produces empty/whitespace output., Return markdown string from input file. (+1 more)

### Community 23 - "Parsing Determinism Tests"
Cohesion: 0.15
Nodes (12): Tests for deterministic resume parsing via pre-parsed CV cache., run() has pre_parsed_cv and debug parameters with correct defaults., A pre-parsed CV should faithfully carry its data., _tailor_impl signature includes debug param., _re_tailor_impl signature includes debug param., _run_workflow passes pre_parsed_cv and debug through., sample_pre_parsed_cv(), test_pre_parsed_cv_preserves_skills() (+4 more)

### Community 24 - "Job Scraper Agent Tests"
Cohesion: 0.17
Nodes (7): Tests for job scraper agent and integration.  Comprehensive tests for JobScraper, Tests for JobScraperAgent., Test successful job posting scraping with TestModel.          Verifies that the, Test that scraped markdown content is substantial., Test that the original URL is preserved in the output., Test that extraction strategy field is properly populated., TestJobScraperAgent

### Community 25 - "Extraction Quality Scoring Tests"
Cohesion: 0.17
Nodes (7): Tests for quality scoring in validate_extraction., Test quality score for minimum valid content (200 chars)., Test quality score for moderate content (1000 chars)., Test quality score for substantial content (5000 chars)., Test that quality score caps at 100., Test that quality score considers total length including whitespace., TestExtractionQualityScoring

### Community 26 - "Test Fixtures & Conftest"
Cohesion: 0.27
Nodes (10): WorkExperience, anyio_backend(), Path, str, Restrict anyio tests to asyncio backend (trio is not installed)., sample_cv(), sample_docx(), sample_pdf() (+2 more)

### Community 27 - "Placeholder Detection in Scraping"
Cohesion: 0.20
Nodes (6): Tests for placeholder detection edge cases in scraping context., Test that error pages are detected as placeholders., Test that 'click here' content is detected as placeholder., Test that real job posting mentioning JavaScript is not flagged., Test boundary of minimum content length., TestPlaceholderDetectionInScraping

### Community 28 - "ScrapedJobPosting Model Tests"
Cohesion: 0.20
Nodes (6): Tests for ScrapedJobPosting data model., Test creating ScrapedJobPosting with all fields., Test that URL field accepts valid URLs., Test that markdown field stores formatted content., Test different extraction strategy values., TestScrapedJobPostingModel

### Community 29 - "Converter Registry Tests"
Cohesion: 0.36
Nodes (3): TestInputConverterRegistry, InputConverterRegistry, Maps file extensions to their converter implementations.

### Community 30 - "Heading Normalization Tests"
Cohesion: 0.33
Nodes (3): TestNormalizeMarkdownHeadings, _normalize_markdown_headings(), Convert all-caps section header lines to markdown H2 headings.      A line is pr

### Community 31 - "Release Automation & CI"
Cohesion: 0.32
Nodes (7): CI Workflow, Release Automation Plan, bump job (PR-based release), Release Workflow, tag-and-release job, Commitizen Configuration, Release Automation Design

### Community 32 - "Helper Integration Tests"
Cohesion: 0.25
Nodes (5): Integration tests for helper functions used in scraping., Test that placeholder detection integrates properly., Test that markdown cleaning integrates properly., Test that HTML parsing integrates properly., TestHelperFunctionsIntegration

### Community 33 - "Input Validation"
Cohesion: 0.38
Nodes (6): Test that invalid URLs are rejected early., test_invalid_job_url_handled_gracefully(), main(), Validate job URL format.      Args:         job_url: The URL to validate.      R, validate_file(), validate_job_url()

### Community 34 - "HTML-to-Markdown Parsing"
Cohesion: 0.33
Nodes (6): str, parse_html_with_html2text(), parse_html_with_markitdown(), Job scraper helper utilities for parsing and validation.  This module provides p, Parse HTML to markdown using markitdown library.      Attempts to extract body c, Parse HTML to markdown using html2text library.      Configures html2text to pre

### Community 35 - "Report Agent Integration Tests"
Cohesion: 0.29
Nodes (6): SubTests, Integration tests for report_agent using TestModel (no real LLM calls)., report_agent should return a FinalReport when given valid JSON context., FinalReport output must contain all expected fields., test_report_agent_output_has_required_fields(), test_report_agent_returns_final_report()

### Community 36 - "Playwright MCP Tool"
Cohesion: 0.40
Nodes (4): RunContext, str, MCP Tool: Navigates to a URL and extracts the main text content as Markdown., read_job_content_file()

### Community 37 - "Project Cover Banner"
Cohesion: 0.83
Nodes (4): Resume Tailorator Cover Banner, AI Agents, Resume Tailorator (Project), Resume Tailoring per Job

### Community 40 - "Scraping Failure Handling"
Cohesion: 0.67
Nodes (3): Exception, tailor command when scraping fails should return 1., test_tailor_command_scraping_failure()

### Community 41 - "Input Validation Helpers"
Cohesion: 0.67
Nodes (3): validate_inputs.main, validate_file, validate_job_url

## Knowledge Gaps
- **48 isolated node(s):** `superpowers@claude-plugins-official`, `allow`, `RunContext`, `str`, `bool` (+43 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ScrapedJobPosting` connect `Domain Models & Agent Results` to `Helper Integration Tests`, `CLI Typer Command Tests`, `Job Scraper Integration Tests`, `Audit Result Handling`, `Extraction Validation Tests`, `CV Diff Data Models`, `CLI Argument & Env Var Tests`, `URL Validation Tests`, `Job Scraper Agent Tests`, `Extraction Quality Scoring Tests`, `Placeholder Detection in Scraping`, `ScrapedJobPosting Model Tests`?**
  _High betweenness centrality (0.228) - this node is a cross-community bridge._
- **Why does `validate_extraction()` connect `Job Scraper Agent & Tools` to `Domain Models & Agent Results`, `Job Scraper Agent Tests`, `Placeholder Detection Tests`?**
  _High betweenness centrality (0.189) - this node is a cross-community bridge._
- **Why does `CV` connect `Domain Models & Agent Results` to `Markdown/PDF Writers`, `Output Path Pattern Resolution`, `CLI Typer Command Tests`, `Job Scraper Integration Tests`, `Audit Result Handling`, `CV Diff & Gap Analysis Tests`, `Quality Gate Tests`, `CV Diff Data Models`, `Parsing Determinism Tests`, `Test Fixtures & Conftest`?**
  _High betweenness centrality (0.186) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `CV` (e.g. with `Agent` and `AgentRunResult`) actually correct?**
  _`CV` has 49 INFERRED edges - model-reasoned connections that need verification._
- **Are the 46 inferred relationships involving `ResumeTailorResult` (e.g. with `FinalReport` and `ResolvedOriginalResume`) actually correct?**
  _`ResumeTailorResult` has 46 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `FinalReport` (e.g. with `Agent` and `AgentRunResult`) actually correct?**
  _`FinalReport` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `ScrapedJobPosting` (e.g. with `Agent` and `AgentRunResult`) actually correct?**
  _`ScrapedJobPosting` has 33 INFERRED edges - model-reasoned connections that need verification._