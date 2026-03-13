# ChronoFold System Context

## 1. 系统宏观架构 (System Architecture)

系统本质是一个**双向同步的数字资产管理与 AI 助理**。它将 Notion 作为核心数据源，通过 ETL 流程转化为本地 Markdown 资产，利用 LLM 进行深度分析与指标提取，最终通过 Telegram 形成人机交互闭环。

### 核心数据流 (Core Data Flow)
1.  **Ingest (摄取)**: `SyncNotionJob` 定时从 Notion API 拉取变更页面（Incremental Sync），通过 `NotionToMarkdown` 转换为带有 YAML Frontmatter 的标准 Markdown 文件，存储于 `notion_output/`。
2.  **Analyze (ETL 指标抽取)**: `AnalyzeNotesJob` 监听变更文件，仅对日记类文档进行客观指标抽取（`daily_metrics`），并 Upsert 写入 `notion_output/metrics.jsonl`。该阶段不生成主观总结/简报。
3.  **Portfolio Sync (投资组合客观指标)**: `PortfolioSyncJob` 读取 `config/profile.yaml` 中的静态持仓（ticker/currency/stock_count），通过 `yfinance` 拉取价格与汇率，计算当日权益总市值（CNY），并 Upsert 写入 `notion_output/metrics.jsonl`，为“投资偏离警告”提供硬数据底座。
4.  **Review (苏格拉底提问引擎 / The Guardian)**: `PeriodicReviewJob` 作为“终极意图守护者”，接管所有日/周/月度回顾的生成逻辑：在指定日期范围内读取日记 Markdown + 过滤 `metrics.jsonl` 区间数据，组装为 `Profile / Metrics / Raw Notes` 三块上下文，调用 LLM 输出**冷峻、极简、以提问为武器**的报告到 `_reports/`（禁止流水账总结与鸡汤建议）。
5.  **Backup (备份)**: `run_task.sh` 在任务完成后，触发 Rclone 将核心数据（State, Config, Output, Reports）同步至云端存储 (Google Drive)。
6.  **Interact (交互)**:
    - **主动推送**: `DailyRoutines` 基于 Crontab 定时触发，调用统一回顾引擎生成 `daily/weekly` 回顾 Markdown，并通过 Telegram 推送。
    - **被动响应**: `TelegramBotRunner` (Daemon) 监听用户消息，检索知识库上下文，并具备 **Tool Use (工具调用)** 能力：
        - **客观指标**: 通过 `metrics_skill.upsert_daily_metric` 将量化数据写入 `notion_output/metrics.jsonl`。
        - **动态画像演进 (Profile Evolution)**: 通过 `update_profile_skill.update_profile_attribute` 修改 `config/profile.yaml` 的可演进字段，并将每次变更追加写入 `notion_output/profile_changelog.jsonl` 作为审计与认知演化日志。

## 2. 核心模块拓扑 (Module Topology)

### 入口与调度 (Entry & Orchestration)
-   **`main.py`**: 统一 CLI 入口，支持 `sync` (同步+可选指标抽取), `analyze` (仅指标抽取), `review` (生成回顾报告并存盘，支持 daily/weekly/monthly/custom), `portfolio` (同步资产负债表并写入净资产指标), `bot` (启动对话服务), `morning/weekly` (生成对应回顾并推送 Telegram) 等指令。
-   **`deploy/run_task.sh`**: 生产环境执行包装器。负责：1. `git pull` 自动更新代码；2. 激活 venv；3. 执行 `main.py`；4. 执行 Rclone 备份；5. 进程锁管理。
-   **`deploy/manage.sh`**: 交互式运维工具，用于管理 Crontab 调度和 Systemd 服务；并提供资产负债表/持仓估值查看，以及 Portfolio Sync 的定时任务管理入口。

