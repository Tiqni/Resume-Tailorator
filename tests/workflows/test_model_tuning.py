"""Per-agent model tuning: run_agent passes the resolved model."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent

import resume_tailorator.workflows.agents as agents_mod
from resume_tailorator.reporting.base import use_reporter
from resume_tailorator.workflows.agents import resolve_model, run_agent
from tests.reporting.test_base import RecordingReporter


def test_resolve_model_none_when_unconfigured():
    agents_mod.reset_agent_models()
    assert resolve_model("Parser") is None


def test_resolve_model_uses_tiers_when_configured():
    agents_mod.set_agent_models(fast="openai:gpt-5-nano", strong="openai:gpt-5")
    try:
        assert resolve_model("Parser") == "openai:gpt-5-nano"
        assert resolve_model("Writer") == "openai:gpt-5"
        assert resolve_model("Unknown") == "openai:gpt-5"  # default tier strong
    finally:
        agents_mod.reset_agent_models()


@pytest.mark.anyio
async def test_run_agent_passes_resolved_model():
    agents_mod.set_agent_models(fast="openai:gpt-5-nano", strong="openai:gpt-5")
    try:
        agent = MagicMock(spec=Agent)
        agent.run = AsyncMock(return_value=MagicMock())
        with use_reporter(RecordingReporter()):
            await run_agent(agent, "p", agent_label="Parser")
        _, kwargs = agent.run.call_args
        assert kwargs["model"] == "openai:gpt-5-nano"
    finally:
        agents_mod.reset_agent_models()


@pytest.mark.anyio
async def test_explicit_model_overrides_resolution():
    agent = MagicMock(spec=Agent)
    agent.run = AsyncMock(return_value=MagicMock())
    with use_reporter(RecordingReporter()):
        await run_agent(agent, "p", agent_label="Parser", model="openai:custom")
    _, kwargs = agent.run.call_args
    assert kwargs["model"] == "openai:custom"


def test_set_model_alone_does_not_mispin_agents():
    """--model changes MODEL_NAME but, without tier config, must NOT pin agents
    to a stale tier model (regression test)."""
    agents_mod.set_model("openai:gpt-4o")
    try:
        # tiers untouched → still unconfigured → no spurious override
        assert agents_mod.resolve_model("Writer") is None
        assert agents_mod.resolve_model("Parser") is None
    finally:
        agents_mod.reset_model()
        agents_mod.reset_agent_models()


def test_model_override_via_tiers_applies_to_all_agents():
    """Routing an explicit model through both tiers overrides every agent."""
    agents_mod.set_agent_models(fast="openai:gpt-4o", strong="openai:gpt-4o")
    try:
        assert agents_mod.resolve_model("Parser") == "openai:gpt-4o"
        assert agents_mod.resolve_model("Writer") == "openai:gpt-4o"
        assert agents_mod.resolve_model("Auditor") == "openai:gpt-4o"
    finally:
        agents_mod.reset_agent_models()


def test_agent_models_configured_reflects_tier_state():
    """The guard that protects --fast tiers from a bare --model override.

    _run_impl only force-pins every tier to the override model when tiers are
    still unconfigured; once --fast has set distinct tiers this returns True so
    the mechanical agents keep their fast tier.
    """
    agents_mod.reset_agent_models()
    assert agents_mod.agent_models_configured() is False
    agents_mod.set_agent_models(fast="openai:gpt-5-nano", strong="openai:gpt-5-mini")
    try:
        assert agents_mod.agent_models_configured() is True
    finally:
        agents_mod.reset_agent_models()
    assert agents_mod.agent_models_configured() is False


def test_default_model_builds_without_openai_key(monkeypatch):
    """Regression: constructing the agents must not require OPENAI_API_KEY.

    pydantic-ai builds the provider client eagerly when a model *string* is given
    to Agent(...), which crashed `import` for users running --model=ollama:...
    with no OpenAI key. _build_default_model must succeed (with a placeholder) and
    still yield a *defined* model so Agent.override / per-run overrides work.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model = agents_mod._build_default_model()
    assert model is not None
    assert getattr(model, "model_name", None) == "gpt-5-mini"


def test_agents_carry_a_defined_default_model():
    """Every agent needs a defined base model: override() refuses to mask a
    missing model, and the unconfigured run path falls back to it."""
    assert agents_mod.quality_gate_agent.model is not None
    assert agents_mod.job_scraper_agent.model is not None


def test_apply_model_override_pins_all_tiers():
    """--model must reach every stage — including the scraper/parser that run
    before the workflow — by pinning both tiers."""
    agents_mod.reset_model()
    agents_mod.reset_agent_models()
    try:
        agents_mod.apply_model_override("ollama:kimi-k2.6:cloud")
        for label in ("Scraper", "Parser", "Writer", "Auditor", "Quality Gate"):
            assert agents_mod.resolve_model(label) == "ollama:kimi-k2.6:cloud"
    finally:
        agents_mod.reset_model()
        agents_mod.reset_agent_models()


def test_apply_model_override_preserves_fast_tiers():
    """A bare --model after --fast must keep the distinct fast/strong tiers."""
    agents_mod.reset_model()
    agents_mod.reset_agent_models()
    agents_mod.set_agent_models(fast="openai:gpt-5-nano", strong="openai:gpt-5-mini")
    try:
        agents_mod.apply_model_override("ollama:kimi-k2.6:cloud")
        assert agents_mod.resolve_model("Parser") == "openai:gpt-5-nano"
        assert agents_mod.resolve_model("Writer") == "openai:gpt-5-mini"
    finally:
        agents_mod.reset_model()
        agents_mod.reset_agent_models()


def test_apply_model_override_noop_on_falsy():
    """No --model given → tiers stay unconfigured (agents use their own default)."""
    agents_mod.reset_model()
    agents_mod.reset_agent_models()
    agents_mod.apply_model_override(None)
    assert agents_mod.resolve_model("Parser") is None
    agents_mod.apply_model_override("")
    assert agents_mod.resolve_model("Parser") is None
