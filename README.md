# MRAG-study: 全自动科研运行智能体

> **Autonomous Research Agent** — 以最少人工干预自主完成"选题 → 调研 → 实验 → 论文"全流程。

---

## 目录

- [系统概览](#系统概览)
- [核心能力](#核心能力)
- [系统架构](#系统架构)
- [项目目录结构](#项目目录结构)
- [状态文件说明](#状态文件说明)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [CLI 命令参考](#cli-命令参考)
- [自动化科研工作流](#自动化科研工作流)
- [人机协作机制](#人机协作机制)
- [开发路线图](#开发路线图)

---

## 系统概览

本项目实现了一套**全自动科研智能体**，以 Python 为核心，围绕科研目标自主推进任务，覆盖从选题到实验再到论文写作的完整闭环。系统的最终目标不是"只完成实验"，而是**产出一篇完整的学术论文**。

---

## 核心能力

| 能力 | 模块 | 说明 |
|------|------|------|
| 自主调研研究方向 | `researcher.py` | arXiv / Semantic Scholar / Web 检索 + LLM 综述 |
| 自主收集数据集 | `data_collector.py` | 搜索公开数据集并生成对比分析 |
| 自主提出研究 Idea | `idea_generator.py` | 基于文献、结论、资源生成并选优 |
| 运行 GitHub 代码 | `code_runner.py` | 搜索、克隆、分析、运行、自动调试 |
| 代码修改与实验迭代 | `experimenter.py` | LLM 驱动代码修改 + 多轮实验执行 |
| 实验结果评估 | `evaluator.py` | 量化指标提取 + 假设验证 + 下一步建议 |
| Python Skill 编写与复用 | `skill_manager.py` | LLM 生成 → 保存 → 检索 → 动态调用 |
| 任务自主拆解与调度 | `planner.py` | LLM 任务分解 + 优先级调度 + 状态流转 |
| 论文增量写作 | `paper_writer.py` | 按章节渐进式生成，随实验同步积累 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      ResearchAgent (agent.py)               │
│              主编排器 · 自动科研闭环 · 人机协作接口            │
└────────────────┬────────────────────────────────────────────┘
                 │
    ┌────────────┴────────────┐
    │       Core Layer        │
    │  Planner  MemoryManager │
    └────────────┬────────────┘
                 │
    ┌────────────┴────────────────────────────────┐
    │              Module Layer                    │
    │  Researcher  DataCollector  IdeaGenerator    │
    │  CodeRunner  Experimenter   Evaluator        │
    │  SkillManager  PaperWriter                   │
    └────────────┬────────────────────────────────┘
                 │
    ┌────────────┴─────────────────┐
    │         Tool Layer           │
    │  LLMClient  SearchClient     │
    │  GitHubClient                │
    └────────────┬─────────────────┘
                 │
    ┌────────────┴─────────────────┐
    │         State Layer          │
    │  memory.md  tasks.md         │
    │  skills.md  paper_draft.md   │
    └──────────────────────────────┘
```

### 模块调用关系

```
main.py → ResearchAgent
  ├── Planner          (uses LLMClient + MemoryManager)
  ├── Researcher       (uses LLMClient + SearchClient + MemoryManager)
  ├── DataCollector    (uses LLMClient + SearchClient + MemoryManager)
  ├── IdeaGenerator    (uses LLMClient + MemoryManager)
  ├── CodeRunner       (uses LLMClient + GitHubClient + MemoryManager)
  ├── Experimenter     (uses LLMClient + CodeRunner + MemoryManager)
  ├── Evaluator        (uses LLMClient + MemoryManager)
  ├── SkillManager     (uses LLMClient + MemoryManager)
  └── PaperWriter      (uses LLMClient + MemoryManager)
```

---

## 项目目录结构

```
MRAG-study/
├── config/
│   └── config.yaml              # 全局配置（模型、API、路径、行为）
├── agent/
│   ├── core/
│   │   ├── agent.py             # 主编排器 / 事件循环
│   │   ├── planner.py           # 任务拆解与优先级调度
│   │   └── memory_manager.py    # memory/tasks/skills/paper 状态管理
│   ├── modules/
│   │   ├── researcher.py        # 文献调研
│   │   ├── data_collector.py    # 数据集收集
│   │   ├── idea_generator.py    # Idea 生成与选择
│   │   ├── code_runner.py       # GitHub 代码查找/克隆/运行/调试
│   │   ├── experimenter.py      # 实验执行与迭代
│   │   ├── evaluator.py         # 结果评估
│   │   ├── skill_manager.py     # Skill 生成/注册/检索/调用
│   │   └── paper_writer.py      # 论文增量写作
│   ├── tools/
│   │   ├── llm_client.py        # 多 Provider LLM 抽象层
│   │   ├── search_client.py     # arXiv / Semantic Scholar / Serper
│   │   └── github_client.py     # GitHub REST API + git 克隆
│   └── utils/
│       ├── logger.py            # 结构化日志 (rotating file + console)
│       └── file_manager.py      # Markdown 状态文件 I/O 工具
├── state/
│   ├── memory.md                # 智能体长期记忆
│   ├── tasks.md                 # 任务状态跟踪
│   ├── skills.md                # 技能注册表
│   └── paper_draft.md           # 论文草稿（持续积累）
├── skills/                      # 生成的可复用 Python 技能脚本
├── workspace/
│   ├── repos/                   # 克隆的 GitHub 仓库
│   └── results/                 # 实验输出日志
├── logs/                        # 运行日志
├── tests/                       # 单元测试
│   ├── test_file_manager.py
│   ├── test_memory_manager.py
│   ├── test_planner.py
│   ├── test_search_client.py
│   ├── test_skill_manager.py
│   └── test_evaluator.py
├── main.py                      # CLI 入口
├── requirements.txt
└── README.md
```

---

## 状态文件说明

### `state/memory.md` — 长期记忆

存放研究过程中需要跨任务保留的关键信息：

| 章节 | 内容 |
|------|------|
| 研究目标 | 当前科研目标 |
| 关键假设 | 当前选定的研究假设 |
| 有效结论 | 实验验证成功的结论 |
| 失败经验 | 失败的实验及教训 |
| 环境配置 | 运行环境与依赖信息 |
| 相关工作调研 | 文献综述结果 |
| 数据集资源 | 可用数据集汇总 |
| 候选 Ideas | 所有生成的研究想法 |
| 当前选定 Idea | 正在验证的想法 |
| GitHub 开源项目 | 找到的相关代码库分析 |

### `state/tasks.md` — 任务跟踪

五类任务状态，每项包含：title | status | owner | depends_on | next_action | updated_at | notes

| 状态 | 说明 |
|------|------|
| 已完成任务 | 全部完成的任务 |
| 进行中任务 | 当前执行中 |
| 未完成任务 | 待执行 (todo) |
| 新增任务 | 动态新增的任务 |
| 阻塞任务 | 因依赖或错误被阻塞 |

### `state/skills.md` — 技能注册表

每个 Skill 条目包含：名称、功能、输入、输出、适用场景、调用方式、依赖、代码位置、更新时间。

### `state/paper_draft.md` — 论文草稿

按章节增量写作，随实验进展持续更新：标题 | 摘要 | 背景 | 相关工作 | 方法 | 实验设置 | 结果分析 | 结论 | 参考文献

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API 密钥

```bash
export OPENAI_API_KEY="sk-..."        # 必须
export GITHUB_TOKEN="ghp_..."         # 推荐（提高 API 速率）
export SEMANTIC_SCHOLAR_API_KEY="..." # 可选
export SERPER_API_KEY="..."           # 可选（Web 搜索）
```

### 3. 启动科研智能体

```bash
python main.py run --goal "Multimodal Retrieval-Augmented Generation for scientific documents" --cycles 3
```

### 4. 查看状态

```bash
python main.py status          # 查看任务状态
python main.py memory          # 查看完整记忆
python main.py paper           # 查看论文草稿
python main.py skills list     # 查看所有技能
```

---

## 配置说明

编辑 `config/config.yaml`：

```yaml
llm:
  provider: openai       # openai | anthropic | deepseek | local
  model: gpt-4o
  api_key_env: OPENAI_API_KEY

human_loop:
  pause_on_key_decision: true   # 在关键决策点暂停等待人工确认
  notification_channel: console # console | email | slack
```

支持的 LLM Provider：

| Provider | 说明 |
|----------|------|
| `openai` | OpenAI GPT-4o/GPT-4 等 |
| `anthropic` | Anthropic Claude |
| `deepseek` | DeepSeek（OpenAI 兼容接口） |
| `local` | 本地模型服务（Ollama、LM Studio 等） |

---

## CLI 命令参考

```bash
# 启动科研循环
python main.py run --goal "YOUR RESEARCH GOAL" [--cycles 3] [--config config/config.yaml]

# 查看任务状态
python main.py status

# 查看记忆（可指定章节）
python main.py memory [--section "研究目标"]

# 查看论文草稿
python main.py paper

# 技能管理
python main.py skills list
python main.py skills find <keyword>
python main.py skills generate --name <name> --description <desc> --inputs <inputs> --outputs <outputs>
python main.py skills call <name>
```

---

## 自动化科研工作流

```
1. 明确研究总目标
       ↓
2. LLM 拆解任务 → tasks.md
       ↓
3. 文献调研 (arXiv + SS + Web) → memory.md 相关工作
       ↓
4. 数据集收集 → memory.md 数据集资源
       ↓
5. 论文：背景章节 + 相关工作章节
       ↓
6. Idea 生成 (3–5 个候选) → 人工确认选定
       ↓
7. GitHub 项目搜索 / 克隆 / 分析
       ↓
8. 基线实验运行
       ↓
9. LLM 生成代码修改 → 实验执行 (最多 max_iter 次自动重试)
       ↓
10. 论文：方法 + 实验设置 章节
       ↓
11. 结果评估 → 假设验证 → 结论存入 memory.md
       ↓
12. 论文：结果分析章节
       ↓
13. 是否满足论文质量？→ 否：回到步骤6（下一 cycle）
                       → 是：继续
       ↓
14. 论文：结论与展望 + 摘要 + 标题建议
       ↓
15. 完整 paper_draft.md ✓
```

---

## 人机协作机制

系统在以下情况主动暂停并通知操作者：

| 触发条件 | 系统行为 |
|----------|----------|
| 需要外部授权 | 打印通知，记录到 memory.md，等待 |
| 关键 Idea 选定前 | 展示候选列表，等待确认或修改意见 |
| 无法找到可用代码库 | 提示提供仓库地址 |
| 实验多次失败 | 将任务标记为 blocked，通知人工介入 |
| 未处理异常 | 记录错误，任务状态设为 blocked，可重新运行继续 |

**中断恢复**：所有状态持久化在 `state/` 目录。中断后直接重新运行 `python main.py run`，系统会基于已有 `tasks.md` 和 `memory.md` 继续推进，不会重新开始。

---

## 开发路线图

### v0.1（当前）
- [x] 系统架构设计与核心模块实现
- [x] LLM 多 Provider 抽象（OpenAI / Anthropic / DeepSeek / Local）
- [x] 文献调研 (arXiv / Semantic Scholar)
- [x] 任务拆解与状态管理（memory.md / tasks.md）
- [x] Skill 生成、注册、检索、动态调用
- [x] 论文增量写作（按章节）
- [x] 人机协作接口（console 通知 + 暂停恢复）
- [x] 完整测试套件 (46 tests)

### v0.2（近期）
- [ ] Email / Slack 通知 channel 实现
- [ ] 向量数据库支持（FAISS / ChromaDB）用于 Skill 语义检索
- [ ] 多 Agent 并行（文献调研 + 代码复现同步进行）
- [ ] 实验结果可视化（图表自动生成）

### v0.3（中期）
- [ ] 论文 LaTeX 自动排版导出
- [ ] 支持 PDF 论文输入与解析
- [ ] Fine-tuning 数据构建 Skill
- [ ] Web UI 监控面板

---

## 许可证

MIT
