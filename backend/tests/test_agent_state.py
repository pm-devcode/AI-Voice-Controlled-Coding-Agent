from __future__ import annotations
import pytest
import tempfile
import shutil
from pathlib import Path
from backend.src.agent.session_memory import SessionMemoryManager
from backend.src.agent.state_manager import StateManager
from backend.src.agent.models import SessionState, ExecutionPlan


@pytest.fixture
def temp_workspace():
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir)


def test_session_memory_persistence(temp_workspace):
    manager = SessionMemoryManager(str(temp_workspace))
    memory = manager.load()

    # Check if we can add patterns (assuming method exists or we use internal memory)
    # The record_successful_edit method was seen in file_ops.py but let's check session_memory.py
    # From read_file of session_memory.py it has EditPattern and SessionMemory.

    from backend.src.agent.session_memory import EditPattern

    memory.edit_patterns.append(
        EditPattern(file_pattern="*.py", action="test", context="ctx")
    )

    manager.save()

    # Check if file exists
    memory_file = temp_workspace / ".vcca" / "session_memory.json"
    assert memory_file.exists()

    # Load in new manager
    new_manager = SessionMemoryManager(str(temp_workspace))
    new_memory = new_manager.load()
    assert len(new_memory.edit_patterns) == 1
    assert new_memory.edit_patterns[0].action == "test"


from unittest.mock import MagicMock


def test_state_manager_persistence(temp_workspace):
    manager = StateManager(str(temp_workspace))

    state = SessionState(
        interaction_id="123",
        plan=ExecutionPlan(original_request="test", refined_goal="test", steps=[]),
    )

    manager.save_state(state)
    assert (temp_workspace / ".vcca" / ".cache" / "session_state.json").exists()

    loaded = manager.load_state()
    assert loaded is not None
    assert loaded.interaction_id == "123"
