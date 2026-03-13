"""Tests for agent/modules/evaluator.py — metric extraction and result parsing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agent.core.memory_manager import MemoryManager
from agent.modules.evaluator import Evaluator


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
def evaluator(mm):
    llm = MagicMock()
    return Evaluator(llm, mm), llm, mm


def test_extract_metrics_basic(evaluator):
    ev, _, _ = evaluator
    text = "Test completed. accuracy: 0.92, F1=0.88, loss: 0.123"
    metrics = ev.extract_metrics(text)
    assert abs(metrics["accuracy"] - 0.92) < 1e-6
    assert abs(metrics["f1"] - 0.88) < 1e-6
    assert abs(metrics["loss"] - 0.123) < 1e-6


def test_extract_metrics_empty(evaluator):
    ev, _, _ = evaluator
    assert ev.extract_metrics("no numbers here") == {}


def test_evaluate_supported_hypothesis(evaluator):
    ev, llm, mm = evaluator
    llm.chat.return_value = json.dumps({
        "hypothesis_supported": True,
        "key_metrics": {"accuracy": 0.91},
        "analysis": "The method improved accuracy.",
        "conclusion": "Hypothesis supported.",
        "next_steps": ["Try larger dataset"],
        "paper_worthy": True,
        "paper_contribution": "Novel approach",
    })
    result = ev.evaluate("The model improves accuracy", "accuracy: 0.91", "Idea A")
    assert result["hypothesis_supported"] is True
    # Should be stored in valid conclusions
    valid = mm.get_memory("有效结论")
    assert "Idea A" in valid


def test_evaluate_failed_hypothesis(evaluator):
    ev, llm, mm = evaluator
    llm.chat.return_value = json.dumps({
        "hypothesis_supported": False,
        "key_metrics": {},
        "analysis": "Did not work.",
        "conclusion": "Rejected.",
        "next_steps": [],
        "paper_worthy": False,
        "paper_contribution": "",
    })
    result = ev.evaluate("Should improve recall", "recall: 0.50", "Idea B")
    assert result["hypothesis_supported"] is False
    failures = mm.get_memory("失败经验")
    assert "Idea B" in failures


def test_compare_experiments(evaluator):
    ev, llm, _ = evaluator
    llm.chat.return_value = "## Comparison\n- Exp A: acc=0.9\n- Exp B: acc=0.85"
    records = [
        {"title": "Exp A", "metrics": {"accuracy": 0.9}},
        {"title": "Exp B", "metrics": {"accuracy": 0.85}},
    ]
    result = ev.compare_experiments(records)
    assert "Comparison" in result or "Exp" in result
