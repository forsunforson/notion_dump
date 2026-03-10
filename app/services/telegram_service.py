import os
import logging
import aiohttp
from typing import Optional

from app.services.notion_service import NotionService

logger = logging.getLogger(__name__)


class TelegramService:
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        try:
            self.notion = NotionService()
        except Exception as e:
            logger.warning(f"NotionService disabled: {e}")
            self.notion = None
        
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set. Telegram notifications will be disabled.")
        if not self.chat_id:
            logger.warning("TELEGRAM_CHAT_ID not set. Telegram notifications will be disabled.")
    
    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)
    
    async def send_message(self, text: str) -> bool:
        if not self.is_configured:
            logger.warning("Telegram not configured. Skipping message send.")
            return False

        final_text = text if text is not None else ""
        if self.notion and str(final_text).strip():
            self.notion.append_to_daily_chat_log(role="Bot", content=str(final_text))
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        payload = {
            "chat_id": self.chat_id,
            "text": final_text
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("ok"):
                            logger.info("Telegram message sent successfully")
                            return True
                        else:
                            logger.error(f"Telegram API error: {result.get('description')}")
                            return False
                    else:
                        response_text = await response.text()
                        logger.error(f"Telegram HTTP error {response.status}: {response_text}")
                        return False
        except aiohttp.ClientError as e:
            logger.error(f"Telegram network error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram message: {e}")
            return False
