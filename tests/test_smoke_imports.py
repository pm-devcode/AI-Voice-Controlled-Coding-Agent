
import pytest
import sys
import os

# Ensure backend modules can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_imports():
    """Test that key modules import without syntax errors."""
    from backend.src.agent.planner import PlannerAgent
    from backend.src.agent.orchestrator import Orchestrator
    from backend.src.agent.state_manager import StateManager
    from backend.src.api.websocket import websocket_endpoint
    assert True

@pytest.mark.asyncio
async def test_planner_instantiation():
    """Test that PlannerAgent can be instantiated."""
    try:
        from backend.src.agent.planner import PlannerAgent
        agent = PlannerAgent()
        assert agent is not None
    except Exception as e:
        pytest.fail(f"Failed to instantiate PlannerAgent: {e}")

@pytest.mark.asyncio
async def test_models_import():
     """Test that pydantic models are valid."""
     from backend.src.agent.models import ExecutionPlan, TaskStep
     step = TaskStep(id="1", title="test", description="desc")
     plan = ExecutionPlan(
         original_request="req",
         refined_goal="goal",
         steps=[step]
     )
     assert plan.steps[0].title == "test"
