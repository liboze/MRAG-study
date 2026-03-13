"""Tests for agent/core/planner.py — using a mock LLM."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent.core.memory_manager import MemoryManager
from agent.core.planner import Planner


@pytest.fixture
def mm(tmp_path):
    cfg = {
        "memory_file": str(tmp_path / "memory.md"),
        "tasks_file": str(tmp_path / "tasks.md"),
        "skills_registry": str(tmp_path / "skills.md"),
        "paper_draft_file": str(tmp_path / "paper_draft.md"),
    }
    return MemoryManager(cfg)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    return llm


def test_decompose_goal_returns_tasks(mm, mock_llm):
    tasks = [
        {"title": "Survey literature", "status": "todo", "priority": 1, "depends_on": [], "owner": "agent", "next_action": "Search arXiv"},
        {"title": "Collect datasets", "status": "todo", "priority": 2, "depends_on": [], "owner": "agent", "next_action": "Search datasets"},
    ]
    mock_llm.chat.return_value = json.dumps(tasks)
    planner = Planner(mock_llm, mm)
    result = planner.decompose_goal("Study RAG for QA")
    assert len(result) == 2
    assert result[0]["title"] == "Survey literature"
    # Goal should be in memory
    assert "Study RAG for QA" in mm.get_memory("研究目标")


def test_decompose_goal_handles_invalid_json(mm, mock_llm):
    mock_llm.chat.return_value = "not json"
    planner = Planner(mock_llm, mm)
    result = planner.decompose_goal("Some goal")
    assert result == []


def test_decompose_goal_empty_string(mm, mock_llm):
    mock_llm.chat.return_value = "[]"
    planner = Planner(mock_llm, mm)
    result = planner.decompose_goal("")
    assert result == []


def test_pick_next_task_returns_selection(mm, mock_llm):
    mm.add_task({"title": "Task A", "status": "todo"})
    mock_llm.chat.return_value = json.dumps({"title": "Task A", "reason": "Highest priority"})
    planner = Planner(mock_llm, mm)
    result = planner.pick_next_task()
    assert result is not None
    assert result["title"] == "Task A"


def test_pick_next_task_no_tasks(mm, mock_llm):
    planner = Planner(mock_llm, mm)
    result = planner.pick_next_task()
    assert result is None


def test_add_task(mm, mock_llm):
    planner = Planner(mock_llm, mm)
    planner.add_task("New task", "Description", status="new")
    new_tasks = mm.get_tasks_by_status("new")
    assert "New task" in new_tasks


def test_mark_done(mm, mock_llm):
    mm.add_task({"title": "Task X", "status": "todo"})
    planner = Planner(mock_llm, mm)
    planner.mark_done("Task X", notes="Done!")
    done = mm.get_tasks_by_status("done")
    assert "Task X" in done


def test_mark_blocked(mm, mock_llm):
    mm.add_task({"title": "Task Y", "status": "todo"})
    planner = Planner(mock_llm, mm)
    planner.mark_blocked("Task Y", reason="Waiting for data")
    blocked = mm.get_tasks_by_status("blocked")
    assert "Task Y" in blocked
