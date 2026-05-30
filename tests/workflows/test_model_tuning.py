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
