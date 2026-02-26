import os
import json
import asyncio
import datetime
import re
import aiofiles
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml
from app.services.prompt_manager import PromptManager
from app.services.llm_service import LLMService
from app.utils.context_fetcher import ContextFetcher


class AnalyzeNotesJob:
    def __init__(self):
        self.llm = LLMService()
        self.prompt_manager = PromptManager()
        self.fetcher = ContextFetcher()

    async def analyze_changes(self, file_paths: list):
        """
        Analyze the list of changed files using AI.
        """
        if not file_paths:
            return

        print(f"AnalyzeNotesJob starting analysis for {len(file_paths)} files...")
        
        sem = asyncio.Semaphore(5)
        tasks = []
        for path in file_paths:
            tasks.append(self._analyze_one_file_safe(path, sem))
            
        results = await asyncio.gather(*tasks)
        
        valid_results = [r for r in results if r]
        
        if valid_results:
            self._generate_report(valid_results)
        else:
            print("AnalyzeNotesJob: No valid analysis results to report.")

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
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_content = f.read(8000)
        except Exception as e:
            print(f"Error reading file {path}: {e}")
            return None
        
        filename = path.name
        
        raw_content = self.fetcher.localize_text_timestamps(raw_content)
        hydrated_content = await self._hydrate_context(raw_content, path.parent)
        
        is_diary = self.prompt_manager.is_daily_entry(raw_content)
        template_type = "diary" if is_diary else "article"
        
        system_prompt = "你是知识库助手。<changed_document> 是用户刚刚修改的内容，<references> 是该文档引用的背景资料（仅供参考，不是本次修改的内容）。请基于这些信息进行总结。"
        
        user_prompt = self.prompt_manager.build_prompt(str(file_path), hydrated_content, filename, raw_content=raw_content)
        
        analysis_dict = await self.llm.ask_json(system_prompt, user_prompt)
        if not analysis_dict:
            return None
            
        return {
            "filename": filename,
            "file_path": file_path,
            "analysis": analysis_dict
        }

    def _process_daily_metrics(self, analysis: dict, project_root: Path):
        metrics = analysis.get("daily_metrics")
        if not metrics or not isinstance(metrics, dict):
            return
        
        has_actual_data = any(
            v is not None for k, v in metrics.items() if k != "date"
        )
        if not has_actual_data:
            return
        
        metrics_path = project_root / "notion_output" / "metrics.jsonl"
        try:
            metrics_path.parent.mkdir(parents=True, exist_ok=True)
            with open(metrics_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(metrics, ensure_ascii=False) + "\n")
            print(f"Metrics appended to: {metrics_path}")
        except Exception as e:
            print(f"Error writing metrics: {e}")

    def _format_insights(self, insights: dict) -> str:
        if not insights or not isinstance(insights, dict):
            return ""
        
        md_lines = ["**Insights**:\n"]
        for key, value in insights.items():
            if value:
                formatted_key = key.replace("_", " ").title()
                md_lines.append(f"- **{formatted_key}**: {value}\n")
        
        if len(md_lines) == 1:
            return ""
        md_lines.append("\n")
        return "".join(md_lines)

    def _get_document_time(self, file_path: Path, tz: ZoneInfo) -> str | None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read(5000)
            
            yaml_match = re.search(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
            if yaml_match:
                yaml_content = yaml_match.group(1)
                created_match = re.search(r'created_time:\s*["\']?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z?["\']?', yaml_content)
                if created_match:
                    utc_time_str = created_match.group(1)
                    try:
                        utc_time = datetime.datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%S")
                        utc_time = utc_time.replace(tzinfo=datetime.timezone.utc)
                        local_time = utc_time.astimezone(tz)
                        return local_time.strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass
                
                updated_match = re.search(r'last_edited_time:\s*["\']?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z?["\']?', yaml_content)
                if updated_match:
                    utc_time_str = updated_match.group(1)
                    try:
                        utc_time = datetime.datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%S")
                        utc_time = utc_time.replace(tzinfo=datetime.timezone.utc)
                        local_time = utc_time.astimezone(tz)
                        return local_time.strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass
        except Exception:
            pass
        return None
    
    def _generate_report(self, results):
        project_root = Path(os.getcwd())
        reports_dir = project_root / "_reports"
        reports_dir.mkdir(exist_ok=True)
        
        profile = self.fetcher.get_profile()
        preferences = profile.get("preferences", {})
        timezone_str = preferences.get("timezone", "Asia/Shanghai")
        
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("Asia/Shanghai")
        
        now_local = datetime.datetime.now(tz)
        today_str = now_local.strftime("%Y-%m-%d")
        report_file = reports_dir / f"report_{today_str}.md"
        
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        timestamp_utc = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        markdown_content = f"\n## 🤖 AI 后台分析报告\n"
        markdown_content += f"> **系统同步时间**: {timestamp_utc} (UTC)。请注意，此时间仅为后台脚本运行时间，不代表用户的实际作息或笔记创建时间。\n\n"
        
        for item in results:
            filename = item.get("filename", "Unknown")
            file_path = item.get("file_path")
            analysis = item.get("analysis", {})
            
            if not isinstance(analysis, dict):
                analysis = {}
            
            self._process_daily_metrics(analysis, project_root)
            
            summary = analysis.get("summary", "No summary provided.")
            action_items = analysis.get("action_items", [])
            tags = analysis.get("tags", [])
            insights = analysis.get("insights")
            
            markdown_content += f"### 📄 {filename}\n"
            
            if file_path:
                doc_time = self._get_document_time(Path(file_path), tz)
                if doc_time:
                    markdown_content += f"*(文档记录时间: {doc_time})*\n"
            
            markdown_content += f"**Summary**: {summary}\n\n"
            
            if action_items and isinstance(action_items, list):
                markdown_content += "**Action Items**:\n"
                for action in action_items:
                    if action:
                        markdown_content += f"- [ ] {action}\n"
                markdown_content += "\n"
            
            insights_md = self._format_insights(insights)
            if insights_md:
                markdown_content += insights_md
            
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
