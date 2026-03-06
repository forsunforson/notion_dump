# User Profile Schema & Best Practices (profile.yaml)

## 1. 设计理念 (Design Philosophy)
`profile.yaml` 是 ChronoFold 系统的**唯一事实来源 (Single Source of Truth)**，用于定义用户的物理基线、资产结构、认知偏好和近期焦点。
为了优化 LLM 的 Token 消耗并提高回答的精准度，本配置采用**领域解耦 (Domain Decoupling)**与**按需加载 (Lazy Loading)**的设计原则。由于该文件包含极度隐私的个人数据，已加入 `.gitignore`，代码库中仅保留本 Schema 规范。

## 2. 数据生命周期与归类 (Data Lifecycle & Categorization)

在 `context_fetcher.py` 提取上下文时，应根据用户的 Query 意图进行动态路由和按需拼装：

* **全局高频层 (Global / Static)**: 每次交互必带的基础人设。
    * `name`, `preferences`
* **物理与健康域 (Physical Domain)**: 仅在触发健身、睡眠、饮食相关意图时加载。
    * `personal_info`, `physical_baseline`
* **财富与认知域 (Financial & Cognitive Domain)**: 仅在触发投资、大额消费、财务相关等意图时加载。
    * `balance_sheet_structure`, `investment_philosophy`
* **短期工作内存 (Short-term Working Memory)**: 周期性变动，用于对齐当前的执行上下文。
    * `recent_focus`
* **动态特征区 (Custom Traits / Append-Only)**: 用户在对话中随口提出的新规矩/新习惯/触发器，用于即时增强上下文记忆。
    * `custom_traits`

## 2.1 读写权限与演进策略 (Read/Write Policy)

在对话式更新画像时，必须遵守以下权限边界：

* **静态锁定区（不可修改）**: `name`, `personal_info.birth_date`, `gender`, `height`, `timezone`
* **高频迭代区（随时覆写）**: `recent_focus.*`, `recent_focus.current_projects`
* **认知演进区（按需覆写）**: `investment_philosophy`, `physical_baseline.primary_goals`, `preferences.*`
* **动态特征区（Append-Only / 自由扩展）**: `custom_traits.*`（仅追加/扩展，不应做“覆盖式清空”）

## 3. 初始化最佳实践与模板 (Initialization Template)

新环境部署时，请在 `config/` 目录下创建 `profile.yaml`，并参考以下结构与数据契约进行填充：

```yaml
# ---------------------------------------------------------
# 全局高频层：AI 沟通基调
# ---------------------------------------------------------
name: "User_Name"
preferences:
  communication_style: "concise" # 期望的 AI 回复风格 (如: concise, empathetic, rigorous)
  detail_level: "medium"         # 信息颗粒度
  language: "zh-CN"
  timezone: "Asia/Shanghai"      # 核心时区配置，影响所有时间计算

# ---------------------------------------------------------
# 物理与健康域：身体资产表
# ---------------------------------------------------------
personal_info:
  birth_date: "YYYY-MM-DD"
  gender: "male/female"
  weight: "70kg"                 # 静态基准体重 (动态体重在 metrics.jsonl 中追踪)
  height: "175cm"

physical_baseline:
  training_experience: "from YYYY to now"
  health_status: "healthy"
  primary_goals: "力量、柔韧性、平衡性、耐力、爆发力均衡发展"
  weekly_routine: 
    description: "经典推拉腿(PPL)分化，外加爆发力训练"
    pattern: "周一推、周二腿、周三拉、周四{休息/柔韧性/有氧}、周五全身爆发力、周末{户外有氧/休息/CF}"
  personal_records:
    - name: "bench press"
      record: "115kg"
    - name: "squat"
      record: "155kg"
    - name: "deadlift"
      record: "180kg"
    - name: "overhead press"
      record: "70kg"
# ---------------------------------------------------------
# 财富与认知域：财务资产负债表 (抽象树状结构)
# ---------------------------------------------------------
balance_sheet_structure:
  asset_detail:
    - name: "large and fixed assets"
      value: "[总额]"
      detail:
        - name: "car"
          value: "[估值]"
    - name: "liquid assets"
      detail:
        - name: "checking account"
          value: "[现金余额]"
        - name: "equity"         # 权益类资产：股票、期权等
          detail:
            - name: "stock"
              detail:
                - name: "[公司名]"
                  stock_count: "[持股数]"
            - name: "option"
              value: "[期权估值]"
              detail:
                - name: "[期权名]"
                  option_count: "[期权数]"
        - name: "house fund"     # 公积金等
          value: "[余额]"
    - name: "personal items"
      value: "[预估价值]"
  liability_detail:
    - name: "short-term liabilities"
      value: "[负债总额]"
    - name: "long-term liabilities"
      value: "[负债总额]"

investment_philosophy: "[投资风格]"

# ---------------------------------------------------------
# 短期工作内存：动态焦点 (建议每月/每季度更新)
# ---------------------------------------------------------
recent_focus:
  current_projects: ["chronofold", "其他并行项目"]
  weekly_goal: "[每周目标]"
  monthly_goal: "[每月目标]"
  quarterly_goal: "[每季度目标]"
  yearly_goal: "[每年目标]"

# ---------------------------------------------------------
# 动态特征与认知补丁区 (由 AI 自动维护 / Append-Only)
# ---------------------------------------------------------
custom_traits:
  # anti_procrastination_trigger: "面对复杂配置容易陷入情绪内耗"
```

## 4. 画像变更审计 (Changelog)

当系统通过工具写回 `profile.yaml` 时，必须在 `notion_output/profile_changelog.jsonl` 追加一条 JSONL 记录，用于追踪用户认知与偏好的演化（时间戳必须是 UTC）。
