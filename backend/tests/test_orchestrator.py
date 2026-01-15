from __future__ import annotations
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from backend.src.agent.orchestrator import Orchestrator
from backend.src.agent.models import (
    SessionState,
    ExecutionPlan,
    TaskStep,
    StepStatus,
    Agentmode,
)
from backend.src.agent.intent_router import IntentAnalysis, IntentType


@pytest.fixture
def mock_planner():
    planner = MagicMock()
    planner.create_plan = AsyncMock()
    return planner


@pytest.fixture
def mock_agent():
    agent = MagicMock()

    # Mock chat_stream as an async generator
    async def mock_stream(*args, **kwargs):
        yield "Step output chunk"

    agent.chat_stream = mock_stream
    agent.adapter = MagicMock()
    agent.adapter.log_debug = AsyncMock()
    return agent


@pytest.fixture
def mock_state_manager():
    sm = MagicMock()
    sm.load_state.return_value = None
    return sm


@pytest.fixture
def ui_callback():
    return AsyncMock()


@pytest.mark.asyncio
async def test_orchestrator_full_new_task_execution(
    mock_planner, mock_agent, mock_state_manager, ui_callback
):
    orchestrator = Orchestrator(
        mock_state_manager, mock_planner, mock_agent, ui_callback
    )

    # 1. Mock intent router result
    with patch.object(
        orchestrator.intent_router, "analyze", new_callable=AsyncMock
    ) as mock_analyze:
        mock_analyze.return_value = IntentAnalysis(
            original_prompt="Stwórz plik",
            refined_prompt="Create file",
            intent=IntentType.NEW_TASK,
            confidence=1.0,
            reasoning="test",
            show_plan_only=False,
        )

        # 2. Mock planner result
        mock_planner.create_plan.return_value = ExecutionPlan(
            original_request="Stwórz plik",
            refined_goal="Create file",
            steps=[
                TaskStep(
                    id="1", title="Init", description="Desc", mode=Agentmode.FAST_TOOL
                )
            ],
        )

        # 3. Trigger input
        await orchestrator.handle_user_input("Stwórz plik")

        # 4. Check results
        assert mock_planner.create_plan.called
        assert ui_callback.called

        # Verify plan was broadcasted
        plan_updates = [
            call for call in ui_callback.call_args_list if call.args[0] == "plan_update"
        ]
        assert len(plan_updates) > 0

        # Verify execution progress (broadcast_update is called multiple times)
        step_updates = [
            call for call in ui_callback.call_args_list if call.args[0] == "step_update"
        ]
        statuses = [c.args[1]["status"] for c in step_updates]
        assert "in_progress" in statuses
        assert "done" in statuses

        # Verify state persistence
        assert mock_state_manager.save_state.called


@pytest.mark.asyncio
async def test_orchestrator_pause_and_resume(
    mock_planner, mock_agent, mock_state_manager, ui_callback
):
    orchestrator = Orchestrator(
        mock_state_manager, mock_planner, mock_agent, ui_callback
    )

    # Setup a plan
    orchestrator.state.plan = ExecutionPlan(
        original_request="test",
        refined_goal="test",
        steps=[
            TaskStep(id="1", title="Step 1", description="1", status=StepStatus.DONE),
            TaskStep(
                id="2", title="Step 2", description="2", status=StepStatus.PENDING
            ),
        ],
    )
    orchestrator.state.is_paused = True

    # Resume
    # _execution_loop will run if is_paused becomes False
    orchestrator.state.is_paused = False
    await orchestrator._execution_loop()

    # Verify Step 2 was executed
    assert orchestrator.state.plan.steps[1].status == StepStatus.DONE
