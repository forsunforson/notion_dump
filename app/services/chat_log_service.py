import logging
from typing import Optional

from app.services.notion_service import NotionService

logger = logging.getLogger(__name__)


class ChatLogService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ChatLogService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        try:
            self.notion = NotionService()
        except Exception as e:
            logger.warning(f"NotionService disabled for ChatLog: {e}")
            self.notion = None
        self._initialized = True

    def log_message(self, role: str, content: str):
        """
        Log a chat message to Notion.
        """
        if not self.notion:
            return
            
        content_str = str(content or "").strip()
        if not content_str:
            return

        try:
            self.notion.append_to_daily_chat_log(role=role, content=content_str)
        except Exception as e:
            logger.error(f"Failed to log chat message: {e}")
