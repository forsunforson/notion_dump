import json
import logging
import asyncio
from app.services.telegram_service import TelegramService
from app.services.llm_service import LLMService
from app.utils.context_fetcher import ContextFetcher

logger = logging.getLogger(__name__)


class DailyRoutines:
    def __init__(self):
        self.llm = LLMService()
        self.telegram = TelegramService()
        self.fetcher = ContextFetcher()
    
    async def morning_routine(self) -> bool:
        logger.info("Starting morning routine (dual-track mode)...")
        
        profile = self.fetcher.get_profile()
        user_name = profile.get('name', 'ywy')
        preferences = profile.get("preferences", {})
        physical_baseline = profile.get("physical_baseline", {})
        
        timezone_str = preferences.get("timezone", "Asia/Shanghai")
        time_info = self.fetcher.get_time_info(timezone_str)
        current_date = time_info["current_date"]
        current_weekday = time_info["current_weekday"]
        date_info = f"当地时间：{current_date}，{current_weekday}"
        
        weekly_routine = physical_baseline.get("weekly_routine", {})
        primary_goals = physical_baseline.get("primary_goals", "")
        
        latest_report = self.fetcher.get_latest_report()
        recent_metrics = self.fetcher.get_recent_metrics(3)
        recent_workout_logs = self.fetcher.get_recent_workout_logs(7)
        
        message_a = ""
        try:
            system_prompt_a = f"你是一个贴心的私人助理。用户的名字是 {user_name}。现在是早上。请根据用户最近的知识库报告生成晨间问候。用友好的口吻总结昨夜的知识沉淀或重要待办，语气轻松，控制在 300 字以内。打招呼时直接使用「{user_name}」这个名字，绝对不要输出 [User Name] 这种占位符。"
            
            if latest_report:
                user_prompt_a = f"请根据以下知识库报告生成晨间问候：\n\n<report>\n{latest_report}\n</report>"
            else:
                user_prompt_a = "暂无新的知识库报告，请生成一条轻松的晨间问候。"
            
            message_a = await self.llm.ask_text(system_prompt_a, user_prompt_a, max_tokens=500)
            if not message_a:
                message_a = "早安！知识简报生成失败，请稍后查看。"
            else:
                logger.info(f"Generated knowledge brief: {message_a[:100]}...")
        except Exception as e:
            logger.error(f"Error generating knowledge brief: {e}")
            message_a = "早安！知识简报生成失败，请稍后查看。"
        
        message_b = ""
        try:
            routine_desc = weekly_routine.get("description", "未设置")
            routine_pattern = weekly_routine.get("pattern", "未设置")
            
            system_prompt_b = f"""你是一个顶级的私人教练。用户的名字是 {user_name}。
你的任务是为用户提供【今日专属训练计划】。

【核心原则】
1. 动态调整：仔细阅读用户过去 7 天的真实训练记录。即使用户的基准计划是「{routine_desc}」，你也必须根据他昨天/前天的实际情况（比如是否休息了、是否跳过了某练）来推断今天最合理的训练部位。
2. 格式匹配：输出格式必须与用户的日常记录格式高度匹配，直接给出清晰的动作列表。

【输出要求】
- 简要点评（1句话）：评价最近的训练执行情况。
- 今日重点（1句话）：明确今天是练什么（如：推/拉/腿/动态恢复）。
- 计划列表：用 Markdown 列表清晰列出推荐的训练动作及组数/重量/次数建议（如：格式参考用户过去的训练记录）。
- 避免废话：不要输出"加油"、"注意安全"等套话。绝对不要捏造用户没有做过的训练。"""
            
            metrics_text = ""
            if recent_metrics:
                metrics_lines = []
                for m in recent_metrics:
                    metrics_lines.append(json.dumps(m, ensure_ascii=False, indent=2))
                metrics_text = "\n\n".join(metrics_lines)
            else:
                metrics_text = "暂无近期身体状态数据。"
            
            user_prompt_b = f"""当地时间：{current_date}，{current_weekday}
用户的核心目标：{primary_goals if primary_goals else "未设置"}

【过去 7 天实际训练记录】
{recent_workout_logs}

【过去 3 天量化指标 (参考)】
{metrics_text}

请根据以上真实记录，生成今日的训练计划。"""
            
            message_b = await self.llm.ask_text(system_prompt_b, user_prompt_b, max_tokens=500)
            if not message_b:
                message_b = "今日训练建议生成失败，请稍后查看。"
            else:
                logger.info(f"Generated training plan: {message_b[:100]}...")
        except Exception as e:
            logger.error(f"Error generating training plan: {e}")
            message_b = "今日训练建议生成失败，请稍后查看。"
        
        try:
            success_a = await self.telegram.send_message(message_a)
            if not success_a:
                logger.error("Failed to send knowledge brief")
                return False
            
            await asyncio.sleep(1)
            
            success_b = await self.telegram.send_message(message_b)
            if not success_b:
                logger.error("Failed to send training plan")
                return False
            
            logger.info("Morning routine (dual-track) completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in morning routine message delivery: {e}")
            return False
    
    async def weekly_review(self) -> bool:
        logger.info("Starting weekly review...")
        
        reports_content = self.fetcher.get_reports_from_last_n_days(7)
        history_content = self.fetcher.get_history_from_last_n_days(7)
        
        context_parts = []
        if reports_content:
            context_parts.append(f"<weekly_reports>\n{reports_content}\n</weekly_reports>")
        if history_content:
            context_parts.append(f"<activity_log>\n{history_content}\n</activity_log>")
        
        context = "\n\n".join(context_parts) if context_parts else "暂无本周的活动数据。"
        
        system_prompt = """你是一个知识管理助手。请根据用户过去一周的知识库变动，生成一份"本周知识回顾"。

输出要求：
1. 使用 Markdown 格式
2. 包含以下部分：
   - 本周概览（总体变化统计）
   - 重点内容回顾（最重要的 3-5 个主题）
   - 待办事项提醒（如果有未完成的任务）
   - 下周建议
3. 控制在 800 字以内
4. 语气专业但友好"""
        
        user_prompt = f"请根据以下本周数据生成本周知识回顾：\n\n{context}"
        
        try:
            message = await self.llm.ask_text(system_prompt, user_prompt, max_tokens=1200)
            if not message:
                logger.error("Empty response from LLM in weekly review")
                return False
            
            logger.info(f"Generated weekly review: {message[:100]}...")
            
            success = await self.telegram.send_message(message)
            if success:
                logger.info("Weekly review completed successfully")
            else:
                logger.warning("Weekly review completed but message delivery failed")
            
            return success
            
        except Exception as e:
            logger.error(f"Error in weekly review: {e}")
            return False


def test_get_recent_workout_logs():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    import os
    from pathlib import Path
    
    file_dir = Path(__file__).resolve().parent
    project_root = file_dir.parent.parent
    
    original_cwd = os.getcwd()
    os.chdir(project_root)
    
    try:
        os.environ.pop("AI_API_KEY", None)
        
        fetcher = ContextFetcher()
        
        result = fetcher.get_recent_workout_logs(days=7)
        
        print("\n" + "="*60)
        print("【最近 7 天训练记录测试结果】")
        print("="*60)
        print(result)
        print("="*60)
        
    finally:
        os.chdir(original_cwd)


if __name__ == "__main__":
    test_get_recent_workout_logs()
