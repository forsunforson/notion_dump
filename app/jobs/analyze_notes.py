import json
import asyncio
import datetime
from pathlib import Path
from app.services.prompt_manager import PromptManager
from app.services.llm_service import LLMService
from app.utils.context_fetcher import ContextFetcher
from app.core.paths import output_dir


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

        system_prompt = "你是一个结构化信息抽取器。你只负责从文本中抽取客观指标，禁止主观总结与发挥。"
        user_prompt = f"""请从以下日记内容中抽取 daily_metrics，并仅以 JSON 返回，不要输出任何额外文本。

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
"""

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
            metrics_path.parent.mkdir(parents=True, exist_ok=True)
            
            metrics_map = {}
            
            if metrics_path.exists():
                with open(metrics_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            item = json.loads(line)
                            key = item.get("source") or item.get("date")
                            if key:
                                metrics_map[key] = item
                        except json.JSONDecodeError:
                            continue
            
            key = metrics.get("source") or metrics.get("date")
            metrics_map[key] = metrics
            
            with open(metrics_path, 'w', encoding='utf-8') as f:
                for item in metrics_map.values():
                    f.write(json.dumps(item, ensure_ascii=False) + '\n')
                    
            print(f"Metrics saved to: {metrics_path}")
        except Exception as e:
            print(f"Error writing metrics: {e}")
