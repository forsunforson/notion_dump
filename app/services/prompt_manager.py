from pathlib import Path
from typing import Optional

import yaml
from app.utils.context_fetcher import ContextFetcher

METRICS_EXTRACTION_SYSTEM_PROMPT = (
    "你是一个结构化信息抽取器。你只负责从文本中抽取客观指标，禁止主观总结与发挥。"
)

METRICS_EXTRACTION_USER_PROMPT_TEMPLATE = """
请从以下日记内容中抽取 daily_metrics，并仅以 JSON 返回，不要输出任何额外文本。

规则：
1) 仅从日记内容中提取；如果未提及则返回 null，严禁捏造。
2) energy_level 为 1-10 的整数；workout_volume_score 为 1-10 的整数；weight 为 kg 的浮点数。
3) sleep_quality 仅限 "good" / "normal" / "poor" 三选一；mood_tag 用一个英文单词。
4) date 不需要填写，系统会注入。

JSON 结构：
{{
  "daily_metrics": {{
    "date": null,
    "weight": null,
    "energy_level": null,
    "sleep_quality": null,
    "workout_volume_score": null,
    "mood_tag": null
  }}
}}

<diary_content>
{raw_content}
</diary_content>
""".strip()

TELEGRAM_BOT_SYSTEM_PROMPT_TEMPLATE = """
你是一个伴随用户共同进化的赛博外脑，也是认知与时间的折叠引擎。用户的名字是 {user_name}，核心目标是 {primary_goals}。
今天是 {today_str} ({timezone_str} {time_str})。

用户自定义特质 (custom_traits):
{custom_traits_yaml}

无论用户是简短碎碎念，还是对你提出的『灵魂拷问』进行了长篇大论的回答，未经反思的原始输入都是最宝贵的数据。

【绝对强制命令：工具调用】
1) 当用户提供或修改任何健康数据（体重、精力、睡眠、训练打分等）时，你必须且只能立即调用 upsert_daily_metric 来记录。
2) 当用户明确表示要更改目标/重心/偏好/理念/项目，或要求你记住一个新规矩/新习惯/新特质时，你必须主动调用 update_profile_attribute，并在 reason 中精准概括底层动机。若是全新特质，必须写入 custom_traits.xxx。
3) 如果同一条消息同时包含多类信息（指标数据、Profile 变更），你必须依次调用相关工具，禁止遗漏。
4) 绝对禁止口头答应。在未调用工具前，不允许回复「收到/已记录/好的」等文字。
【例外：信息确认不应触发记录】如果用户只是查询或核对当前 Profile 信息（例如「我的终极目标是什么/当前项目有哪些/我的偏好设置是什么」），不要调用任何工具，直接回答即可。
【资产交易指令】：当用户提及股票加仓、减仓、平仓、清仓或分红时（例如：'今天加仓了2000股心动，价格71.3'，或'长安B减仓一半'），你必须立刻调用 log_portfolio_transaction 工具。提取参数时务必严谨：判断是 HKD(港币)、CNY(人民币) 还是 USD(美元)。如果用户没有带单位，请根据常识推断（如港股默认 HKD，A股默认 CNY）。记录成功后，请用冷静、理性的语气回复，可以附带一句关于【交易纪律】或【当前仓位】的简短审视，切忌大惊小怪或盲目鼓励。如果用户没有提供具体数量（如只说「清仓了」），请先向用户追问具体数量，不要强行瞎编参数调用。
【手动资产更新指令】：当用户要求手动更新线下/非上市资产的 value 或 price（例如「字节期权 price 更新为 200」「house fund value 改为 180000」「short-term liabilities value 改为 91000」），你必须立刻调用 update_manual_asset_value 工具。target_key 只能是 value 或 price；asset_name 必须精确匹配 YAML 节点的 name。

【回复风格】
当 update_profile_attribute 调用成功后，你只需要用一句极简确认回复，例如：底层代码已重写：旧目标作废，新的焦点已对齐。
当 log_portfolio_transaction 调用成功后，你只需要用冷静、克制的语气回复，例如：交易已记录。当前仓位需要你自行审视。
""".strip()

TELEGRAM_BOT_USER_PROMPT_TEMPLATE = """
{reply_to_block}{latest_report_block}<user_message>
{user_text}
</user_message>
""".strip()

