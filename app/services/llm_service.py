import os
import json
import logging
import time
from pathlib import Path
import urllib.request
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

    async def ask_with_tools_messages(
        self,
        messages: list[dict],
        tools: list,
        tool_map: dict,
        tool_choice: str | dict = "auto",
    ) -> tuple[str, int]:
        logger.info(f"[LLM Request] Model: {self.model} (with tools, messages)")

        tool_calls_executed = 0
        def sanitize_message(m: object) -> dict | None:
            if not isinstance(m, dict):
                return None
            role = m.get("role")
            if role in ("system", "user"):
                return {"role": role, "content": "" if m.get("content") is None else str(m.get("content"))}
            if role == "assistant":
                out: dict = {"role": "assistant"}
                out["content"] = "" if m.get("content") is None else m.get("content")
                if m.get("tool_calls") is not None:
                    out["tool_calls"] = m.get("tool_calls")
                return out
            if role == "tool":
                out = {
                    "role": "tool",
                    "content": "" if m.get("content") is None else str(m.get("content")),
                }
                if m.get("tool_call_id") is not None:
                    out["tool_call_id"] = m.get("tool_call_id")
                if m.get("name") is not None:
                    out["name"] = m.get("name")
                return out
            return {"role": "user", "content": "" if m.get("content") is None else str(m.get("content"))}

        local_messages: list[dict] = [m for m in (sanitize_message(x) for x in (messages or [])) if m is not None]
        #region debug-point
        dbg_url = (os.getenv("TRAE_DEBUG_API_URL") or "").strip()
        dbg_session = (os.getenv("TRAE_DEBUG_SESSION_ID") or "ask-tools").strip()
        dbg_outdir = (os.getenv("TRAE_DEBUG_LOG_DIR") or ".dbg").strip()
        dbg_seq = 0

        def dbg_event(name: str, payload: dict):
            nonlocal dbg_seq
            dbg_seq += 1
            event = {
                "sessionId": dbg_session,
                "name": name,
                "seq": dbg_seq,
                "ts": int(time.time() * 1000),
                "payload": payload,
            }
            try:
                if dbg_url:
                    data = json.dumps(event, ensure_ascii=False).encode("utf-8")
                    req = urllib.request.Request(
                        dbg_url,
                        data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=2).read()
                else:
                    outdir = Path(os.getcwd()) / dbg_outdir
                    outdir.mkdir(parents=True, exist_ok=True)
                    outpath = outdir / f"trae-debug-log-{dbg_session}.ndjson"
                    with open(outpath, "a", encoding="utf-8") as f:
                        f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception:
                return

        def summarize_msg(m: object) -> dict:
            if not isinstance(m, dict):
                return {"is_dict": False, "type": type(m).__name__}
            c = m.get("content")
            tool_calls = m.get("tool_calls")
            return {
                "is_dict": True,
                "role": m.get("role"),
                "keys": sorted(list(m.keys())),
                "content_is_none": c is None,
                "content_type": type(c).__name__,
                "content_len": len(c) if isinstance(c, str) else 0,
                "has_tool_calls": tool_calls is not None,
                "tool_calls_type": type(tool_calls).__name__,
                "tool_call_id_present": "tool_call_id" in m,
                "name_present": "name" in m,
            }
        #endregion debug-point

        try:
            while True:
                #region debug-point
                tail = [summarize_msg(m) for m in local_messages[-12:]]
                null_content_idxs = [
                    i for i, m in enumerate(local_messages)
                    if isinstance(m, dict) and m.get("content") is None
                ]
                non_dict_idxs = [i for i, m in enumerate(local_messages) if not isinstance(m, dict)]
                dbg_event(
                    "llm.tools.request",
                    {
                        "base_url": self.base_url,
                        "model": self.model,
                        "tool_choice": tool_choice,
                        "tools_len": len(tools or []),
                        "messages_len": len(local_messages),
                        "non_dict_message_idxs": non_dict_idxs[:50],
                        "null_content_message_idxs": null_content_idxs[:50],
                        "tail": tail,
                    },
                )
                #endregion debug-point
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=local_messages,
                    tools=tools,
                    tool_choice=tool_choice,
                )

                message = response.choices[0].message
                #region debug-point
                dbg_event(
                    "llm.tools.response_meta",
                    {
                        "assistant_content_is_none": message.content is None,
                        "assistant_content_type": type(message.content).__name__,
                        "tool_calls_count": len(message.tool_calls or []) if message.tool_calls else 0,
                    },
                )
                #endregion debug-point
                if message.tool_calls:
                    local_messages.append(
                        sanitize_message(
                            {
                                "role": "assistant",
                                "content": "" if message.content is None else message.content,
                                "tool_calls": [
                                    {
                                        "id": tc.id,
                                        "type": tc.type,
                                        "function": {
                                            "name": tc.function.name,
                                            "arguments": tc.function.arguments,
                                        },
                                    }
                                    for tc in (message.tool_calls or [])
                                ],
                            }
                        )
                        or {"role": "assistant", "content": ""}
                    )
                else:
                    local_messages.append(
                        sanitize_message({"role": "assistant", "content": "" if message.content is None else message.content})
                        or {"role": "assistant", "content": ""}
                    )

                if message.tool_calls:
                    #region debug-point
                    dbg_event(
                        "llm.tools.tool_calls",
                        {
                            "count": len(message.tool_calls or []),
                            "assistant_content_is_none": message.content is None,
                        },
                    )
                    #endregion debug-point
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
                    #region debug-point
                    dbg_event(
                        "llm.tools.final",
                        {"tool_calls_executed": tool_calls_executed, "content_len": len(content)},
                    )
                    #endregion debug-point
                    logger.info(f"[LLM Response] {content[:2000]}...")
                    return content, tool_calls_executed
        except Exception as e:
            logger.error(f"Error in ask_with_tools_messages: {e}")
            #region debug-point
            dbg_event(
                "llm.tools.error",
                {
                    "error_type": type(e).__name__,
                    "error_str": str(e),
                    "status_code": getattr(e, "status_code", None),
                    "body": getattr(e, "body", None),
                    "messages_len": len(local_messages),
                    "tail": [summarize_msg(m) for m in local_messages[-12:]],
                },
            )
            #endregion debug-point
            return "Sorry, I encountered an error while processing your request with tools.", tool_calls_executed
