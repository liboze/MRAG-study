"""Code runner module — find, clone, understand, and run GitHub repositories.

Capabilities:
  - Search GitHub for relevant open-source projects
  - Inspect project structure (README, file tree)
  - Understand dependencies, entry points, and key logic via LLM analysis
  - Clone and run code in a sandboxed local workspace
  - Debug failures and attempt auto-fix
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from agent.core.memory_manager import MemoryManager
from agent.tools.github_client import GitHubClient
from agent.tools.llm_client import LLMClient
from agent.utils.logger import get_logger

logger = get_logger(__name__)

_ANALYSE_SYSTEM = """你是一名 Python 工程专家，擅长快速理解开源项目。
请分析提供的 README 和文件结构，给出：
1. 项目概述（≤100 字）；
2. 核心依赖（列表）；
3. 如何安装环境（具体命令）；
4. 如何运行基准实验（具体命令）；
5. 关键代码文件（列表，说明用途）；
6. 可以利用或修改的主要模块与功能点。
请以结构化 Markdown 输出。
"""

_DEBUG_SYSTEM = """你是一名资深 Python 调试专家。
请分析以下错误输出，给出：
1. 错误根本原因；
2. 修复建议（≤150 字）；
3. 具体修复命令或代码（如适用）。
以 Markdown 格式输出，包含 ## 错误原因、## 修复建议、## 修复操作。
"""


class CodeRunner:
    """Interact with GitHub projects: search, clone, understand, run, debug.

    Parameters
    ----------
    llm:
        Configured LLM client.
    github:
        Configured GitHub client.
    memory:
        Memory manager.
    config:
        The ``experiment`` section from config.yaml.
    """

    def __init__(
        self,
        llm: LLMClient,
        github: GitHubClient,
        memory: MemoryManager,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._llm = llm
        self._github = github
        self._memory = memory
        self._cfg = config or {}
        self._workspace = self._cfg.get("workspace_dir", "workspace")
        self._max_iter = int(self._cfg.get("max_iterations", 5))
        self._timeout = int(self._cfg.get("timeout", 3600))
        os.makedirs(self._workspace, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def find_and_analyse(self, query: str, max_repos: int = 5) -> List[Dict[str, Any]]:
        """Search GitHub for *query*, analyse top repos, return analysis list."""
        logger.info("CodeRunner: searching repos for %r", query)
        repos = self._github.search_repos(query, max_results=max_repos)
        analyses: List[Dict[str, Any]] = []
        for repo in repos:
            analysis = self._analyse_repo(repo)
            analyses.append(analysis)

        # Persist to memory
        summary = "\n\n---\n\n".join(
            f"**{a['full_name']}** (⭐{a.get('stars', 0)})\n{a.get('analysis', '')[:300]}"
            for a in analyses
        )
        self._memory.update_memory("GitHub 开源项目", summary)
        return analyses

    def clone_and_run(
        self,
        repo: Dict[str, Any],
        run_command: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Clone *repo* and run *run_command* in it.

        If *run_command* is ``None``, attempts to auto-detect a reasonable
        command from the LLM's project analysis.

        Returns a result dict: ``local_path``, ``returncode``, ``stdout``,
        ``stderr``, ``debug_suggestion`` (if failed).
        """
        clone_url = repo.get("clone_url", "")
        full_name = repo.get("full_name", "repo")
        if not clone_url:
            return {"error": "No clone_url provided."}

        local_path = self._github.clone_repo(clone_url, full_name)

        # Install dependencies if requirements.txt or setup.py exist
        self._install_dependencies(local_path)

        cmd = run_command or self._infer_run_command(local_path, repo)
        if not cmd:
            return {"local_path": local_path, "error": "Could not determine run command."}

        result = self._github.run_command(local_path, cmd, timeout=self._timeout, env=env)
        result["local_path"] = local_path

        if result["returncode"] != 0:
            debug = self._debug(result["stderr"] + "\n" + result["stdout"])
            result["debug_suggestion"] = debug
            self._memory.append_memory("实验注意事项", f"**{full_name}** 运行失败：{debug[:200]}")

        return result

    def run_script(
        self,
        script_path: str,
        args: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run a Python script by path with optional arguments."""
        cmd = ["python", script_path] + (args or [])
        work_dir = cwd or os.path.dirname(script_path) or "."
        result = self._github.run_command(work_dir, cmd, timeout=self._timeout, env=env)
        if result["returncode"] != 0:
            result["debug_suggestion"] = self._debug(result["stderr"])
        return result

    # ── Internal ───────────────────────────────────────────────────────────────

    def _analyse_repo(self, repo: Dict[str, Any]) -> Dict[str, Any]:
        full_name = repo["full_name"]
        readme = self._github.get_readme(full_name)
        file_tree = self._github.list_files(full_name)
        tree_text = "\n".join(
            f"{'  ' if f['type'] == 'file' else ''}{f['path']} ({f['type']})"
            for f in file_tree[:40]
        )
        prompt = (
            f"**仓库**: {full_name}\n"
            f"**Stars**: {repo.get('stars', 0)}\n"
            f"**语言**: {repo.get('language', '')}\n\n"
            f"## README\n{readme[:2000]}\n\n"
            f"## 文件结构\n{tree_text}"
        )
        analysis = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_ANALYSE_SYSTEM,
        )
        return {**repo, "readme": readme[:500], "analysis": analysis}

    def _install_dependencies(self, local_path: str) -> None:
        req_path = os.path.join(local_path, "requirements.txt")
        setup_path = os.path.join(local_path, "setup.py")
        pyproject = os.path.join(local_path, "pyproject.toml")

        if os.path.exists(req_path):
            logger.info("Installing requirements.txt in %s", local_path)
            self._github.run_command(
                local_path, ["pip", "install", "-r", "requirements.txt", "-q"], timeout=300
            )
        elif os.path.exists(setup_path) or os.path.exists(pyproject):
            logger.info("Installing package in %s", local_path)
            self._github.run_command(
                local_path, ["pip", "install", "-e", ".", "-q"], timeout=300
            )

    def _infer_run_command(
        self, local_path: str, repo: Dict[str, Any]
    ) -> Optional[List[str]]:
        """Ask the LLM to suggest a minimal run command based on project analysis."""
        analysis = repo.get("analysis", "") or repo.get("readme", "")
        if not analysis:
            return None
        prompt = (
            f"项目分析：\n{analysis[:1000]}\n\n"
            "请给出运行该项目基准实验的最简单命令（仅输出命令本身，不含解释）："
        )
        cmd_str = self._llm.complete(prompt, max_tokens=100).strip()
        # Remove markdown code fences if present
        cmd_str = re.sub(r"^```\w*\n?", "", cmd_str).strip("`").strip()
        if not cmd_str:
            return None
        import shlex
        try:
            return shlex.split(cmd_str)
        except ValueError:
            return cmd_str.split()

    def _debug(self, error_output: str) -> str:
        prompt = f"错误输出：\n\n{error_output[:2000]}"
        return self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_DEBUG_SYSTEM,
        )