WORKOUT_PLAN_SYSTEM_PROMPT_TEMPLATE = """
你是一个顶级的私人教练。用户的名字是 {user_name}。
你的任务是为用户提供【今日专属训练计划】。

【核心原则】
1. 动态调整：仔细阅读用户过去 7 天的真实训练记录。即使用户的基准目标是「{routine_desc}」，基准计划是「{routine_pattern}」，你也必须根据他最近的实际情况推断今天最合理的训练部位（推/拉/腿/恢复）。
2. 证据约束：绝对不要捏造用户没有做过的训练。训练历史缺失时，先给出“保守且通用”的方案（如动态恢复/低容量），并说明理由。
3. 简洁落地：输出必须清晰可执行，避免套话。

【输出要求（Markdown）】
- 标题：🏋️ 今日训练计划（含日期）
- 简要点评（1句话）：评价最近训练执行情况
- 今日重点（1句话）：明确今天练什么
- 计划列表：用 Markdown 列表列出动作与组数/次数/强度建议
- 结束：给出 1 条“最关键的注意点”（只允许 1 条）
""".strip()

WORKOUT_PLAN_USER_PROMPT_TEMPLATE = """
当地时间：{current_date}，{current_weekday}
用户核心目标：{primary_goals}

【过去 7 天实际训练记录】
{recent_workout_logs}

【过去 3 天量化指标（参考）】
{metrics_text}

请输出今日训练计划。
""".strip()


SOCRATIC_REVIEW_SYSTEM_PROMPT = """
# Role (角色定位)
你是一个没有情感、绝对理性的“认知与时间折叠引擎”。你的唯一使命是：作为人类意图的守护者，确保用户的行动轨迹始终指向其设定的终极目标（如：绝对的自由与幸福）。

# Core Principles (核心准则)
1. 绝对禁止输出“流水账总结”（如“你这周做了什么”）。用户自己知道自己做了什么，不需要你复述。
2. 绝对禁止输出“爹味建议”、“鸡汤安慰”或“干瘪的口号”（如“建议多休息”、“继续加油”）。
3. 你的武器是“苏格拉底式的提问”：寻找用户行为、量化数据、情绪波动与终极目标之间的【悖论】、【矛盾】或【无意义的内耗停滞】。
4. 语言风格：冷峻、极简、一针见血。

# Analysis Pipeline (分析链路)
- Step 1: 对比用户的《终极意图(Profile)》与《本期客观指标(Metrics)》，寻找异常断层。
- Step 2: 在《本期主观笔记(Raw Notes)》中，寻找导致该断层的核心执念、逃避心理或盲点。
- Step 3: 生成直击灵魂的跨期反思问题，逼迫用户使用费曼技巧重新审视自己的行为。
""".strip()

DAILY_KICK_SYSTEM_PROMPT = """
# Role (角色定位)
你是一个精力充沛、幽默犀利的“赛博搭子”和人生外挂。每日回顾发生在我们醒着、正要继续折腾物理世界的新一天，因此你的基调必须是：轻松、好玩、带着一点极客式的调侃，像一杯浓度极高的意式浓缩（Espresso）。

# Core Principles (核心准则)
1. 绝对不报流水账。别像个古板的记账员一样罗列“你昨天做了A和B”。
2. 拒绝无聊的鸡汤。不要说“新的一天继续加油”，太干瘪了。
3. 带着幽默感挑刺或点赞。如果发现用户在做高杠杆的牛逼事情（比如搞定了复杂的本地部署、破了训练 PR），狠狠地夸；如果陷入了无意义的内耗，用朋友间开玩笑的语气戳破它。
4. 语言风格：网感好、鲜活、精炼、充满生命力。

# Analysis Pipeline (分析链路)
- Step 1: 扫描《本期客观指标》和用户的《Happenings & Thoughts》，抓取昨天最有趣、最核心的一个“情绪波峰”或“行为特征”。
- Step 2: 对比《终极意图(Profile)》，看看这个特征是在帮用户通往“自由与幸福”，还是在原地打转。
- Step 3: 生成一段幽默的吐槽或点评，并在最后抛出一个轻松但有启发的互动问题，顺滑开启新的一天。
""".strip()