### 核心作业 (Core Jobs - `app/jobs/`)
-   **`sync_notion.py`**: 处理 Notion 数据同步。维护 `.chronofold-state.json` 记录上次同步时间，支持递归下载 Page/Database，处理父子关系映射。
-   **`analyze_notes.py`**: 指标 ETL 引擎。读取变更的 Markdown，仅抽取 `daily_metrics` 并 Upsert 到 `notion_output/metrics.jsonl`。
-   **`net_worth_sync_job.py`**: 净资产同步作业。读取画像中的 `balance_sheet_structure`（静态资产/现金/股票/期权/负债），拉取行情与汇率，生成当日 `net_worth_cny / total_assets_cny / total_liabilities_cny / liquid_assets_cny` 并 Upsert 写入 `metrics.jsonl`（幂等覆盖当日记录）。
-   **`periodic_review.py`**: 苏格拉底提问引擎 (The Guardian)。支持 `daily/weekly/monthly/custom` 回顾类型：自动推算日期范围（非 custom），在区间内读取日记与 `metrics.jsonl`，通过 `PromptManager.build_review_prompt()` 组装 prompt，生成符合固定结构的 Markdown 报告并输出到 `_reports/{review_type}_{end_date}.md`。
-   **`bot_runner.py`**: Telegram Bot 守护进程。由 Systemd 托管，基于 Long Polling 监听消息，维护对话上下文，并集成 `app/skills/` 实现 Agentic 行为。
-   **`routines.py`**: 轻量分发层。执行 `morning/weekly` 时调用统一回顾引擎生成 Markdown，并通过 `TelegramService` 推送消息。

### 维护工具 (Ops CLI - `app/cli/`)
-   **`balance_sheet.py`**: 运维查看工具。读取 `config/profile.yaml` 输出资产负债表结构；可选拉取 `yfinance` 实时价格与 `XXCNY=X` 汇率，计算并展示持仓的实时 CNY 估值。

### 技能与工具库 (Skills & Tools - `app/skills/`)
-   **`metrics_skill.py`**: 量化指标管理技能。提供 `upsert_daily_metric` 函数，支持通过自然语言对话记录体重、精力值、睡眠等数据，自动更新 `metrics.jsonl`。
-   **`update_profile_skill.py`**: Profile 动态更新技能。提供 `update_profile_attribute(yaml_path, new_value, reason, category)`：使用点语法定位并更新画像字段；对静态锁定字段强制拒绝；写回后追加审计日志到 `profile_changelog.jsonl`。
-   **`update_portfolio_skill.py`**: 投资交易记录与资产负债表更新技能。提供 `log_portfolio_transaction(ticker, action, price, quantity, cash_impact, currency, notes)`：先写入 Notion Portfolio Ledger，再以**双分录**方式原子更新 `config/profile.yaml` 中的 `stock_count` 与 `checking account` 余额（BUY 扣现金加股票；SELL 加现金减股票；DIVIDEND 只加现金）；随后为该交易 Page 追加一段“交易快照”正文（来自 `config/templates/trade_snapshot_log.md`，并自动填充部分字段，如成交均价、仓位变动股数、恒生科技指数当日表现等）。成功后向 `profile_changelog.jsonl` 追加审计事件（股票与现金可能各一条）。

