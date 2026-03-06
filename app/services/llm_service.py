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
        logger.info(f"[LLM Request] Model: {self.model}")
        logger.info(f"[LLM Request] System prompt: {system_prompt[:200]}...")
        logger.info(f"[LLM Request] User prompt: {user_prompt[:1000]}...")
        
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
            
            logger.info(f"[LLM Response] {result_json[:2000]}...")
            
            result = json.loads(result_json)
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error in ask_json: {e}")
            return {}

    async def ask_text(self, system_prompt: str, user_prompt: str, max_tokens: int = 800) -> str:
        logger.info(f"[LLM Request] Model: {self.model}")
        logger.info(f"[LLM Request] System prompt: {system_prompt[:200]}...")
        logger.info(f"[LLM Request] User prompt: {user_prompt[:1000]}...")
        
        try:
            request_kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "stream": False,
            }

            num_ctx_env = os.getenv("AI_NUM_CTX")
            base_url_lower = (self.base_url or "").lower()
            if "localhost" in base_url_lower:
                num_ctx = int(num_ctx_env) if num_ctx_env else 32768
                request_kwargs["extra_body"] = {"options": {"num_ctx": num_ctx}}

            response = await self.client.chat.completions.create(**request_kwargs)
            
            content = response.choices[0].message.content
            if not content:
                logger.error("Empty response from LLM")
                return ""
            
            logger.info(f"[LLM Response] {content[:2000]}...")
            
            return content
            
        except Exception as e:
            logger.error(f"Error in ask_text: {e}")
            return ""

    async def ask_with_tools(self, system_prompt: str, user_prompt: str, tools: list, tool_map: dict) -> str:
        """
        Ask LLM with tool support. Handles the tool execution loop.
        """
        logger.info(f"[LLM Request] Model: {self.model} (with tools)")
        
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            while True:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto"
                )
                
                message = response.choices[0].message
                
                # Append assistant's message to conversation history
                try:
                    messages.append(message.model_dump())
                except Exception:
                    messages.append({"role": "assistant", "content": message.content})
                
                if message.tool_calls:
                    logger.info(f"[LLM Tool Call] {len(message.tool_calls)} tools called")
                    
                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)
                        
                        logger.info(f"Executing tool: {function_name} with args: {function_args}")
                        
                        if function_name in tool_map:
                            tool_function = tool_map[function_name]
                            
                            # Execute the tool function
                            # Note: Assuming tool functions are synchronous for now based on current implementation
                            try:
                                function_response = tool_function(**function_args)
                            except Exception as e:
                                function_response = f"Error executing tool: {str(e)}"
                                
                            messages.append({
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": str(function_response),
                            })
                        else:
                            logger.warning(f"Tool {function_name} not found in tool_map")
                            messages.append({
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": f"Error: Tool {function_name} not found.",
                            })
                else:
                    # No more tool calls, return the final response
                    content = message.content
                    logger.info(f"[LLM Response] {content[:2000]}...")
                    return content
                    
        except Exception as e:
            logger.error(f"Error in ask_with_tools: {e}")
            return "Sorry, I encountered an error while processing your request with tools."

    async def ask_with_tools_messages(
        self,
        messages: list[dict],
        tools: list,
        tool_map: dict,
        tool_choice: str | dict = "auto",
    ) -> tuple[str, int]:
        logger.info(f"[LLM Request] Model: {self.model} (with tools, messages)")

        tool_calls_executed = 0
        local_messages: list[dict] = list(messages)

        try:
            while True:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=local_messages,
                    tools=tools,
                    tool_choice=tool_choice,
                )

                message = response.choices[0].message
                try:
                    local_messages.append(message.model_dump())
                except Exception:
                    local_messages.append({"role": "assistant", "content": message.content})

                if message.tool_calls:
                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)
                        logger.info(f"Executing tool: {function_name} with args: {function_args}")

                        if function_name in tool_map:
                            tool_function = tool_map[function_name]
                            try:
                                function_response = tool_function(**function_args)
                                tool_calls_executed += 1
                            except Exception as e:
                                function_response = f"Error executing tool: {str(e)}"

                            local_messages.append(
                                {
                                    "tool_call_id": tool_call.id,
                                    "role": "tool",
                                    "name": function_name,
                                    "content": str(function_response),
                                }
                            )
                        else:
                            local_messages.append(
                                {
                                    "tool_call_id": tool_call.id,
                                    "role": "tool",
                                    "name": function_name,
                                    "content": f"Error: Tool {function_name} not found.",
                                }
                            )
                else:
                    content = message.content or ""
                    logger.info(f"[LLM Response] {content[:2000]}...")
                    return content, tool_calls_executed
        except Exception as e:
            logger.error(f"Error in ask_with_tools_messages: {e}")
            return "Sorry, I encountered an error while processing your request with tools.", tool_calls_executed
