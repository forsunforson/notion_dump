import json
import asyncio
import datetime
from pathlib import Path
from app.services.prompt_manager import PromptManager
from app.services.llm_service import LLMService
from app.services.context_fetcher import ContextFetcher
from app.core.paths import output_dir
from app.services.event_store import write_metrics_event


class AnalyzeNotesJob:
    def __init__(self):
        self.llm = LLMService()
        self.prompt_manager = PromptManager()
        self.fetcher = ContextFetcher()

    async def analyze_changes(self, file_paths: list):
        if not file_paths:
            return

        sem = asyncio.Semaphore(5)
        tasks = []
        for path in file_paths:
            tasks.append(self._extract_metrics_one_file_safe(path, sem))
            
        results = await asyncio.gather(*tasks)

        valid_results = [r for r in results if r]
        if not valid_results:
            return

        for item in valid_results:
            filename = item.get("filename")
            date_localized = item.get("date_localized")
            analysis = item.get("analysis", {})
            if isinstance(analysis, dict):
                self._process_daily_metrics(analysis, filename, date_localized)

    async def _extract_metrics_one_file_safe(self, file_path, sem):
        async with sem:
            try:
                return await self._extract_metrics_one_file(file_path)
            except Exception as e:
                print(f"Error analyzing {file_path}: {e}")
                return None

    async def _extract_metrics_one_file(self, file_path):
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
        date_localized = self.fetcher.extract_date_from_yaml(raw_content)

        is_diary = self.prompt_manager.is_daily_entry(raw_content)
        if not is_diary:
            return None

        system_prompt, user_prompt = self.prompt_manager.build_metrics_extraction_prompts(raw_content=raw_content)

        analysis_dict = await self.llm.ask_json(system_prompt, user_prompt)
        if not analysis_dict:
            return None
            
        return {
            "filename": filename,
            "file_path": file_path,
            "date_localized": date_localized,
            "analysis": analysis_dict
        }
    
    def _process_daily_metrics(self, analysis: dict, filename: str = None, date_localized: str = None):
        metrics = analysis.get("daily_metrics")
        if not metrics or not isinstance(metrics, dict):
            return
        
        has_actual_data = any(
            v is not None for k, v in metrics.items() if k != "date"
        )
        if not has_actual_data:
            return
        
        if date_localized:
            metrics["date"] = date_localized
        
        source = filename if filename else metrics.get("source")
        timestamp_utc = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        metrics["source"] = source
        metrics["timestamp"] = timestamp_utc
        
        metrics_path = output_dir() / "metrics.jsonl"
        try:
            write_metrics_event(metrics_path, metrics)
            print(f"Metrics saved to: {metrics_path}")
        except Exception as e:
            print(f"Error writing metrics: {e}")
