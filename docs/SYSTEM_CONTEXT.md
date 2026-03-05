# Notion Dump System Context

## 1. 系统宏观架构 (System Architecture)

系统本质是一个**双向同步的数字资产管理与 AI 助理**。它将 Notion 作为核心数据源，通过 ETL 流程转化为本地 Markdown 资产，利用 LLM 进行深度分析与指标提取，最终通过 Telegram 形成人机交互闭环。

### 核心数据流 (Core Data Flow)
1.  **Ingest (摄取)**: `SyncNotionJob` 定时从 Notion API 拉取变更页面（Incremental Sync），通过 `NotionToMarkdown` 转换为带有 YAML Frontmatter 的标准 Markdown 文件，存储于 `notion_output/`。
2.  **Analyze (ETL 指标抽取)**: `AnalyzeNotesJob` 监听变更文件，仅对日记类文档进行客观指标抽取（`daily_metrics`），并 Upsert 写入 `notion_output/metrics.jsonl`。该阶段不生成主观总结/简报。
3.  **Review (苏格拉底提问引擎 / The Guardian)**: `PeriodicReviewJob` 作为“终极意图守护者”，接管所有日/周/月度回顾的生成逻辑：在指定日期范围内读取日记 Markdown + 过滤 `metrics.jsonl` 区间数据，组装为 `Profile / Metrics / Raw Notes` 三块上下文，调用 LLM 输出**冷峻、极简、以提问为武器**的报告到 `_reports/`（禁止流水账总结与鸡汤建议）。
4.  **Backup (备份)**: `run_task.sh` 在任务完成后，触发 Rclone 将核心数据（State, Config, Output, Reports）同步至云端存储 (Google Drive)。
5.  **Interact (交互)**:
    - **主动推送**: `DailyRoutines` 基于 Crontab 定时触发，调用统一回顾引擎生成 `daily/weekly` 回顾 Markdown，并通过 Telegram 推送。
    - **被动响应**: `TelegramBotRunner` (Daemon) 监听用户消息，检索知识库上下文，并具备 **Tool Use (工具调用)** 能力，可执行本地函数（如记录体重、心情等），提供个性化问答服务。

## 2. 核心模块拓扑 (Module Topology)

### 入口与调度 (Entry & Orchestration)
-   **`main.py`**: 统一 CLI 入口，支持 `sync` (同步+可选指标抽取), `analyze` (仅指标抽取), `review` (生成回顾报告并存盘，支持 daily/weekly/monthly/custom), `bot` (启动对话服务), `morning/weekly` (生成对应回顾并推送 Telegram) 等指令。
-   **`deploy/run_task.sh`**: 生产环境执行包装器。负责：1. `git pull` 自动更新代码；2. 激活 venv；3. 执行 `main.py`；4. 执行 Rclone 备份；5. 进程锁管理。
-   **`deploy/manage.sh`**: 交互式运维工具，用于管理 Crontab 调度和 Systemd 服务。

### 核心作业 (Core Jobs - `app/jobs/`)
-   **`sync_notion.py`**: 处理 Notion 数据同步。维护 `.notion-dump-state.json` 记录上次同步时间，支持递归下载 Page/Database，处理父子关系映射。
-   **`analyze_notes.py`**: 指标 ETL 引擎。读取变更的 Markdown，仅抽取 `daily_metrics` 并 Upsert 到 `notion_output/metrics.jsonl`。
-   **`periodic_review.py`**: 苏格拉底提问引擎 (The Guardian)。支持 `daily/weekly/monthly/custom` 回顾类型：自动推算日期范围（非 custom），在区间内读取日记与 `metrics.jsonl`，通过 `PromptManager.build_socratic_review_prompt()` 组装 prompt，生成符合固定结构的 Markdown 报告并输出到 `_reports/{review_type}_{end_date}.md`。
-   **`bot_runner.py`**: Telegram Bot 守护进程。由 Systemd 托管，基于 Long Polling 监听消息，维护对话上下文，并集成 `app/skills/` 实现 Agentic 行为。
-   **`routines.py`**: 轻量分发层。执行 `morning/weekly` 时调用统一回顾引擎生成 Markdown，并通过 `TelegramService` 推送消息。

### 技能与工具库 (Skills & Tools - `app/skills/`)
-   **`metrics_skill.py`**: 量化指标管理技能。提供 `upsert_daily_metric` 函数，支持通过自然语言对话记录体重、精力值、睡眠等数据，自动更新 `metrics.jsonl`。

### 基础服务 (Infrastructure Services - `app/services/`)
-   **`notion_service.py`**: Notion API 客户端。封装分页 (Pagination)、搜索 (Search)、块获取 (Get Blocks) 及数据库解析逻辑。
-   **`llm_service.py`**: LLM 交互网关。封装 OpenAI-Compatible 接口，提供 `ask_json` (结构化输出) 和 `ask_text` 能力，统一处理 System Prompt；支持通过 `AI_NUM_CTX`（仅本地 OpenAI-Compatible 网关）配置更大的上下文窗口。
-   **`telegram_service.py`**: 消息推送服务。仅负责单向发送 (Send Message)。
-   **`prompt_manager.py`**: 提示词工程管理。维护“苏格拉底回顾” System/User Prompt（`SOCRATIC_REVIEW_SYSTEM_PROMPT` / `SOCRATIC_REVIEW_USER_PROMPT`），并提供 `build_socratic_review_prompt(profile, metrics_trend, notes_content)` 生成 messages；日记判定逻辑由 `ContextFetcher.is_daily_entry` 统一提供。

