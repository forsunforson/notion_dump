import json
import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from app.core.paths import output_dir

def upsert_daily_metric(
    date: str,
    weight: Optional[float] = None,
    energy_level: Optional[int] = None,
    workout_volume_score: Optional[float] = None,
    sleep_hours: Optional[float] = None,
    mood_score: Optional[int] = None,
    source: str = "telegram_bot"
) -> str:
    """
    Upsert daily metrics for a given date.
    
    Args:
        date: The date for the metrics (YYYY-MM-DD).
        weight: Body weight in kg.
        energy_level: Energy level (1-10).
        workout_volume_score: Workout volume score.
        sleep_hours: Hours of sleep.
        mood_score: Mood score (1-10).
        source: The source of the data (default: "telegram_bot").
        
    Returns:
        A message indicating success or failure.
    """
    try:
        # Generate a unique source identifier for the bot entry for this date
        # This ensures we don't overwrite entries from other dates if source is just "telegram_bot"
        # and compatible with analyze_notes.py which uses source as key.
        if source == "telegram_bot":
            real_source = f"telegram_bot_{date}"
        else:
            real_source = source

        # Construct the metrics object
        metrics = {
            "date": date,
            "source": real_source,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        
        if weight is not None:
            metrics["weight"] = weight
        if energy_level is not None:
            metrics["energy_level"] = energy_level
        if workout_volume_score is not None:
            metrics["workout_volume_score"] = workout_volume_score
        if sleep_hours is not None:
            metrics["sleep_hours"] = sleep_hours
        if mood_score is not None:
            metrics["mood_score"] = mood_score
            
        # Check if there is actual data besides date, source, and timestamp
        has_actual_data = any(
            k not in ["date", "source", "timestamp"] for k in metrics.keys()
        )
        
        if not has_actual_data:
            return "No metrics provided to update."

        metrics_path = output_dir() / "metrics.jsonl"
        
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
        
        # Update the map
        metrics_map[real_source] = metrics
        
        with open(metrics_path, 'w', encoding='utf-8') as f:
            for item in metrics_map.values():
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
                
        return f"Successfully updated metrics for {date}."
        
    except Exception as e:
        return f"Error updating metrics: {str(e)}"

METRICS_SKILL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "upsert_daily_metric",
        "description": "Record or update daily health and productivity metrics (weight, energy, etc.) to the system.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The date of the metrics in YYYY-MM-DD format."
                },
                "weight": {
                    "type": "number",
                    "description": "Body weight in kg."
                },
                "energy_level": {
                    "type": "integer",
                    "description": "Subjective energy level from 1 to 10."
                },
                "workout_volume_score": {
                    "type": "number",
                    "description": "Workout volume score (arbitrary unit)."
                },
                "sleep_hours": {
                    "type": "number",
                    "description": "Hours of sleep."
                },
                "mood_score": {
                    "type": "integer",
                    "description": "Mood score from 1 to 10."
                },
                "source": {
                    "type": "string",
                    "description": "Source of the data, defaults to 'telegram_bot'."
                }
            },
            "required": ["date"]
        }
    }
}
