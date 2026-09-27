"""Run 状态机（FR-504）：合法流转与非法流转（SPEC 10 章流转表）。"""

import pytest

from app.domain.enums import RunState, transition_allowed


def test_running_transitions():
    assert transition_allowed(RunState.RUNNING, RunState.AWAITING_CONFIRM)
    assert transition_allowed(RunState.RUNNING, RunState.COMPLETED)
    assert transition_allowed(RunState.RUNNING, RunState.FAILED)
    assert not transition_allowed(RunState.RUNNING, RunState.SUPERSEDED)


def test_awaiting_confirm_transitions():
    assert transition_allowed(RunState.AWAITING_CONFIRM, RunState.COMPLETED)
    assert transition_allowed(RunState.AWAITING_CONFIRM, RunState.SUPERSEDED)
    assert not transition_allowed(RunState.AWAITING_CONFIRM, RunState.FAILED)
    assert not transition_allowed(RunState.AWAITING_CONFIRM, RunState.RUNNING)


def test_terminal_states_frozen():
    for terminal in (RunState.COMPLETED, RunState.FAILED, RunState.SUPERSEDED):
        for target in RunState:
            assert not transition_allowed(terminal, target)


def test_illegal_transition_raises_in_finalize():
    """repository.finalize_run 对非法流转抛错（用内存对象验证，无需 DB）。"""
    from app.memory.models import AgentRun
    from app.memory.repository import finalize_run

    run = AgentRun(
        conversation_id="u1001",
        state=RunState.COMPLETED.value,
        prompt_version="test",
    )

    async def _run():
        async def noop():  # session 参数占位
            pass

        await finalize_run(noop(), run, state=RunState.RUNNING)

    import asyncio

    with pytest.raises(ValueError, match="非法状态流转"):
        asyncio.run(_run())
