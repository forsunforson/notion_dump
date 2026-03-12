import os
import json
import logging
import inspect
from typing import Any
try:
    from openai import AsyncOpenAI
except Exception:
    AsyncOpenAI = None

from app.utils.local_debug_logger import LocalDebugLogger

logger = logging.getLogger(__name__)


def _prune_nones(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if v is None:
                continue
            out[k] = _prune_nones(v)
        return out
    if isinstance(obj, list):
        return [_prune_nones(x) for x in obj if x is not None]
    return obj


def _sanitize_message(m: Any) -> dict | None:
    if not isinstance(m, dict):
        return None
    role = m.get("role")
    if role in ("system", "user"):
        return {"role": role, "content": "" if m.get("content") is None else str(m.get("content"))}
    if role == "assistant":
        out: dict[str, Any] = {"role": "assistant"}
        out["content"] = "" if m.get("content") is None else m.get("content")
        if m.get("tool_calls") is not None:
            out["tool_calls"] = m.get("tool_calls")
        return out
    if role == "tool":
        out: dict[str, Any] = {
            "role": "tool",
            "content": "" if m.get("content") is None else str(m.get("content")),
        }
        if m.get("tool_call_id") is not None:
            out["tool_call_id"] = m.get("tool_call_id")
        if m.get("name") is not None:
            out["name"] = m.get("name")
        return out
    return {"role": "user", "content": "" if m.get("content") is None else str(m.get("content"))}


def _summarize_msg(m: Any) -> dict[str, Any]:
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


class LLMService:
    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY")
        self.base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("AI_MODEL", "gpt-3.5-turbo")
        
        if not self.api_key:
            raise ValueError("AI_API_KEY environment variable is not set")

        if AsyncOpenAI is None:
            self.client = None
        else:
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        logger.info(f"LLMService initialized with model: {self.model}")

    async def ask_json(self, system_prompt: str, user_prompt: str) -> dict:
        if self.client is None:
            raise RuntimeError("Missing dependency: openai")
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
        if self.client is None:
            raise RuntimeError("Missing dependency: openai")
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
        if self.client is None:
            raise RuntimeError("Missing dependency: openai")
        logger.info(f"[LLM Request] Model: {self.model} (with tools, messages)")

        tool_calls_executed = 0
        local_messages: list[dict] = [m for m in (_sanitize_message(x) for x in (messages or [])) if m is not None]
        dbg = LocalDebugLogger(session_id=(os.getenv("LOCAL_DEBUG_SESSION_ID") or os.getenv("TRAE_DEBUG_SESSION_ID") or "ask-tools"))

        def tool_call_payload(tc: Any) -> dict[str, Any]:
            try:
                return _prune_nones(tc.model_dump())
            except Exception:
                return _prune_nones(
                    {
                        "id": getattr(tc, "id", None),
                        "type": getattr(tc, "type", None),
                        "function": {
                            "name": getattr(getattr(tc, "function", None), "name", None),
                            "arguments": getattr(getattr(tc, "function", None), "arguments", None),
                        },
                    }
                )

        async def execute_tool_call(tool_call: Any) -> tuple[dict[str, Any], bool]:
            function_name = tool_call.function.name
            raw_args = tool_call.function.arguments
            try:
                function_args = json.loads(raw_args) if raw_args else {}
            except Exception as e:
                return (
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": f"Error: Invalid tool arguments JSON: {str(e)}",
                    },
                    False,
                )

            logger.info(f"Executing tool: {function_name} with arg keys: {sorted(list(function_args.keys()))}")
            tool_function = tool_map.get(function_name)
            if tool_function is None:
                return (
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": f"Error: Tool {function_name} not found.",
                    },
                    False,
                )

            try:
                result = tool_function(**function_args)
                if inspect.isawaitable(result):
                    result = await result
                return (
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(result),
                    },
                    True,
                )
            except Exception as e:
                return (
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": f"Error executing tool: {str(e)}",
                    },
                    False,
                )

        try:
            while True:
                tail = [_summarize_msg(m) for m in local_messages[-12:]]
                null_content_idxs = [
                    i for i, m in enumerate(local_messages)
                    if isinstance(m, dict) and m.get("content") is None
                ]
                non_dict_idxs = [i for i, m in enumerate(local_messages) if not isinstance(m, dict)]
                dbg.emit(
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
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=local_messages,
                    tools=tools,
                    tool_choice=tool_choice,
                )

                message = response.choices[0].message
                dbg.emit(
                    "llm.tools.response_meta",
                    {
                        "assistant_content_is_none": message.content is None,
                        "assistant_content_type": type(message.content).__name__,
                        "tool_calls_count": len(message.tool_calls or []) if message.tool_calls else 0,
                    },
                )
                if message.tool_calls:
                    try:
                        tc0 = (message.tool_calls or [])[0]
                        tc0_dump = tc0.model_dump() if tc0 else {}
                        dbg.emit(
                            "llm.tools.tool_call_shape",
                            {
                                "tc0_keys": sorted(list((tc0_dump or {}).keys())),
                                "tc0_function_keys": sorted(list(((tc0_dump or {}).get("function") or {}).keys())),
                                "tc0_has_thought_signature": (
                                    ("thought_signature" in (tc0_dump or {}))
                                    or ("thoughtSignature" in (tc0_dump or {}))
                                    or ("thought_signature" in ((tc0_dump or {}).get("function") or {}))
                                    or ("thoughtSignature" in ((tc0_dump or {}).get("function") or {}))
                                ),
                            },
                        )
                    except Exception:
                        pass
                    tool_calls_payload = [tool_call_payload(tc) for tc in (message.tool_calls or [])]
                    local_messages.append(
                        _sanitize_message(
                            {
                                "role": "assistant",
                                "content": "" if message.content is None else message.content,
                                "tool_calls": tool_calls_payload,
                            }
                        )
                        or {"role": "assistant", "content": "", "tool_calls": tool_calls_payload}
                    )
                else:
                    local_messages.append(
                        _sanitize_message({"role": "assistant", "content": "" if message.content is None else message.content})
                        or {"role": "assistant", "content": ""}
                    )

                if message.tool_calls:
                    dbg.emit(
                        "llm.tools.tool_calls",
                        {
                            "count": len(message.tool_calls or []),
                            "assistant_content_is_none": message.content is None,
                        },
                    )
                    for tool_call in message.tool_calls:
                        tool_msg, executed = await execute_tool_call(tool_call)
                        if executed:
                            tool_calls_executed += 1
                        local_messages.append(tool_msg)
                else:
                    content = message.content or ""
                    dbg.emit(
                        "llm.tools.final",
                        {"tool_calls_executed": tool_calls_executed, "content_len": len(content)},
                    )
                    logger.info(f"[LLM Response] {content[:2000]}...")
                    return content, tool_calls_executed
        except Exception as e:
            logger.exception("Error in ask_with_tools_messages")
            dbg.emit(
                "llm.tools.error",
                {
                    "error_type": type(e).__name__,
                    "error_str": str(e),
                    "status_code": getattr(e, "status_code", None),
                    "body": getattr(e, "body", None),
                    "messages_len": len(local_messages),
                    "tail": [_summarize_msg(m) for m in local_messages[-12:]],
                },
            )
            raise
