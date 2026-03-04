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