### 工具链 (Utilities - `app/utils/`)
-   **`notion_converter.py`**: 核心转换器。负责 Notion Block -> Markdown 的渲染，以及 Page Properties -> YAML Frontmatter 的映射。
-   **`context_fetcher.py`**: 上下文组装器。负责读取本地文件 (`metrics.jsonl`, `_reports/`, `profile.yaml`) 并进行时区本地化处理，为 AI 提供短期记忆；同时提供 Frontmatter 解析与日记判定（`is_daily_entry`）。

## 3. 核心数据契约 (Data Schemas)

### Notion Markdown 结构 (`notion_output/*.md`)
文件名为 Notion Page UUID，内容包含 YAML Frontmatter 和正文。
```markdown
---
id: "UUID"
title: "Page Title"
created_time: "ISO8601 UTC"
last_edited_time: "ISO8601 UTC"
url: "Notion URL"
# 其他自定义属性自动映射为 snake_case
tags: ["tag1", "tag2"]
status: "Done"
---

# Page Title

[Markdown Content...]
```

### 回顾报告 (`_reports/{review_type}_{end_date}.md`)
由统一回顾引擎 `PeriodicReviewJob` 生成的回顾报告，输出为 Markdown。
- `review_type ∈ {daily, weekly, monthly, custom}`
- `end_date` 为本地日期（以 `profile.yaml -> preferences.timezone` 为准）
- `daily/weekly/monthly` 由引擎自动推算日期范围；`custom` 必须由 CLI 传入 `start_date/end_date`
- 日记筛选时会将本地日期范围转换为 UTC，再与 Frontmatter 的 `created_time` 比对
报告输出必须严格遵循固定结构（禁止额外寒暄）：
```markdown
## 1. 冰冷的镜像 (The Objective Mirror)

## 2. 偏离警告 (The Guardian's Alert)

## 3. 灵魂拷问 (Socratic Questions)
```

### 量化指标 (`notion_output/metrics.jsonl`)
由 AI 从日记或记录中提取，用于长期趋势分析。支持基于 `source` 或 `date` 的 Upsert。主键 (Primary Key): source (兜底策略为 date)
```json
{
  "date": "2026-02-24",            // 业务发生日期 (Local Time)
  "source": "UUID.md",             // 数据来源文件
  "weight": 76.0,                  // 体重 (kg)
  "energy_level": 7,               // 精力值 (1-10)
  "sleep_quality": "normal",       // 睡眠质量
  "workout_volume_score": 8,       // 训练容量评分
  "mood_tag": "thoughtful",        // 情绪标签
  "timestamp": "2026-02-24T12:00:00Z" // 记录生成时间 (UTC)
}
```

### 用户画像 (`config/profile.yaml`)
系统的静态知识库，用于控制 AI 的人设和回答策略。
```yaml
name: "User Name"
physical_baseline:
  primary_goals: "健身目标描述"
  weekly_routine:
    pattern: "训练计划模式 (e.g., PPL)"
preferences:
  timezone: "Asia/Shanghai"  # 核心时区配置
  language: "zh-CN"
```

## 4. 关键演进约定 (Evolution Rules)

1.  **时区策略 (Timezone Policy)**:
    -   **存储层**: 所有机器生成的时间戳（Log, History, Metadata）一律使用 **UTC**。
    -   **展示层**: 所有与 LLM 交互 (Prompt Context) 和用户展示 (Telegram Message) 的时间，必须根据 `profile.yaml` 中的 `timezone` 动态转换为本地时间。
    -   **筛选层**: 所有基于“本地日期”的筛选（如周期性回顾的 `start-date/end-date`），必须先转换为 UTC 范围，再与 `created_time` 比对。

2.  **同步机制 (Sync Strategy)**:
    -   采用 **Incremental Sync** (增量同步)，仅拉取 `last_edited_time > last_sync_time` 的页面。
    -   状态文件 `.notion-dump-state.json` 是唯一的事实来源 (Source of Truth)。

3.  **数据备份 (Data Resilience)**:
    -   采用 **Stateful Sync** (状态同步) 策略备份到 Rclone。
    -   `deploy/run_task.sh` 是原子操作单元，必须保证 "Code Update -> Execution -> Backup" 的顺序执行。

4.  **AI 交互 (AI Interaction)**:
    -   **职责边界**: 所有“回顾输出”统一收敛到 `PeriodicReviewJob`；`AnalyzeNotesJob` 仅做客观指标抽取与落盘，避免重复实现与 prompt 分叉。
    -   **输出约束**: 回顾任务禁止输出流水账总结与情绪安慰；只允许以“事实镜像 + 偏离警告 + 苏格拉底式尖锐问题”逼迫用户校准终极意图与行动轨迹。
    -   **Structured Output**: 指标抽取任务必须强制要求 JSON 格式输出，以保证下游数据处理的稳定性。
    -   **Action Boundaries (动作边界)**: Agent 仅允许通过 `app/skills/` 目录下的明确定义的函数执行副作用操作（如文件写入）。所有写操作必须具备幂等性（Idempotency），防止重复调用导致数据污染。
    -   **Tool Use (工具调用)**: 考虑到大模型（如 Gemini Flash）存在“口头答应（Action Hallucination）”的惰性，System Prompt 中必须包含强烈的执行约束（如：“绝对禁止口头答应，必须且只能调用工具”），以强制 LLM 走 Tool Calling 链路，确保数据的真实落地。
