#!/usr/bin/env python3
"""CLI entry point for the Autonomous Research Agent.

Usage examples:

  # Start a new research run
  python main.py run --goal "Multimodal RAG for scientific document understanding"

  # Show current task status
  python main.py status

  # List all registered skills
  python main.py skills list

  # Generate a new skill on demand
  python main.py skills generate --name "parse_arxiv_xml" \
      --description "Parse arXiv API XML response into a list of paper dicts" \
      --inputs "xml_text: str" --outputs "List[Dict[str, str]]"

  # Show the current paper draft
  python main.py paper

  # Show memory
  python main.py memory [--section "研究目标"]
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-agent",
        description="Autonomous Research Agent — full paper-writing research loop",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to config YAML (default: config/config.yaml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── run ───────────────────────────────────────────────────────────────────
    run_p = sub.add_parser("run", help="Start the autonomous research loop")
    run_p.add_argument("--goal", required=True, help="Research objective (free text)")
    run_p.add_argument(
        "--cycles", type=int, default=3, help="Max idea→experiment cycles (default: 3)"
    )

    # ── status ────────────────────────────────────────────────────────────────
    sub.add_parser("status", help="Print current task status from tasks.md")

    # ── memory ────────────────────────────────────────────────────────────────
    mem_p = sub.add_parser("memory", help="Print agent memory")
    mem_p.add_argument("--section", default=None, help="Specific memory section to print")

    # ── paper ─────────────────────────────────────────────────────────────────
    sub.add_parser("paper", help="Print the current paper draft")

    # ── skills ────────────────────────────────────────────────────────────────
    skills_p = sub.add_parser("skills", help="Manage reusable skills")
    skills_sub = skills_p.add_subparsers(dest="skills_command", required=True)

    skills_sub.add_parser("list", help="List all registered skills")

    find_p = skills_sub.add_parser("find", help="Search skills by keyword")
    find_p.add_argument("keyword", help="Search keyword")

    gen_p = skills_sub.add_parser("generate", help="Generate a new skill via LLM")
    gen_p.add_argument("--name", required=True, help="Snake_case skill name")
    gen_p.add_argument("--description", required=True, help="What the skill does")
    gen_p.add_argument("--inputs", default="", help="Input parameter description")
    gen_p.add_argument("--outputs", default="", help="Output description")
    gen_p.add_argument("--use-cases", default="", dest="use_cases", help="When to use this skill")

    call_p = skills_sub.add_parser("call", help="Call a registered skill")
    call_p.add_argument("name", help="Skill name")
    call_p.add_argument("--fn", default=None, help="Function name within skill (default: skill name)")

    return parser


def cmd_run(args: argparse.Namespace) -> None:
    from agent.core.agent import ResearchAgent
    agent = ResearchAgent(config_path=args.config)
    agent.run(goal=args.goal, max_cycles=args.cycles)


def cmd_status(args: argparse.Namespace) -> None:
    from agent.core.memory_manager import MemoryManager
    import os
    import yaml
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    state_cfg = {**cfg.get("state", {}), "skills_registry": cfg["skills"]["skills_registry"]}
    mm = MemoryManager(state_cfg)
    print(mm.get_all_tasks())


def cmd_memory(args: argparse.Namespace) -> None:
    from agent.core.memory_manager import MemoryManager
    import yaml
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    state_cfg = {**cfg.get("state", {}), "skills_registry": cfg["skills"]["skills_registry"]}
    mm = MemoryManager(state_cfg)
    print(mm.get_memory(args.section))


def cmd_paper(args: argparse.Namespace) -> None:
    from agent.core.memory_manager import MemoryManager
    import yaml
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    state_cfg = {**cfg.get("state", {}), "skills_registry": cfg["skills"]["skills_registry"]}
    mm = MemoryManager(state_cfg)
    print(mm.get_paper_draft())


def cmd_skills(args: argparse.Namespace) -> None:
    from agent.core.memory_manager import MemoryManager
    from agent.modules.skill_manager import SkillManager
    from agent.tools.llm_client import LLMClient
    import yaml
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    state_cfg = {**cfg.get("state", {}), "skills_registry": cfg["skills"]["skills_registry"]}
    mm = MemoryManager(state_cfg)
    llm = LLMClient(cfg["llm"])
    sm = SkillManager(llm, mm, cfg["skills"])

    if args.skills_command == "list":
        print(sm.list_skills())

    elif args.skills_command == "find":
        results = sm.find_skill(args.keyword)
        if results:
            for r in results:
                print(f"- {r['name']}: {r['description']} ({r['file_path']})")
        else:
            print("No skills found.")

    elif args.skills_command == "generate":
        path = sm.generate_skill(
            name=args.name,
            description=args.description,
            inputs=args.inputs,
            outputs=args.outputs,
            use_cases=args.use_cases,
        )
        print(f"Skill generated: {path}")

    elif args.skills_command == "call":
        result = sm.call_skill(args.name, function_name=args.fn)
        print(f"Result: {result}")


def main(argv: Optional[list] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "run": cmd_run,
        "status": cmd_status,
        "memory": cmd_memory,
        "paper": cmd_paper,
        "skills": cmd_skills,
    }
    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
