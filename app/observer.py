import os
import json
import asyncio
import datetime
import re
import aiofiles
from pathlib import Path
from openai import AsyncOpenAI
from services.prompt_manager import PromptManager

class ContentObserver:
    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY")
        self.base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("AI_MODEL", "gpt-3.5-turbo")
        
        if not self.api_key:
            print("Warning: AI_API_KEY not set. Observer functionalities might fail.")
            
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        self.prompt_manager = PromptManager()

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
        matches = re.finditer(r'\[(.*?)\]\((.*?\.md)\)', content)
        
        ref_xml_parts = []
        count = 0
        
        for match in matches:
            if count >= 5:
                break
                
            filename = match.group(2)
            
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
        
        content = await self._hydrate_context(content, path.parent)
        
        system_prompt = "你是知识库助手。<changed_document> 是用户刚刚修改的内容，<references> 是该文档引用的背景资料（仅供参考，不是本次修改的内容）。请基于这些信息进行总结。"
        
        user_prompt = self.prompt_manager.build_prompt(str(file_path), content, filename)
        
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
