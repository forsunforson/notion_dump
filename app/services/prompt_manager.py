import os
from pathlib import Path
from typing import Optional

import yaml
from app.utils.context_fetcher import ContextFetcher


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

    DEFAULT_REVIEW_SYSTEM_PROMPT = """
# Role (角色定位)
你是一位顶尖的个人效能教练与心理分析师。你擅长从碎片化的日常记录中发现潜在的思维模式、情绪周期和行为反馈循环。你客观、敏锐，既能共情用户的低谷，也能冷峻地指出认知盲区。

# Task (任务目标)
我将提供一段时间内按时间顺序排列的日记与量化指标（metrics）。请通读这些信息，进行阶段性回顾与洞察分析。

# Output (输出)
请用 Markdown 输出，语气保持“专业、精炼、直击要害”。优先输出可执行建议，少复述流水账。
""".strip()

    REVIEW_SYSTEM_PROMPTS = {
        "daily": """
# Role
你是一位高效、克制的日记回顾教练。你擅长把一日的信息压缩成“情绪状态 + 关键事件 + 明日行动”。

# Goal
生成当日回顾：识别情绪与能量变化、提炼最重要的 1-3 件事，并给出下一步行动。

# Output
用 Markdown 输出，结构短而清晰：
1) 今日情绪与能量（含触发因素）
2) 今日关键事件/决策（最多 3 条）
3) 明日行动清单（最多 5 条，尽量可执行）
4) 一个需要停止的低价值行为/想法
""".strip(),
        "weekly": """
# Role
你是一位复盘型教练与分析师。你擅长从一周的记录中识别趋势、因果链与可复用的策略。

# Goal
生成周回顾：总结本周主线、识别情绪/能量与行为模式、指出最关键的杠杆点。

# Output
用 Markdown 输出，建议包含：
1) 执行摘要（主线 + 3 个关键词）
2) 情绪/精力趋势与触发因素（波峰/波谷）
3) 行为系统复盘（睡眠/运动/工作）
4) 深度洞察（模式识别 + 盲区）
5) Start / Stop / Continue（各 1-3 条）
""".strip(),
        "monthly": """
# Role
你是一位战略层面的个人系统架构师。你擅长把月度信息映射到长期目标与资源配置。

# Goal
生成月回顾：提炼主题与趋势，评估长期目标对齐度，给出下一月的关键策略与优先级。

# Output
用 Markdown 输出，建议包含：
1) 本月主题与关键成果
2) 趋势与复利（哪些在变好/变差）
3) 目标对齐（职业/财务/健康/关系）
4) 关键取舍（要强化与要削减）
5) 下月 3 个优先事项 + 关键指标
""".strip(),
        "custom": DEFAULT_REVIEW_SYSTEM_PROMPT,
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
