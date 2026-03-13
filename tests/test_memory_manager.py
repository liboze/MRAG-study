"""Tests for agent/core/memory_manager.py"""

from __future__ import annotations

import os
import pytest

from agent.core.memory_manager import MemoryManager


@pytest.fixture
def mm(tmp_path):
    cfg = {
        "memory_file": str(tmp_path / "memory.md"),
        "tasks_file": str(tmp_path / "tasks.md"),
        "skills_registry": str(tmp_path / "skills.md"),
        "paper_draft_file": str(tmp_path / "paper_draft.md"),
    }
    return MemoryManager(cfg)


# ── Initialisation ─────────────────────────────────────────────────────────────

def test_state_files_created(tmp_path):
    cfg = {
        "memory_file": str(tmp_path / "memory.md"),
        "tasks_file": str(tmp_path / "tasks.md"),
        "skills_registry": str(tmp_path / "skills.md"),
        "paper_draft_file": str(tmp_path / "paper_draft.md"),
    }
    mm = MemoryManager(cfg)
    for key in ("memory_file", "tasks_file", "skills_registry", "paper_draft_file"):
        assert os.path.exists(cfg[key]), f"{key} not created"


# ── Memory ─────────────────────────────────────────────────────────────────────

def test_update_and_get_memory(mm):
    mm.update_memory("研究目标", "Test the agent system")
    content = mm.get_memory("研究目标")
    assert "Test the agent system" in content


def test_append_memory(mm):
    mm.update_memory("Notes", "Note 1")
    mm.append_memory("Notes", "Note 2")
    content = mm.get_memory("Notes")
    assert "Note 1" in content
    assert "Note 2" in content


def test_add_memory_note(mm):
    mm.add_memory_note("This is a note", section="Notes")
    content = mm.get_memory("Notes")
    assert "This is a note" in content


# ── Tasks ──────────────────────────────────────────────────────────────────────

def test_add_task(mm):
    mm.add_task({"title": "Test task", "status": "todo", "description": "A test"})
    tasks = mm.get_tasks_by_status("todo")
    assert "Test task" in tasks


def test_update_task_status(mm):
    mm.add_task({"title": "My task", "status": "todo"})
    mm.update_task_status("My task", "done", notes="Completed successfully")
    done = mm.get_tasks_by_status("done")
    assert "My task" in done
    todo = mm.get_tasks_by_status("todo")
    assert "My task" not in todo


def test_get_all_tasks(mm):
    mm.add_task({"title": "TaskA", "status": "todo"})
    mm.add_task({"title": "TaskB", "status": "done"})
    all_tasks = mm.get_all_tasks()
    assert "TaskA" in all_tasks
    assert "TaskB" in all_tasks


# ── Skills ─────────────────────────────────────────────────────────────────────

def test_register_skill(mm):
    mm.register_skill({
        "name": "test_skill",
        "description": "Does something useful",
        "inputs": "x: int",
        "outputs": "int",
        "use_cases": "Testing",
        "call_signature": "test_skill(x)",
        "dependencies": "none",
        "file_path": "skills/test_skill.py",
    })
    skills = mm.get_skills()
    assert "test_skill" in skills


def test_find_skill(mm):
    mm.register_skill({
        "name": "arxiv_parser",
        "description": "Parse arXiv XML",
        "inputs": "xml: str",
        "outputs": "list",
        "use_cases": "Literature search",
        "call_signature": "arxiv_parser(xml)",
        "dependencies": "none",
        "file_path": "skills/arxiv_parser.py",
    })
    result = mm.find_skill("arxiv")
    assert "arxiv_parser" in result


# ── Paper draft ────────────────────────────────────────────────────────────────

def test_update_paper_section(mm):
    mm.update_paper_section("摘要", "This paper studies X.")
    draft = mm.get_paper_draft()
    assert "This paper studies X." in draft


def test_append_paper_section(mm):
    mm.update_paper_section("相关工作", "Section A.")
    mm.append_paper_section("相关工作", "Section B.")
    draft = mm.get_paper_draft()
    assert "Section A." in draft
    assert "Section B." in draft