### 基础服务 (Infrastructure Services - `app/services/`)
-   **`notion_service.py`**: Notion API 客户端。封装分页 (Pagination)、搜索 (Search)、块获取 (Get Blocks) 及数据库解析逻辑；并提供 Inbox 写入能力（`append_to_inbox`），通过 `POST /v1/pages` 在 `NOTION_INBOX_DATABASE_ID` 下创建 Page，将文本作为段落 blocks 写入。
-   **`chat_log_service.py`**: 对话日志服务。封装 `NotionService` 的 `append_to_daily_chat_log` 能力，提供统一的对话日志写入入口，供 `TelegramService` 和 `BotRunner` 调用。
-   **`llm_service.py`**: LLM 交互网关。封装 OpenAI-Compatible 接口，提供 `ask_json` (结构化输出) 和 `ask_text` 能力，统一处理 System Prompt；支持通过 `AI_NUM_CTX`（仅本地 OpenAI-Compatible 网关）配置更大的上下文窗口。
-   **`telegram_service.py`**: 消息推送服务。负责单向发送 (Send Message)，并调用 `ChatLogService` 记录 Bot 发送的消息。
-   **`prompt_manager.py`**: 提示词工程管理与“System Prompt 单一入口”。集中管理各条链路的 system/user prompt 组装与 persona 范围：周期性回顾（含 `SOUL.md` 拼接）、日记指标抽取（JSON）、Telegram Bot（Tool Use 约束，含 `SOUL.md` 拼接）、训练计划等；对外提供 `build_review_prompt(...)`、`build_metrics_extraction_prompts(...)`、`build_telegram_bot_messages(...)`、`build_workout_plan_prompts(...)` 等统一接口，避免 prompt 文案散落在 Job 中；日记判定逻辑由 `ContextFetcher.is_daily_entry` 统一提供。

### 工具链 (Utilities - `app/utils/`)
> **复用原则 (Reuse Principles)**:
> 1. **优先复用**: 在实现新功能时，优先检查 `app/utils/` 是否已有现成工具（特别是 ID 处理、时区、文本切分、Frontmatter 解析）。
> 2. **纯函数优先**: 工具类函数应尽量设计为无副作用的纯函数（Pure Functions），便于测试和复用。
> 3. **避免逻辑漂移**: 核心业务逻辑（如“如何判定一篇文档是日记”）应收敛在 `app/utils` 或 `app/services` 中，避免在多个 Job 中重复实现导致规则不一致。

-   **`notion_converter.py`**: 核心转换器。负责 Notion Block -> Markdown 的渲染，以及 Page Properties -> YAML Frontmatter 的映射。
-   **`context_fetcher.py`**: 上下文组装器。负责读取本地文件 (`metrics.jsonl`, `_reports/`, `profile.yaml`) 并进行时区本地化处理，为 AI 提供短期记忆。
-   **`plain.py`**: 通用数据清洗工具。提供 `to_plain` 函数，递归将 ruamel.yaml 对象转换为原生 Python dict/list。
-   **`notion_ids.py`**: ID 标准化工具。提供 `normalize_uuid` 函数，统一 Notion UUID 格式（带横杠）。
-   **`notion_meta.py`**: 元数据提取工具。提供 `extract_title` 和 `get_page_meta` 函数，从 Notion 对象中提取关键信息。
-   **`timezone_utils.py`**: 时区管理工具。提供 `load_profile_timezone` 函数，统一从 `profile.yaml` 加载用户时区配置。
-   **`frontmatter.py`**: Frontmatter 解析工具。提供 `parse_frontmatter` 函数，统一解析 Markdown YAML 头。
-   **`text_chunking.py`**: 文本切分工具。提供 `split_text_by_length` (Notion) 和 `split_text_smart` (Telegram) 两种切分策略。
-   **`jsonl_kv_store.py`**: JSONL 存储工具。提供 `upsert_jsonl` 函数，支持基于键值的增量写入。

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
系统的画像与偏好单一事实来源（Source of Truth），用于控制 AI 的认知基调与回答策略；其中一部分字段允许在 Telegram 对话中随时演进。
```yaml
name: "User Name"
physical_baseline:
  primary_goals: "健身目标描述"
  weekly_routine:
    pattern: "训练计划模式 (e.g., PPL)"
preferences:
  timezone: "Asia/Shanghai"  # 核心时区配置
  language: "zh-CN"

# ---------------------------------------------------------
# 动态特征与认知补丁区 (由 AI 自动维护)
# ---------------------------------------------------------
custom_traits:
  # anti_procrastination_trigger: "面对复杂配置容易陷入情绪内耗"
```