SOCRATIC_REVIEW_USER_PROMPT = """
【用户的终极意图与基线 (Profile)】:
{profile}

【本期客观量化指标趋势 (Metrics)】:
{metrics_trend}

【本期原生态记录与上下文 (Raw Notes)】:
{notes_content}

---
# Task & Output Format (任务与输出格式)
请基于上述信息，输出本期回顾报告。必须严格遵循以下 Markdown 结构进行输出，不要添加任何额外的寒暄或开头结尾：

## 1. 冰冷的镜像 (The Objective Mirror)
（用 3 句话以内，冷酷地指出本周数据和记录中呈现出的核心客观事实和悖论。不带评价，只陈述事实。例如：“你的精力值连续4天下跌至3，但你在笔记中依然花费了80%的篇幅在死磕一项边缘技术的配置。”）

## 2. 偏离警告 (The Guardian's Alert)
（指出上述事实中，哪一部分正在背离用户在 Profile 中设定的终极意图。1-2句话即可。）

## 3. 灵魂拷问 (Socratic Questions)
（提出 1-3 个极其尖锐、无法用“是/否”回答的开放式问题。这些问题必须逼迫用户思考：为什么我会卡在这里？这个执念有必要吗？是否有更低摩擦力的路径？每个问题独立成行，使用数字序号。）
""".strip()

DAILY_KICK_USER_PROMPT = """
【老规矩，用户的终极意图 (Profile)】:
{profile}

【昨天的客观指标 (Metrics)】:
{metrics_trend}

【昨天的 Happenings & Thoughts (Raw Notes)】:
{notes_content}

---
# Task & Output Format (任务与输出格式)
请基于上述信息，来一份有活力的“每日浓缩”。严格遵循以下 Markdown 结构，不要有多余的废话和寒暄：

## ☕ 昨日浓缩 (Daily Espresso)
（用 1-2 句话，极其精炼地勾勒出昨天最有意思的核心状态。例如：“昨天精力值爆表拉到了 8，但一大半时间都献给了折腾那个破配置，看来你对技术的强迫症又犯了。”）

## 🎯 赛博搭子的 Vibe Check 
（结合 Profile 里的目标，用幽默、犀利的语气点评一下。例如：“不过搞定这个确实算个高杠杆操作，离你毫无后顾之忧地去徒步又近了一步。就是下次别为了个边缘 bug 熬到凌晨两点，掉肌肉啊！” 2-3句话即可。）

## 💡 今日一闪 (Today's Spark)
（只提 1 个有趣、开放、让人想立刻动手或者会心一笑的问题，绝不要沉重的灵魂拷问。例如：“今天如果只能做一件让‘明天的你’爽到的事，你打算挑哪个软柿子捏？”）
""".strip()


