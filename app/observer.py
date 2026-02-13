import os
import json
import asyncio
import datetime
import re
import aiofiles
from pathlib import Path
from openai import AsyncOpenAI

class ContentObserver:
    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY")
        self.base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("AI_MODEL", "gpt-3.5-turbo")
        self.prompt_template_path = Path("observer_prompt.md")
        
        if not self.api_key:
            print("Warning: AI_API_KEY not set. Observer functionalities might fail.")
            
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    def _get_prompt_template(self):
        default_template = """
Plaintext
文件名: {filename}
内容:
{content}
    请简要分析（JSON格式返回）：
    1. summary: 一句话总结核心变更。
    2. action_items: 提取出的明确待办事项列表（没有则为空列表）。
    3. tags: 建议的 1-3 个标签。
"""
        if self.prompt_template_path.exists():
            try:
                with open(self.prompt_template_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                print(f"Error reading prompt template, using default: {e}")
                return default_template
        else:
            # Create default template file if it doesn't exist
            try:
                with open(self.prompt_template_path, "w", encoding="utf-8") as f:
                    f.write(default_template.strip())
                print(f"Created default prompt template at {self.prompt_template_path}")
            except Exception as e:
                print(f"Error creating prompt template: {e}")
            return default_template

    async def analyze_changes(self, file_paths: list):
        """
        Analyze the list of changed files using AI.
        """
        if not file_paths:
            return

        print(f"Observer starting analysis for {len(file_paths)} files...")
        
        sem = asyncio.Semaphore(5)
        tasks = []
        for path in file_paths:
            tasks.append(self._analyze_one_file_safe(path, sem))
            
        results = await asyncio.gather(*tasks)
        
        # Filter out None results (failed or skipped)
        valid_results = [r for r in results if r]
        
        if valid_results:
            self._generate_report(valid_results)
        else:
            print("Observer: No valid analysis results to report.")

    async def _analyze_one_file_safe(self, file_path, sem):
        async with sem:
            try:
                return await self._analyze_one_file(file_path)
            except Exception as e:
                print(f"Error analyzing {file_path}: {e}")
                return None

    async def _hydrate_context(self, content: str, root_dir: Path) -> str:
        matches = re.finditer(r'(parent_doc_link:\s*)?\[(.*?)\]\((.*?\.md)\)', content)
        
        ref_xml_parts = []
        count = 0
        
        for match in matches:
            if count >= 5:
                break
                
            prefix = match.group(1)
            filename = match.group(3)
            
            # If prefix exists (i.e., it is "parent_doc_link: "), skip this link
            if prefix:
                continue
                
            file_path = root_dir / filename
            if file_path.exists():
                try:
                    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                        ref_content = await f.read(1000)
                        ref_xml_parts.append(f'      <ref title="{filename}">\n        {ref_content}\n      </ref>')
                        count += 1
                except Exception:
                    pass
        
        xml_content = f"<changed_document>\n{content}\n</changed_document>"
        
        if ref_xml_parts:
            xml_content += "\n    <references>\n" + "\n".join(ref_xml_parts) + "\n    </references>"
            
        return xml_content

    async def _analyze_one_file(self, file_path):
        path = Path(file_path)
        if not path.exists():
            print(f"File not found: {path}")
            return None
            
        # Read first 8000 chars to avoid context overflow
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read(8000)
        except Exception as e:
            print(f"Error reading file {path}: {e}")
            return None
            
        filename = path.name
        
        # Hydrate context
        content = await self._hydrate_context(content, path.parent)
        
        system_prompt = "你是知识库助手。<changed_document> 是用户刚刚修改的内容，<references> 是该文档引用的背景资料（仅供参考，不是本次修改的内容）。请基于这些信息进行总结。"
        
        prompt_template = self._get_prompt_template()
        user_prompt = prompt_template.format(filename=filename, content=content)
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                stream=False
            )
            
            result_json = response.choices[0].message.content
            analysis = json.loads(result_json)
            
            return {
                "filename": filename,
                "analysis": analysis
            }
            
        except Exception as e:
            raise e

    def _generate_report(self, results):
        # Create _reports folder in project root (assuming CWD is project root)
        project_root = Path(os.getcwd())
        reports_dir = project_root / "_reports"
        reports_dir.mkdir(exist_ok=True)
        
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        report_file = reports_dir / f"report_{today_str}.md"
        
        # Append to the file
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        markdown_content = f"\n## Analysis Report - {timestamp}\n\n"
        
        for item in results:
            filename = item["filename"]
            analysis = item["analysis"]
            
            summary = analysis.get("summary", "No summary provided.")
            action_items = analysis.get("action_items", [])
            tags = analysis.get("tags", [])
            
            markdown_content += f"### {filename}\n"
            markdown_content += f"**Summary**: {summary}\n\n"
            
            if action_items:
                markdown_content += "**Action Items**:\n"
                for action in action_items:
                    markdown_content += f"- [ ] {action}\n"
                markdown_content += "\n"
            
            if tags:
                tag_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
                markdown_content += f"**Tags**: {tag_str}\n"
            
            markdown_content += "\n---\n\n"
            
        try:
            with open(report_file, "a", encoding="utf-8") as f:
                f.write(markdown_content)
            print(f"Report generated: {report_file}")
        except Exception as e:
            print(f"Error writing report: {e}")
