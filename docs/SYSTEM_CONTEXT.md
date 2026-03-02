# Notion Dump System Context

## 1. 系统宏观架构 (System Architecture)

系统本质是一个**双向同步的数字资产管理与 AI 助理**。它将 Notion 作为核心数据源，通过 ETL 流程转化为本地 Markdown 资产，利用 LLM 进行深度分析与指标提取，最终通过 Telegram 形成人机交互闭环。

### 核心数据流 (Core Data Flow)
1.  **Ingest (摄取)**: `SyncNotionJob` 定时从 Notion API 拉取变更页面（Incremental Sync），通过 `NotionToMarkdown` 转换为带有 YAML Frontmatter 的标准 Markdown 文件，存储于 `notion_output/`。
2.  **Analyze (分析)**: `AnalyzeNotesJob` 监听变更文件，调用 LLM (OpenAI Compatible) 分析内容，提取结构化指标（Metrics）与非结构化洞察（Insights），生成 `metrics.jsonl` 和每日报告 (`_reports/`)。
3.  **Backup (备份)**: `run_task.sh` 在任务完成后，触发 Rclone 将核心数据（State, Config, Output, Reports）同步至云端存储 (Google Drive)。
4.  **Interact (交互)**:
    - **主动推送**: `DailyRoutines` 基于 Crontab 定时触发，聚合 `profile.yaml`、近期 Metrics 和 Report，通过 Telegram 推送晨间问候与周报。
    - **被动响应**: `TelegramBotRunner` (Daemon) 监听用户消息，检索知识库上下文，提供个性化问答服务。

## 2. 核心模块拓扑 (Module Topology)

### 入口与调度 (Entry & Orchestration)
-   **`main.py`**: 统一 CLI 入口，支持 `sync` (同步+分析), `analyze` (仅分析), `bot` (启动对话服务), `morning/weekly` (例行任务) 等指令。
-   **`deploy/run_task.sh`**: 生产环境执行包装器。负责：1. `git pull` 自动更新代码；2. 激活 venv；3. 执行 `main.py`；4. 执行 Rclone 备份；5. 进程锁管理。
-   **`deploy/manage.sh`**: 交互式运维工具，用于管理 Crontab 调度和 Systemd 服务。

### 核心作业 (Core Jobs - `app/jobs/`)
-   **`sync_notion.py`**: 处理 Notion 数据同步。维护 `.notion-dump-state.json` 记录上次同步时间，支持递归下载 Page/Database，处理父子关系映射。
-   **`analyze_notes.py`**: AI 分析引擎。读取变更的 Markdown，使用 `PromptManager` 组装 Prompt，调用 LLM 提取 `metrics.jsonl` 并生成每日简报。
-   **`bot_runner.py`**: Telegram Bot 守护进程。由 Systemd 托管，基于 Long Polling 监听消息，维护对话上下文。
-   **`routines.py`**: 业务编排层。组合 `ContextFetcher` 和 `LLMService`，生成高度定制化的晨报（含训练建议）和周报。

### 基础服务 (Infrastructure Services - `app/services/`)
-   **`notion_service.py`**: Notion API 客户端。封装分页 (Pagination)、搜索 (Search)、块获取 (Get Blocks) 及数据库解析逻辑。
-   **`llm_service.py`**: LLM 交互网关。封装 OpenAI 接口，提供 `ask_json` (结构化输出) 和 `ask_text` 能力，统一处理 System Prompt。
-   **`telegram_service.py`**: 消息推送服务。仅负责单向发送 (Send Message)。
-   **`prompt_manager.py`**: 提示词工程管理。根据文件类型（日记 vs 文章）和用户画像 (`profile.yaml`) 动态构建 Prompt。

### 工具链 (Utilities - `app/utils/`)
-   **`notion_converter.py`**: 核心转换器。负责 Notion Block -> Markdown 的渲染，以及 Page Properties -> YAML Frontmatter 的映射。
-   **`context_fetcher.py`**: 上下文组装器。负责读取本地文件 (`metrics.jsonl`, `_reports/`, `profile.yaml`) 并进行时区本地化处理，为 AI 提供短期记忆。

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

2.  **同步机制 (Sync Strategy)**:
    -   采用 **Incremental Sync** (增量同步)，仅拉取 `last_edited_time > last_sync_time` 的页面。
    -   状态文件 `.notion-dump-state.json` 是唯一的事实来源 (Source of Truth)。

3.  **数据备份 (Data Resilience)**:
    -   采用 **Stateful Sync** (状态同步) 策略备份到 Rclone。
    -   `deploy/run_task.sh` 是原子操作单元，必须保证 "Code Update -> Execution -> Backup" 的顺序执行。

4.  **AI 交互 (AI Interaction)**:
    -   **Context Hydration**: 在分析单篇文档时，必须注入其引用的其他文档片段（Reference Hydration），以提供上下文。
    -   **Structured Output**: 核心分析任务必须强制要求 JSON 格式输出，以保证下游数据处理的稳定性。