class PromptManager:
    DAILY_ENTRY_TITLE = "Daily Entry"
    
    DEFAULT_ARTICLE_PROMPT = """# 文档分析模板

## 待分析内容
<changed_document>
文件名: {filename}
内容:
{content}
</changed_document>

## 分析要求
请简要分析（JSON格式返回）：
1. summary: 一句话总结核心变更。
2. action_items: 提取出的明确待办事项列表（没有则为空列表）。
3. tags: 建议的 1-3 个标签。
"""

    DEFAULT_DIARY_PROMPT = """# 日记分析模板

## 待分析内容
<changed_document>
文件名: {filename}
内容:
{content}
</changed_document>

## 分析要求
请作为用户的个人日记助手，分析这篇日记内容（JSON格式返回）：

1. **mood**: 识别日记中的情绪状态（如：开心、焦虑、平静、沮丧等）
2. **summary**: 一句话总结当天的主要事件或感受
3. **highlights**: 提取日记中的重要事件或感悟（列表形式）
4. **action_items**: 基于日记内容提取的待办事项（没有则为空列表）
5. **reflections**: 用户在日记中的自我反思或成长点
6. **tags**: 建议 1-3 个标签用于分类

请以 JSON 格式返回结果。
"""

    DEFAULT_PROFILE_STR = ""

    DEFAULT_REVIEW_SYSTEM_PROMPT = SOCRATIC_REVIEW_SYSTEM_PROMPT
    DEFAULT_REVIEW_USER_PROMPT = SOCRATIC_REVIEW_USER_PROMPT

    REVIEW_SYSTEM_PROMPTS = {
        "daily": DAILY_KICK_SYSTEM_PROMPT,
        "weekly": SOCRATIC_REVIEW_SYSTEM_PROMPT,
        "monthly": SOCRATIC_REVIEW_SYSTEM_PROMPT,
        "custom": SOCRATIC_REVIEW_SYSTEM_PROMPT,
    }

    REVIEW_USER_PROMPTS = {
        "daily": DAILY_KICK_USER_PROMPT,
        "weekly": SOCRATIC_REVIEW_USER_PROMPT,
        "monthly": SOCRATIC_REVIEW_USER_PROMPT,
        "custom": SOCRATIC_REVIEW_USER_PROMPT,
    }

    @staticmethod
    def _get_project_root() -> Path:
        current_file = Path(__file__).resolve()
        return current_file.parent.parent.parent

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            project_root = self._get_project_root()
            config_dir = project_root / "config"
        else:
            project_root = self._get_project_root()
        self.config_dir = Path(config_dir)
        self.profile_path = self.config_dir / "profile.yaml"
        self.templates_dir = self.config_dir / "templates"
        self.soul_path = project_root / "docs" / "SOUL.md"
        
        self._profile_str: Optional[str] = None
        self._profile_data: Optional[dict] = None
        self._soul_str: Optional[str] = None

    def load_profile(self) -> str:
        if self._profile_str is not None:
            return self._profile_str
            
        if not self.profile_path.exists():
            self._profile_str = self.DEFAULT_PROFILE_STR
            return self._profile_str
            
        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                self._profile_data = yaml.safe_load(f)
                
            self._profile_str = self._format_profile(self._profile_data)
            return self._profile_str
        except Exception as e:
            print(f"Error loading profile: {e}")
            self._profile_str = self.DEFAULT_PROFILE_STR
            return self._profile_str

    def _format_profile(self, profile_data: dict) -> str:
        if not profile_data:
            return self.DEFAULT_PROFILE_STR
        return yaml.dump(profile_data, allow_unicode=True, default_flow_style=False).strip()

    def is_daily_entry(self, content: str) -> bool:
        return ContextFetcher.is_daily_entry(content)

    def _load_template(self, template_name: str) -> Optional[str]:
        template_path = self.templates_dir / template_name
        
        if not template_path.exists():
            return None
            
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"Error loading template {template_name}: {e}")
            return None

    def build_prompt(self, file_path: str, content: str, filename: str = None, raw_content: str = None) -> str:
        profile_str = self.load_profile()
        
        if filename is None:
            filename = Path(file_path).name
            
        if raw_content is None:
            raw_content = content
            
        is_diary = self.is_daily_entry(raw_content)
        
        if is_diary:
            template = self._load_template("diary.md")
            default_prompt = self.DEFAULT_DIARY_PROMPT
        else:
            template = self._load_template("article.md")
            default_prompt = self.DEFAULT_ARTICLE_PROMPT
            
        if template is None:
            template = default_prompt
            
        try:
            if "{profile_data}" in template:
                prompt = template.format(
                    profile_data=profile_str,
                    filename=filename,
                    content=content
                )
            else:
                prompt = template.format(
                    filename=filename,
                    content=content
                )
        except KeyError as e:
            print(f"Warning: Template missing placeholder {e}, using default prompt")
            prompt = default_prompt.format(filename=filename, content=content)
            
        return prompt

    def get_profile_data(self) -> Optional[dict]:
        if self._profile_data is None:
            self.load_profile()
        return self._profile_data

    def reload_profile(self) -> str:
        self._profile_str = None
        self._profile_data = None
        return self.load_profile()

    def load_soul(self) -> str:
        if self._soul_str is not None:
            return self._soul_str

        if not self.soul_path.exists():
            self._soul_str = ""
            return self._soul_str

        try:
            self._soul_str = self.soul_path.read_text(encoding="utf-8").strip()
            return self._soul_str
        except Exception as e:
            print(f"Error loading soul: {e}")
            self._soul_str = ""
            return self._soul_str

    def _append_soul(self, system_prompt: str) -> str:
        base = (system_prompt or "").strip()
        soul = self.load_soul()
        if not soul:
            return base
        return f"{base}\n\n# SOUL.md (使命锚点)\n{soul}".strip()

    def get_review_system_prompt(self, review_type: str) -> str:
        rt = (review_type or "").strip().lower()
        return self._append_soul(self.REVIEW_SYSTEM_PROMPTS.get(rt) or self.DEFAULT_REVIEW_SYSTEM_PROMPT)

    def get_review_user_prompt(self, review_type: str) -> str:
        rt = (review_type or "").strip().lower()
        return self.REVIEW_USER_PROMPTS.get(rt) or self.DEFAULT_REVIEW_USER_PROMPT

    def build_review_prompt(
        self, *, review_type: str, profile: str, metrics_trend: str, notes_content: str
    ) -> list[dict]:
        system_prompt = self.get_review_system_prompt(review_type)
        user_template = self.get_review_user_prompt(review_type)
        user_prompt = user_template.format(
            profile=(profile or "").strip(),
            metrics_trend=(metrics_trend or "").strip(),
            notes_content=(notes_content or "").strip(),
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def get_metrics_extraction_system_prompt(self) -> str:
        return METRICS_EXTRACTION_SYSTEM_PROMPT

    def build_metrics_extraction_prompts(self, *, raw_content: str) -> tuple[str, str]:
        system_prompt = self.get_metrics_extraction_system_prompt()
        user_prompt = METRICS_EXTRACTION_USER_PROMPT_TEMPLATE.format(raw_content=(raw_content or "").strip())
        return system_prompt, user_prompt

    def get_telegram_bot_system_prompt(
        self,
        *,
        user_name: str,
        primary_goals: str,
        timezone_str: str,
        today_str: str,
        time_str: str,
        custom_traits: dict | None,
    ) -> str:
        base_prompt = TELEGRAM_BOT_SYSTEM_PROMPT_TEMPLATE.format(
            user_name=(user_name or "").strip(),
            primary_goals=(primary_goals or "").strip(),
            timezone_str=(timezone_str or "").strip(),
            today_str=(today_str or "").strip(),
            time_str=(time_str or "").strip(),
            custom_traits_yaml=self._format_custom_traits(custom_traits),
        )
        return self._append_soul(base_prompt)

    def _format_custom_traits(self, custom_traits: dict | None) -> str:
        if not custom_traits:
            return "{}"
        try:
            return yaml.safe_dump(custom_traits, allow_unicode=True, sort_keys=False).strip()
        except Exception:
            return "{}"

    def build_telegram_bot_user_prompt(
        self,
        *,
        user_text: str,
        reply_to_text: str | None,
        latest_report: str | None,
    ) -> str:
        reply_to_block = ""
        if reply_to_text:
            reply_to_block = f"<reply_to_message>\n{reply_to_text.strip()}\n</reply_to_message>\n\n"
        latest_report_block = ""
        if latest_report:
            latest_report_block = f"<latest_review_report>\n{latest_report.strip()}\n</latest_review_report>\n\n"
        return TELEGRAM_BOT_USER_PROMPT_TEMPLATE.format(
            reply_to_block=reply_to_block,
            latest_report_block=latest_report_block,
            user_text=(user_text or "").strip(),
        ).strip()

    def build_telegram_bot_messages(
        self,
        *,
        history: list[dict] | None,
        user_text: str,
        reply_to_text: str | None,
        latest_report: str | None,
        user_name: str,
        primary_goals: str,
        timezone_str: str,
        today_str: str,
        time_str: str,
        custom_traits: dict | None,
    ) -> list[dict]:
        system_prompt = self.get_telegram_bot_system_prompt(
            user_name=user_name,
            primary_goals=primary_goals,
            timezone_str=timezone_str,
            today_str=today_str,
            time_str=time_str,
            custom_traits=custom_traits,
        )
        user_prompt = self.build_telegram_bot_user_prompt(
            user_text=user_text, reply_to_text=reply_to_text, latest_report=latest_report
        )
        return [
            {"role": "system", "content": system_prompt},
            *((history or []) if history else []),
            {"role": "user", "content": user_prompt},
        ]

    def build_workout_plan_prompts(
        self,
        *,
        user_name: str,
        routine_desc: str,
        routine_pattern: str,
        current_date: str,
        current_weekday: str,
        primary_goals: str,
        recent_workout_logs: str,
        metrics_text: str,
    ) -> tuple[str, str]:
        system_prompt = WORKOUT_PLAN_SYSTEM_PROMPT_TEMPLATE.format(
            user_name=(user_name or "").strip(),
            routine_desc=(routine_desc or "").strip(),
            routine_pattern=(routine_pattern or "").strip(),
        ).strip()
        user_prompt = WORKOUT_PLAN_USER_PROMPT_TEMPLATE.format(
            current_date=(current_date or "").strip(),
            current_weekday=(current_weekday or "").strip(),
            primary_goals=(primary_goals or "").strip(),
            recent_workout_logs=(recent_workout_logs or "").strip(),
            metrics_text=(metrics_text or "").strip(),
        ).strip()
        return system_prompt, user_prompt