### Profile 演化日志 (`notion_output/profile_changelog.jsonl`)
每次通过 `update_profile_attribute` 成功写回 `profile.yaml` 后，必须追加一条 JSONL 记录（UTC 时间戳），用于追踪用户目标、偏好与认知的演变过程。
此外，投资交易工具在更新 `balance_sheet_structure` 时也会写入该日志：若同时影响股票持仓与现金余额，会追加两条审计事件。
```json
{
  "timestamp": "2026-03-06T12:00:00Z",
  "yaml_path": "recent_focus.weekly_goal",
  "old_value": "搞定本地模型部署",
  "new_value": "去徒步，远离电子屏幕",
  "reason": "用户意识到过度关注技术细节导致精力崩溃",
  "source": "Telegram Bot"
}
```

## 4. 关键演进约定 (Evolution Rules)

1.  **时区策略 (Timezone Policy)**:
    -   **存储层**: 所有机器生成的时间戳（Log, History, Metadata）一律使用 **UTC**。
    -   **展示层**: 所有与 LLM 交互 (Prompt Context) 和用户展示 (Telegram Message) 的时间，必须根据 `profile.yaml` 中的 `timezone` 动态转换为本地时间。
    -   **筛选层**: 所有基于“本地日期”的筛选（如周期性回顾的 `start-date/end-date`），必须先转换为 UTC 范围，再与 `created_time` 比对。

2.  **同步机制 (Sync Strategy)**:
    -   采用 **Incremental Sync** (增量同步)，仅拉取 `last_edited_time > last_sync_time` 的页面。
    -   状态文件 `.chronofold-state.json` 是唯一的事实来源 (Source of Truth)。

3.  **数据备份 (Data Resilience)**:
    -   采用 **Stateful Sync** (状态同步) 策略备份到 Rclone。
    -   `deploy/run_task.sh` 是原子操作单元，必须保证 "Code Update -> Execution -> Backup" 的顺序执行。

4.  **AI 交互 (AI Interaction)**:
    -   **职责边界**: 所有“回顾输出”统一收敛到 `PeriodicReviewJob`；`AnalyzeNotesJob` 仅做客观指标抽取与落盘，避免重复实现与 prompt 分叉。
    -   **输出约束**: 回顾任务禁止输出流水账总结与情绪安慰；只允许以“事实镜像 + 偏离警告 + 苏格拉底式尖锐问题”逼迫用户校准终极意图与行动轨迹。
    -   **Structured Output**: 指标抽取任务必须强制要求 JSON 格式输出，以保证下游数据处理的稳定性。
    -   **Action Boundaries (动作边界)**: Agent 仅允许通过 `app/skills/` 目录下的明确定义的函数执行副作用操作（如文件写入）。所有写操作必须具备幂等性（Idempotency），防止重复调用导致数据污染。
    -   **Tool Use (工具调用)**: 考虑到大模型（如 Gemini Flash）存在“口头答应（Action Hallucination）”的惰性，System Prompt 中必须包含强烈的执行约束（如：“绝对禁止口头答应，必须且只能调用工具”），以强制 LLM 走 Tool Calling 链路，确保数据的真实落地。

5.  **Profile 读写权限与升级 (Profile Evolution Policy)**:
    -   **静态锁定区（不可修改）**: `name`, `personal_info.birth_date`, `gender`, `height`, `timezone`。AI 无权改动，任何写入请求必须拒绝。
    -   **高频迭代区（随时覆写）**: `recent_focus.*`, `recent_focus.current_projects`。
    -   **认知演进区（按需覆写）**: `investment_philosophy`, `physical_baseline.primary_goals`, `preferences.*`。
    -   **动态特征区（Append-Only / 自由扩展）**: `custom_traits.*`。用于存放用户在对话中临时提出的新规矩/习惯/触发器；当用户只是“查询/核对当前信息”时，不应触发任何写操作或落库。
