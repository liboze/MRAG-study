"""Experiment module — implement ideas, run experiments, iterate based on results.

Workflow:
  1. Understand the target codebase (from CodeRunner analysis).
  2. Ask LLM to generate code modifications for the research idea.
  3. Apply the changes and run the experiment.
  4. Record results; if failed, retry with LLM-suggested fixes (up to max_iter).
  5. Persist results to memory and workspace/results.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from agent.core.memory_manager import MemoryManager
from agent.modules.code_runner import CodeRunner
from agent.tools.llm_client import LLMClient
from agent.utils.file_manager import now_str, write_file
from agent.utils.logger import get_logger

logger = get_logger(__name__)

_CODE_MOD_SYSTEM = """你是一名资深 Python 研究工程师，擅长根据研究假设修改实验代码。
请根据提供的研究 idea 和已有代码结构，输出具体的代码修改方案。

输出格式（JSON 对象，不含其他文字）：
{
  "file_path": "相对于项目根目录的文件路径",
  "description": "修改说明（≤100 字）",
  "search": "要替换的原始代码片段（精确匹配，≤30 行）",
  "replace": "替换后的代码片段"
}

若需多处修改，请输出 JSON 数组，每个元素为上述对象。
"""

_EXPERIMENT_PLAN_SYSTEM = """你是一名 AI 实验设计专家。
请根据研究 idea 和项目分析，给出完整的实验执行计划。

