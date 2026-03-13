"""Skill manager — create, store, retrieve, and invoke reusable Python skills.

A "skill" is a standalone Python function (in a .py file under ``skills/``)
that the agent can generate on demand and reuse across tasks.

Lifecycle:
  1. Agent identifies a reusable sub-task.
  2. ``generate_skill()`` asks the LLM to write a Python function.
  3. The function is saved to ``skills/<name>.py`` and registered in ``skills.md``.
  4. ``find_skill()`` retrieves relevant skills by keyword.
  5. ``call_skill()`` executes a registered skill with given arguments.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import re
from typing import Any, Callable, Dict, List, Optional

from agent.core.memory_manager import MemoryManager
from agent.tools.llm_client import LLMClient
from agent.utils.file_manager import now_str, write_file
from agent.utils.logger import get_logger

logger = get_logger(__name__)

_SKILL_GEN_SYSTEM = """你是一名 Python 工程专家，擅长编写可复用的工具函数。
请根据用户描述，编写一个独立的 Python 函数作为"技能脚本"。

要求：
1. 函数必须有类型注解；
2. 函数必须有 docstring，说明功能、参数、返回值；
3. 函数必须是自包含的（所有 import 在函数内部或文件顶部）；
4. 函数名使用 snake_case；
5. 仅输出完整的 Python 源码，不含任何解释或 Markdown 标记。
"""


class SkillManager:
    """Manage the lifecycle of reusable Python skill scripts.

    Parameters
    ----------
    llm:
        Configured LLM client.
    memory:
        Memory manager (for skills.md).
    config:
        The ``skills`` section from config.yaml.
    """

    def __init__(self, llm: LLMClient, memory: MemoryManager, config: Dict[str, Any]) -> None:
        self._llm = llm
        self._memory = memory
        self._skills_dir = config.get("skills_dir", "skills")
        os.makedirs(self._skills_dir, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_skill(
        self,
        name: str,
        description: str,
        inputs: str,
        outputs: str,
        use_cases: str,
        extra_context: str = "",
    ) -> str:
        """Ask the LLM to generate a skill and save it.

        Parameters
        ----------
        name:
            Snake_case function / file name (without ``.py``).
        description:
            What the skill does.
        inputs / outputs:
            Human-readable description of params and return values.
        use_cases:
            Scenarios where this skill applies.
        extra_context:
            Additional code or context to guide generation.

        Returns the path to the saved skill file.
        """
        prompt = (
            f"技能名称: {name}\n"
            f"功能描述: {description}\n"
            f"输入参数: {inputs}\n"
            f"输出: {outputs}\n"
            f"适用场景: {use_cases}\n"
        )
        if extra_context:
            prompt += f"\n参考上下文:\n{extra_context[:1000]}"

        code = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_SKILL_GEN_SYSTEM,
        )
        # Strip markdown fences if present
        code = re.sub(r"^```python\n?", "", code.strip())
        code = re.sub(r"```$", "", code).strip()

        file_path = os.path.join(self._skills_dir, f"{name}.py")
        write_file(file_path, code + "\n")
        logger.info("Skill generated and saved: %s", file_path)

        # Detect call signature from generated code
        call_sig = self._extract_signature(code, name)

        # Register in skills.md
        self._memory.register_skill({
            "name": name,
            "description": description,
            "inputs": inputs,
            "outputs": outputs,
            "use_cases": use_cases,
            "call_signature": call_sig,
            "dependencies": self._detect_imports(code),
            "file_path": file_path,
            "updated_at": now_str(),
        })
        return file_path

    def find_skill(self, keyword: str) -> List[Dict[str, str]]:
        """Return skills whose name/description/use_cases contain *keyword*.

        Returns list of dicts with ``name``, ``file_path``, ``description``.
        """
        skills_md = self._memory.find_skill(keyword)
        results: List[Dict[str, str]] = []
        for block in skills_md.split("---"):
            name_m = re.search(r"### (\S+)", block)
            path_m = re.search(r"\*\*代码位置\*\*: `([^`]+)`", block)
            desc_m = re.search(r"\*\*功能\*\*: (.+)", block)
            if name_m:
                results.append({
                    "name": name_m.group(1),
                    "file_path": path_m.group(1) if path_m else "",
                    "description": desc_m.group(1).strip() if desc_m else "",
                })
        return results

    def call_skill(
        self,
        name: str,
        function_name: Optional[str] = None,
        args: Optional[tuple] = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Import and call a skill by *name*.

        Parameters
        ----------
        name:
            The skill name (file base name without ``.py``).
        function_name:
            Function to call; defaults to *name*.
        args / kwargs:
            Positional and keyword arguments to pass.

        Returns the function's return value.
        """
        file_path = os.path.join(self._skills_dir, f"{name}.py")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Skill not found: {file_path}")

        fn = function_name or name
        spec = importlib.util.spec_from_file_location(name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load skill: {file_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        if not hasattr(module, fn):
            raise AttributeError(f"Function {fn!r} not found in {file_path}")

        callable_fn: Callable = getattr(module, fn)
        logger.info("Calling skill %s.%s", name, fn)
        return callable_fn(*(args or ()), **(kwargs or {}))

    def list_skills(self) -> str:
        """Return the full skills.md content."""
        return self._memory.get_skills()

    # ── Internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_signature(code: str, default_name: str) -> str:
        m = re.search(r"^def (\w+\([^)]*\))", code, re.MULTILINE)
        if m:
            return m.group(1)
        return f"{default_name}(...)"

    @staticmethod
    def _detect_imports(code: str) -> str:
        imports = re.findall(r"^(?:import|from)\s+(\S+)", code, re.MULTILINE)
        stdlib = {"os", "sys", "re", "json", "pathlib", "typing", "datetime", "math",
                  "random", "collections", "itertools", "functools", "io", "abc",
                  "copy", "time", "logging", "subprocess", "shutil"}
        third_party = sorted(set(i.split(".")[0] for i in imports) - stdlib)
        return ", ".join(third_party) if third_party else "standard library only"
