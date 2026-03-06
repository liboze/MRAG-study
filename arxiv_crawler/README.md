# arXiv 论文爬取工具

一个生产级、高可用的 arXiv 论文爬取脚本，支持关键词搜索和今日新提交两种模式，输出结构化 Excel 文件（含中文翻译版），并完全遵守 arXiv 访问政策。

---

## 功能特性

- **两种爬取模式**
  - **模式一（search）**：按关键词 + 日期范围搜索，过滤标题/摘要包含指定关键词的论文
  - **模式二（today）**：爬取当天 arXiv 新提交的论文，支持按类别筛选

- **双语 Excel 输出**
  - 英文原版（`arxiv_papers_en_*.xlsx`）
  - 中文翻译版（`arxiv_papers_zh_*.xlsx`），默认使用 Google Translate，可切换 OpenAI

- **合规与健壮性**
  - User-Agent 轮换、请求频率限制、指数退避重试
  - 遵守 arXiv API 服务条款（包含 `From` 请求头）
  - 完善的异常处理和日志系统

---

## 目录结构

```
arxiv_crawler/
├── arxiv_crawler.py          # 主入口与 CLI
├── crawler/
│   ├── __init__.py
│   ├── api_crawler.py        # 模式一：关键词+日期搜索
│   ├── page_crawler.py       # 模式二：今日新提交论文
│   └── utils.py              # 公共工具（UA轮换/限速/重试）
├── translator/
│   ├── __init__.py
│   ├── base.py               # 翻译器抽象基类
│   ├── google_translator.py  # Google Translate 实现
│   └── openai_translator.py  # OpenAI 翻译实现
├── exporter/
│   ├── __init__.py
│   └── excel_exporter.py     # Excel 导出（EN + ZH）
├── requirements.txt          # 依赖列表
└── README.md                 # 本文档
```

---

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/liboze/MRAG-study.git
cd MRAG-study
```

### 2. 安装依赖

```bash
pip install -r arxiv_crawler/requirements.txt
```

### 3. 验证安装

```bash
cd arxiv_crawler
python arxiv_crawler.py --help
```

---

## 使用方法

所有命令均在 `arxiv_crawler/` 目录下运行：

```bash
cd arxiv_crawler
```

### 模式一：关键词 + 日期范围搜索

```bash
# 基本用法：搜索 2025 年以来包含 "RAG" 关键词的论文
python arxiv_crawler.py search --start-date 2025-01-01 --keywords "RAG"

# 多个关键词（OR 逻辑）
python arxiv_crawler.py search --start-date 2025-01-01 \
    --keywords "RAG" "retrieval augmented generation" "multimodal"

# 指定输出目录和请求延迟
python arxiv_crawler.py search --start-date 2025-03-01 \
    --keywords "LLM" "large language model" \
    --output-dir ./my_papers \
    --delay 5

# 使用 OpenAI 翻译
python arxiv_crawler.py search --start-date 2025-01-01 \
    --keywords "LLM" \
    --translator openai \
    --api-key sk-your-key-here

# dry-run：仅预览，不实际下载
python arxiv_crawler.py search --start-date 2025-01-01 \
    --keywords "RAG" --dry-run
```

### 模式二：今日新提交论文

```bash
# 爬取默认类别（cs, stat, eess, math）的今日论文
python arxiv_crawler.py today

# 指定类别
python arxiv_crawler.py today --categories cs stat

# 爬取特定子类别
python arxiv_crawler.py today --categories cs.LG cs.CL cs.CV

# 不翻译（只生成英文版 Excel）
python arxiv_crawler.py today --translator none

# dry-run
python arxiv_crawler.py today --dry-run
```

---

## 配置选项

### 通用参数（所有命令适用）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--output-dir` | `./arxiv_output` | 输出目录 |
| `--delay` | `3.0` | 请求间隔秒数（建议 ≥ 3，遵守 arXiv 政策） |
| `--email` | 无 | 联系邮箱（写入 HTTP From 头，arXiv 推荐） |
| `--translator` | `google` | 翻译后端：`google` / `openai` / `none` |
| `--api-key` | 无 | OpenAI API Key（`--translator openai` 时必填） |
| `--openai-model` | `gpt-3.5-turbo` | OpenAI 模型名称 |
| `--openai-base-url` | 无 | OpenAI 自定义 API 端点（可选） |
| `--log-level` | `INFO` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--dry-run` | 否 | 仅预览操作，不实际爬取 |

### `search` 子命令专属参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--start-date` | 必填 | 搜索起始日期（`YYYY-MM-DD` 格式） |
| `--keywords` | 必填 | 搜索关键词（一个或多个） |
| `--max-results` | `500` | 最大返回论文数 |

### `today` 子命令专属参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--categories` | `cs stat eess math` | arXiv 类别列表 |

---

## 输出文件说明

输出目录结构：

```
arxiv_output/
└── 2025-03-06/                          # 按爬取日期分目录
    ├── arxiv_papers_en_20250306_120000.xlsx   # 英文原版
    ├── arxiv_papers_zh_20250306_120000.xlsx   # 中文翻译版
    └── raw/
        └── arxiv_papers_raw_20250306_120000.json  # 原始 JSON 数据
```

### 英文版 Excel 列说明

| 列名 | 说明 |
|------|------|
| Crawl Time | 爬取时间 |
| Search Keywords | 搜索关键词（或类别） |
| Published Date | 论文发表日期 |
| Title | 论文标题 |
| Authors | 作者列表（分号分隔） |
| Affiliations | 作者机构（arXiv 通常不提供，标记"未提供"） |
| Abstract | 摘要 |
| arXiv ID | arXiv 唯一标识符 |
| PDF Link | PDF 下载链接 |

### 中文版 Excel 列说明

列名为中文（`爬取时间`、`搜索关键词`、`论文发表时间`、`标题`、`作者`、`作者机构`、`摘要`、`arXiv ID`、`PDF链接`），其中标题、作者机构、摘要字段翻译为中文。

---

## 常见问题

### 1. 安装 `fake-useragent` 时报错

`fake-useragent` 不是必需的，若安装失败，程序会自动回退到内置 User-Agent 池：

```bash
pip install fake-useragent --ignore-requires-python
# 或直接跳过，不影响使用
```

### 2. Google 翻译失败

- 检查网络连接是否可以访问 Google 服务
- 短时间内请求过多可能触发频率限制，尝试增大 `--delay`
- 可切换到 `--translator openai` 使用 OpenAI API

### 3. 爬取结果为空

- 确认日期范围合理（arXiv 按 UTC 时间发布，今日论文可能在下午才出现）
- 尝试更宽泛的关键词
- 使用 `--log-level DEBUG` 查看详细请求信息

### 4. `ModuleNotFoundError`

确保在正确的目录下运行，并已安装所有依赖：

```bash
cd arxiv_crawler
pip install -r requirements.txt
python arxiv_crawler.py --help
```

### 5. Excel 文件打不开

确保已安装 `openpyxl`：

```bash
pip install openpyxl>=3.1.0
```

---

## arXiv API 使用条款

本工具遵守 [arXiv API 使用条款](https://arxiv.org/help/api/tou)：

- 请求间隔不低于 3 秒（默认设置）
- 建议在 `--email` 参数中提供联系邮箱
- 不用于商业目的
- 请注明数据来源为 arXiv

---

## 运行环境

- Python 3.8+
- 依赖见 `requirements.txt`

---

## License

本项目基于 MIT License 开源。
