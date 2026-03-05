import os
from pathlib import Path
from typing import Optional

import yaml
from app.utils.context_fetcher import ContextFetcher


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

    REVIEW_SYSTEM_PROMPTS = {
        "daily": SOCRATIC_REVIEW_SYSTEM_PROMPT,
        "weekly": SOCRATIC_REVIEW_SYSTEM_PROMPT,
        "monthly": SOCRATIC_REVIEW_SYSTEM_PROMPT,
        "custom": SOCRATIC_REVIEW_SYSTEM_PROMPT,
    }

    @staticmethod
    def _get_project_root() -> Path:
        current_file = Path(__file__).resolve()
        return current_file.parent.parent.parent

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            project_root = self._get_project_root()
            config_dir = project_root / "config"
        self.config_dir = Path(config_dir)
        self.profile_path = self.config_dir / "profile.yaml"
        self.templates_dir = self.config_dir / "templates"
        
        self._profile_str: Optional[str] = None
        self._profile_data: Optional[dict] = None

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

    def get_review_system_prompt(self, review_type: str) -> str:
        rt = (review_type or "").strip().lower()
        env_key = f"REVIEW_SYSTEM_PROMPT_{rt.upper()}"
        override = os.getenv(env_key, "").strip()
        if override:
            return override

        legacy = os.getenv("PERIODIC_REVIEW_SYSTEM_PROMPT", "").strip()
        if legacy:
            return legacy

        return self.REVIEW_SYSTEM_PROMPTS.get(rt) or self.DEFAULT_REVIEW_SYSTEM_PROMPT

    def build_socratic_review_prompt(self, profile: str, metrics_trend: str, notes_content: str) -> list[dict]:
        user_prompt = SOCRATIC_REVIEW_USER_PROMPT.format(
            profile=(profile or "").strip(),
            metrics_trend=(metrics_trend or "").strip(),
            notes_content=(notes_content or "").strip(),
        )
        return [
            {"role": "system", "content": SOCRATIC_REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
