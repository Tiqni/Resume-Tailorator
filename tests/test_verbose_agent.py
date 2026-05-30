"""Tests for run_agent(): emits reporter events and streams when wants_tokens."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent

from resume_tailorator.reporting.base import use_reporter
from resume_tailorator.workflows.agents import run_agent
from tests.reporting.test_base import RecordingReporter


class _AsyncIter:
    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


class TestRunAgentNonStreaming:
    @pytest.mark.anyio
    async def test_delegates_to_agent_run_when_reporter_wants_no_tokens(self):
        agent = MagicMock(spec=Agent)
        expected = MagicMock()
        agent.run = AsyncMock(return_value=expected)

        rec = RecordingReporter()  # wants_tokens = False
        with use_reporter(rec):
            result = await run_agent(agent, "prompt", agent_label="A")

        agent.run.assert_awaited_once()
        assert result is expected
        kinds = [e[0] for e in rec.events]
        assert kinds[0] == "agent_start"
        assert "agent_done" in kinds

    @pytest.mark.anyio
    async def test_passes_usage_params(self):
        agent = MagicMock(spec=Agent)
        agent.run = AsyncMock()
        with use_reporter(RecordingReporter()):
            await run_agent(agent, "test", agent_label="A", usage="u", usage_limits="ul")
        agent.run.assert_awaited_once_with("test", usage="u", usage_limits="ul")


class TestRunAgentStreaming:
    @pytest.mark.anyio
    async def test_emits_start_and_done_when_streaming(self):
        agent = MagicMock(spec=Agent)
        agent.run_stream_events = MagicMock(return_value=_AsyncIter([]))
        agent.run = AsyncMock(return_value=MagicMock())

        rec = RecordingReporter()
        rec.wants_tokens = True
        with use_reporter(rec):
            await run_agent(agent, "prompt", agent_label="Writer")

        agent.run_stream_events.assert_called_once_with(
            "prompt", usage=None, usage_limits=None
        )
        kinds = [e[0] for e in rec.events]
        assert kinds[0] == "agent_start"
        assert "agent_done" in kinds


class TestRunAgentFallback:
    @pytest.mark.anyio
    async def test_falls_back_on_stream_error(self):
        agent = MagicMock(spec=Agent)
        fallback = MagicMock()
        agent.run = AsyncMock(return_value=fallback)
        bad = MagicMock()
        bad.__aiter__ = MagicMock(side_effect=RuntimeError("boom"))
        agent.run_stream_events = MagicMock(return_value=bad)

        rec = RecordingReporter()
        rec.wants_tokens = True
        with use_reporter(rec):
            result = await run_agent(agent, "p", agent_label="Writer")

        assert result is fallback
        agent.run.assert_awaited_once()