输出 JSON 对象（不含其他文字）：
{
  "install_cmd": ["pip", "install", "..."],
  "run_commands": [["python", "train.py", "--arg", "val"]],
  "expected_output_keywords": ["accuracy", "F1"],
  "results_dir": "outputs/"
}
"""


class Experimenter:
    """Manage the full experiment lifecycle for a research idea.

    Parameters
    ----------
    llm:
        Configured LLM client.
    code_runner:
        Configured CodeRunner.
    memory:
        Memory manager.
    config:
        The ``experiment`` section from config.yaml.
    """

    def __init__(
        self,
        llm: LLMClient,
        code_runner: CodeRunner,
        memory: MemoryManager,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._llm = llm
        self._runner = code_runner
        self._memory = memory
        self._cfg = config or {}
        self._results_dir = self._cfg.get("results_dir", "workspace/results")
        self._max_iter = int(self._cfg.get("max_iterations", 5))
        os.makedirs(self._results_dir, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def run_experiment(
        self,
        idea: Dict[str, Any],
        project_path: str,
        repo_analysis: str = "",
    ) -> Dict[str, Any]:
        """Run the experiment for *idea* inside *project_path*.

        Attempts up to ``max_iterations`` times, applying LLM fixes on failure.
        Returns a summary dict with ``success``, ``output``, ``iterations``,
        ``result_file``.
        """
        idea_title = idea.get("title", "experiment")
        logger.info("Experimenter: running experiment %r in %s", idea_title, project_path)

        # Step 1: Generate code modifications
        modifications = self._generate_modifications(idea, project_path, repo_analysis)

        # Step 2: Apply modifications
        for mod in modifications:
            self._apply_modification(project_path, mod)

        # Step 3: Get experiment plan
        plan = self._plan_experiment(idea, project_path, repo_analysis)
        run_commands: List[List[str]] = plan.get("run_commands", [])
        if not run_commands:
            run_commands = [["python", "-m", "pytest", "-x", "-q"]]

        # Step 4: Execute with retry
        all_output: List[str] = []
        success = False
        for iteration in range(1, self._max_iter + 1):
            for cmd in run_commands:
                result = self._runner.run_script(
                    script_path=cmd[0] if os.path.isabs(cmd[0]) else os.path.join(project_path, cmd[0]),
                    args=cmd[1:],
                    cwd=project_path,
                ) if cmd[0].endswith(".py") else self._runner._github.run_command(
                    project_path, cmd, timeout=self._runner._timeout
                )

                output_chunk = f"[iter {iteration}] CMD: {' '.join(cmd)}\n"
                output_chunk += result.get("stdout", "")[-2000:]
                if result.get("stderr"):
                    output_chunk += "\nSTDERR:\n" + result["stderr"][-500:]
                all_output.append(output_chunk)

                if result["returncode"] == 0:
                    success = True
                    break
                else:
                    logger.warning(
                        "Experiment iteration %d failed. Attempting auto-fix...", iteration
                    )
                    fix = result.get("debug_suggestion", "")
                    if fix:
                        self._apply_llm_fix(project_path, result["stderr"], fix)

            if success:
                break

        full_output = "\n\n".join(all_output)
        result_file = self._save_results(idea_title, full_output, success)

        # Persist summary to memory
        status = "成功" if success else "失败"
        self._memory.append_memory(
            "实验注意事项",
            f"**{idea_title}** ({status}, {iteration} 次迭代): {full_output[:300]}",
        )
        logger.info("Experimenter: done. success=%s iterations=%d", success, iteration)
        return {
            "success": success,
            "output": full_output,
            "iterations": iteration,
            "result_file": result_file,
        }

    # ── Internal ───────────────────────────────────────────────────────────────

    def _generate_modifications(
        self, idea: Dict[str, Any], project_path: str, repo_analysis: str
    ) -> List[Dict[str, Any]]:
        """Ask LLM to produce code modifications for the idea."""
        prompt = (
            f"研究 Idea：\n{idea.get('title', '')}\n"
            f"假设：{idea.get('hypothesis', '')}\n"
            f"实现路径：{idea.get('approach', '')}\n\n"
            f"项目分析：\n{repo_analysis[:1500]}"
        )
        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_CODE_MOD_SYSTEM,
        )
        import json, re
        # Try list first, then single object
        for pattern in (r"\[.*\]", r"\{.*\}"):
            m = re.search(pattern, raw, re.DOTALL)
            if m:
                try:
                    result = json.loads(m.group(0))
                    if isinstance(result, list):
                        return result
                    if isinstance(result, dict):
                        return [result]
                except json.JSONDecodeError:
                    pass
        return []

    def _plan_experiment(
        self, idea: Dict[str, Any], project_path: str, repo_analysis: str
    ) -> Dict[str, Any]:
        prompt = (
            f"研究 Idea：{idea.get('title', '')}\n"
            f"验证方式：{idea.get('validation', '')}\n\n"
            f"项目路径：{project_path}\n"
            f"项目分析：{repo_analysis[:800]}"
        )
        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_EXPERIMENT_PLAN_SYSTEM,
        )
        import json, re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return {}

    def _apply_modification(self, project_path: str, mod: Dict[str, Any]) -> None:
        """Apply a single file modification (search-and-replace)."""
        rel_path = mod.get("file_path", "")
        if not rel_path:
            return
        full_path = os.path.join(project_path, rel_path)
        if not os.path.exists(full_path):
            logger.warning("Modification target not found: %s", full_path)
            return
        with open(full_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        search = mod.get("search", "")
        replace = mod.get("replace", "")
        if search and search in content:
            content = content.replace(search, replace, 1)
            with open(full_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            logger.info("Applied modification to %s: %s", rel_path, mod.get("description", ""))
        else:
            logger.warning("Search pattern not found in %s; skipping modification.", rel_path)

    def _apply_llm_fix(self, project_path: str, stderr: str, suggestion: str) -> None:
        """Try to auto-apply a fix suggested by the LLM."""
        prompt = (
            f"错误：\n{stderr[:1000]}\n\n"
            f"修复建议：\n{suggestion[:500]}\n\n"
            "请给出可直接执行的 shell 命令（一行，不含解释）："
        )
        cmd_str = self._llm.complete(prompt, max_tokens=80).strip().strip("`")
        if not cmd_str or cmd_str.startswith("#"):
            return
        import shlex
        import subprocess
        # Basic safety check: reject commands with dangerous shell metacharacters
        _DANGEROUS = (";", "&&", "||", "|", ">", "<", "`", "$(", "${")
        if any(tok in cmd_str for tok in _DANGEROUS):
            logger.warning("Auto-fix command contains unsafe characters; skipping: %s", cmd_str)
            return
        try:
            safe_cmd = shlex.split(cmd_str)
        except ValueError:
            logger.warning("Could not parse auto-fix command: %s", cmd_str)
            return
        logger.info("Applying auto-fix command: %s", safe_cmd)
        subprocess.run(safe_cmd, cwd=project_path, timeout=120)

    def _save_results(self, title: str, output: str, success: bool) -> str:
        """Save experiment output to a timestamped file and return its path."""
        ts = now_str().replace(":", "-")
        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:50]
        filename = f"{ts}_{safe_title}_{'ok' if success else 'fail'}.txt"
        path = os.path.join(self._results_dir, filename)
        write_file(path, output)
        logger.info("Results saved to %s", path)
        return path
