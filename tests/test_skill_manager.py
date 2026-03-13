"""Tests for agent/modules/skill_manager.py"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from agent.core.memory_manager import MemoryManager
from agent.modules.skill_manager import SkillManager


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
def skill_mgr(tmp_path, mm):
    llm = MagicMock()
    cfg = {"skills_dir": str(tmp_path / "skills"), "skills_registry": str(tmp_path / "skills.md")}
    return SkillManager(llm, mm, cfg), llm, tmp_path


def test_generate_skill_creates_file(skill_mgr):
    sm, llm, tmp_path = skill_mgr
    llm.chat.return_value = (
        "def add_numbers(a: int, b: int) -> int:\n"
        '    """Add two numbers."""\n'
        "    return a + b\n"
    )
    path = sm.generate_skill(
        name="add_numbers",
        description="Add two integers",
        inputs="a: int, b: int",
        outputs="int",
        use_cases="Arithmetic",
    )
    assert os.path.exists(path)
    content = open(path).read()
    assert "def add_numbers" in content


def test_generate_skill_registered_in_memory(skill_mgr):
    sm, llm, tmp_path = skill_mgr
    llm.chat.return_value = "def my_skill(x):\n    return x\n"
    sm.generate_skill("my_skill", "Test skill", "x", "x", "testing")
    skills_md = sm.list_skills()
    assert "my_skill" in skills_md


def test_call_skill(skill_mgr, tmp_path):
    sm, llm, tmp_path = skill_mgr
    # Write a real skill file manually
    skills_dir = str(tmp_path / "skills")
    os.makedirs(skills_dir, exist_ok=True)
    skill_path = os.path.join(skills_dir, "multiply.py")
    with open(skill_path, "w") as fh:
        fh.write("def multiply(a, b):\n    return a * b\n")
    result = sm.call_skill("multiply", kwargs={"a": 3, "b": 7})
    assert result == 21


def test_call_skill_not_found(skill_mgr):
    sm, _, _ = skill_mgr
    with pytest.raises(FileNotFoundError):
        sm.call_skill("nonexistent_skill")


def test_find_skill(skill_mgr):
    sm, llm, tmp_path = skill_mgr
    llm.chat.return_value = "def parse_xml(xml_text):\n    pass\n"
    sm.generate_skill("parse_xml", "Parse XML data", "xml_text: str", "dict", "XML parsing")
    results = sm.find_skill("xml")
    assert any("parse_xml" in r["name"] for r in results)


def test_extract_signature():
    code = "def my_func(a: int, b: str = 'x') -> bool:\n    pass"
    sig = SkillManager._extract_signature(code, "my_func")
    assert "my_func" in sig
    assert "a: int" in sig


def test_detect_imports_third_party():
    code = "import numpy as np\nimport os\nfrom pandas import DataFrame\n"
    deps = SkillManager._detect_imports(code)
    assert "numpy" in deps
    assert "pandas" in deps
    assert "os" not in deps
