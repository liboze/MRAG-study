"""Main agent orchestrator.

Implements the full autonomous research loop:

  Step 1  — Clarify / load research goal
  Step 2  — Decompose into tasks
  Step 3  — Survey literature
  Step 4  — Collect datasets
  Step 5  — Generate ideas
  Step 6  — Select best idea
  Step 7  — Find & analyse GitHub repos
  Step 8  — Clone & set up project
  Step 9  — Run baseline experiment
  Step 10 — Implement idea modifications
  Step 11 — Run modified experiment
  Step 12 — Evaluate results
  Step 13 — Write / update paper sections
  Step 14 — Repeat from step 5 if needed
  Step 15 — Finalise paper (abstract, title)

Human-in-the-loop checkpoints are inserted at key decision points.
The agent can pause, wait for human input, and resume seamlessly.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

import yaml

from agent.core.memory_manager import MemoryManager
from agent.core.planner import Planner
from agent.modules.code_runner import CodeRunner
from agent.modules.data_collector import DataCollector
from agent.modules.evaluator import Evaluator
from agent.modules.experimenter import Experimenter
from agent.modules.idea_generator import IdeaGenerator
from agent.modules.paper_writer import PaperWriter
from agent.modules.researcher import Researcher
from agent.modules.skill_manager import SkillManager
from agent.tools.github_client import GitHubClient
from agent.tools.llm_client import LLMClient
from agent.tools.search_client import SearchClient
from agent.utils.file_manager import now_str, read_file
from agent.utils.logger import get_logger


class ResearchAgent:
    """Full autonomous research agent.

    Parameters
    ----------
    config_path:
        Path to ``config/config.yaml``.
    """

    def __init__(self, config_path: str = "config/config.yaml") -> None:
        self._cfg = self._load_config(config_path)
        self._logger = get_logger(__name__, self._cfg.get("logging", {}))

        # ── Tool layer ────────────────────────────────────────────────────────
        self._llm = LLMClient(self._cfg["llm"])
        self._search = SearchClient(self._cfg["search"])
        self._github = GitHubClient(self._cfg["github"])

        # ── State layer ───────────────────────────────────────────────────────
        state_cfg = {**self._cfg.get("state", {}), "skills_registry": self._cfg["skills"]["skills_registry"]}
        self._memory = MemoryManager(state_cfg)
        self._planner = Planner(self._llm, self._memory)

        # ── Module layer ──────────────────────────────────────────────────────
        self._researcher = Researcher(self._llm, self._search, self._memory)
        self._data_collector = DataCollector(self._llm, self._search, self._memory)
        self._idea_gen = IdeaGenerator(self._llm, self._memory)
        self._code_runner = CodeRunner(self._llm, self._github, self._memory, self._cfg.get("experiment", {}))
        self._experimenter = Experimenter(self._llm, self._code_runner, self._memory, self._cfg.get("experiment", {}))
        self._evaluator = Evaluator(self._llm, self._memory)
        self._skill_mgr = SkillManager(self._llm, self._memory, self._cfg["skills"])
        self._paper_writer = PaperWriter(self._llm, self._memory)

        self._human_cfg = self._cfg.get("human_loop", {})
        self._logger.info("ResearchAgent initialised.")

    # ── Main entry point ───────────────────────────────────────────────────────

    def run(self, goal: str, max_cycles: int = 3) -> None:
        """Start the autonomous research loop for *goal*.

        Parameters
        ----------
        goal:
            The research objective (free-form text).
        max_cycles:
            Maximum idea → experiment → evaluate cycles before finalising.
        """
        self._logger.info("=== Research Agent starting | goal=%r ===", goal)

        # ── Phase 1: Planning ──────────────────────────────────────────────────
        self._run_phase("任务规划", self._phase_plan, goal)

        # ── Phase 2: Survey ────────────────────────────────────────────────────
        survey_result = self._run_phase("文献调研", self._phase_survey, goal)

        # ── Phase 3: Data collection ───────────────────────────────────────────
        self._run_phase("数据集收集", self._phase_collect_data, goal)

        # ── Phase 4: Write background & related work ───────────────────────────
        if survey_result:
            self._run_phase("论文背景章节", self._phase_write_background, survey_result.get("synthesis", ""))

        # ── Phase 5–N: Idea → Experiment cycles ───────────────────────────────
        for cycle in range(1, max_cycles + 1):
            self._logger.info("=== Cycle %d / %d ===", cycle, max_cycles)

            # Generate and select idea
            ideas = self._run_phase(f"Idea 生成 (cycle {cycle})", self._phase_generate_ideas, goal)
            if not ideas:
                self._logger.warning("No ideas generated; ending cycles early.")
                break

            idea = self._run_phase(f"Idea 选择 (cycle {cycle})", self._phase_select_idea, ideas)
            if not idea:
                break

            # Write method section
            self._run_phase(f"论文方法章节 (cycle {cycle})", self._paper_writer.write_method, idea)

            # Find code, run experiment
            experiment_result = self._run_phase(
                f"代码查找与实验 (cycle {cycle})",
                self._phase_experiment,
                idea,
                goal,
            )

            if not experiment_result:
                self._planner.mark_blocked(f"Idea 实验 cycle {cycle}", "实验未能返回结果")
                continue

            # Evaluate
            evaluation = self._run_phase(
                f"结果评估 (cycle {cycle})",
                self._phase_evaluate,
                idea,
                experiment_result,
            )

            # Update paper
            if evaluation:
                self._run_phase(
                    f"论文结果章节 (cycle {cycle})",
                    self._paper_writer.write_results,
                    evaluation,
                )

            # Decide whether to continue cycling
            if self._should_stop_cycling(evaluation):
                self._logger.info("Sufficient results obtained; stopping cycles.")
                break

        # ── Phase N+1: Finalise paper ──────────────────────────────────────────
        self._run_phase("论文结论章节", self._paper_writer.write_conclusion)
        self._run_phase("论文摘要", self._paper_writer.write_abstract)
        self._run_phase("论文标题建议", self._paper_writer.suggest_title)

        self._logger.info("=== Research Agent finished. Draft at: %s ===",
                          self._cfg.get("state", {}).get("paper_draft_file", "state/paper_draft.md"))

    # ── Phase implementations ──────────────────────────────────────────────────

    def _phase_plan(self, goal: str) -> List[Dict[str, Any]]:
        tasks = self._planner.decompose_goal(goal)
        self._planner.mark_in_progress("任务规划")
        self._planner.mark_done("任务规划", f"{len(tasks)} tasks decomposed.")
        return tasks

    def _phase_survey(self, goal: str) -> Dict[str, Any]:
        self._planner.mark_in_progress("文献调研")
        result = self._researcher.survey(goal)
        self._planner.mark_done("文献调研", f"{len(result.get('papers', []))} papers found.")
        return result

    def _phase_collect_data(self, goal: str) -> Dict[str, Any]:
        self._planner.mark_in_progress("数据集收集")
        result = self._data_collector.collect(goal)
        self._planner.mark_done("数据集收集")
        return result

    def _phase_write_background(self, synthesis: str) -> None:
        self._paper_writer.write_background(synthesis)
        self._paper_writer.write_related_work(synthesis)

    def _phase_generate_ideas(self, goal: str) -> List[Dict[str, Any]]:
        self._planner.mark_in_progress("Idea 生成")
        ideas = self._idea_gen.generate_ideas(goal)
        self._planner.mark_done("Idea 生成", f"{len(ideas)} ideas generated.")
        return ideas

    def _phase_select_idea(self, ideas: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        idea = self._idea_gen.select_idea(ideas)
        if idea and self._human_cfg.get("pause_on_key_decision", True):
            self._request_human_confirmation(
                f"智能体已选定研究 Idea：**{idea.get('title')}**\n"
                f"假设：{idea.get('hypothesis')}\n"
                f"选择理由：{idea.get('selection_reason')}\n\n"
                "请确认是否继续实验，或输入修改意见（直接回车则继续）："
            )
        return idea

    def _phase_experiment(self, idea: Dict[str, Any], goal: str) -> Optional[Dict[str, Any]]:
        query = f"{goal} {idea.get('title', '')}"
        analyses = self._code_runner.find_and_analyse(query, max_repos=3)
        if not analyses:
            self._notify_human(
                "无法找到相关 GitHub 项目，需要您手动提供代码仓库地址。",
                action_required="请提供一个可用的 GitHub 仓库克隆地址，并更新 config/config.yaml。",
            )
            return None

        best_repo = analyses[0]
        if best_repo.get("stars", 0) == 0 and not best_repo.get("clone_url"):
            self._notify_human(
                f"找到的仓库 {best_repo.get('full_name')} 可能无法访问，请确认。",
                action_required="请验证仓库可用性或提供替代仓库。",
            )

        clone_result = self._code_runner.clone_and_run(best_repo)
        local_path = clone_result.get("local_path", "")
        if not local_path:
            return None

        repo_analysis = best_repo.get("analysis", "")
        exp_result = self._experimenter.run_experiment(idea, local_path, repo_analysis)

        # Write experiment setup section
        dataset_summary = self._memory.get_memory("数据集资源")
        self._paper_writer.write_experiment_setup(
            dataset_summary,
            f"仓库: {best_repo.get('full_name')}\n实验结果: {exp_result.get('output', '')[:300]}",
        )
        return exp_result

    def _phase_evaluate(
        self, idea: Dict[str, Any], experiment_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        hypothesis = idea.get("hypothesis", "")
        output = experiment_result.get("output", "")
        evaluation = self._evaluator.evaluate(hypothesis, output, idea.get("title", ""))
        return evaluation

    # ── Helper methods ─────────────────────────────────────────────────────────

    def _run_phase(self, phase_name: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a phase function with error handling and task tracking."""
        self._logger.info("[Phase] %s — starting", phase_name)
        try:
            result = fn(*args, **kwargs)
            self._logger.info("[Phase] %s — done", phase_name)
            return result
        except KeyboardInterrupt:
            self._logger.warning("[Phase] %s interrupted by user.", phase_name)
            self._planner.mark_blocked(phase_name, "用户中断")
            raise
        except Exception as exc:  # noqa: BLE001
            self._logger.error("[Phase] %s FAILED: %s", phase_name, exc, exc_info=True)
            self._planner.mark_blocked(phase_name, str(exc))
            self._notify_human(
                f"阶段 '{phase_name}' 遇到错误：{exc}",
                action_required="请检查日志，修复问题后重新运行。",
            )
            return None

    def _should_stop_cycling(self, evaluation: Optional[Dict[str, Any]]) -> bool:
        if not evaluation:
            return False
        supported = evaluation.get("hypothesis_supported", False)
        paper_worthy = evaluation.get("paper_worthy", False)
        return bool(supported) and bool(paper_worthy)

    def _request_human_confirmation(self, message: str) -> str:
        """Pause and ask for human input via console."""
        channel = self._human_cfg.get("notification_channel", "console")
        if channel == "console":
            print("\n" + "=" * 60)
            print("[人工确认请求]")
            print(message)
            try:
                response = input("您的回应（直接回车继续）: ").strip()
            except EOFError:
                response = ""
            print("=" * 60 + "\n")
            return response
        return ""

    def _notify_human(self, message: str, action_required: str = "") -> None:
        """Notify the human of a situation requiring their attention."""
        channel = self._human_cfg.get("notification_channel", "console")
        note = f"[人工通知] {message}"
        if action_required:
            note += f"\n[需要操作] {action_required}"

        if channel == "console":
            print("\n" + "!" * 60)
            print(note)
            print("!" * 60 + "\n")

        self._memory.add_memory_note(note, "人工干预记录")
        self._logger.warning("Human notification: %s | action: %s", message, action_required)

    # ── Config loader ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_config(path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        return cfg or {}
