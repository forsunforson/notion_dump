import os
import json
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY")
        self.base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("AI_MODEL", "gpt-3.5-turbo")
        
        if not self.api_key:
            raise ValueError("AI_API_KEY environment variable is not set")
        
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        logger.info(f"LLMService initialized with model: {self.model}")

    async def ask_json(self, system_prompt: str, user_prompt: str) -> dict:
        full_req = f"System: {system_prompt}\nUser: {user_prompt}"
        print(f"[LLM Req] {full_req[:1000]}")
        
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
            if not result_json:
                logger.error("Empty response from LLM")
                return {}
            
            print(f"[LLM Resp] {result_json[:1000]}")
            
            result = json.loads(result_json)
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error in ask_json: {e}")
            return {}

    async def ask_text(self, system_prompt: str, user_prompt: str, max_tokens: int = 800) -> str:
        full_req = f"System: {system_prompt}\nUser: {user_prompt}"
        print(f"[LLM Req] {full_req[:1000]}")
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=max_tokens,
                stream=False
            )
            
            content = response.choices[0].message.content
            if not content:
                logger.error("Empty response from LLM")
                return ""
            
            print(f"[LLM Resp] {content[:1000]}")
            
            return content
            
        except Exception as e:
            logger.error(f"Error in ask_text: {e}")
            return ""
