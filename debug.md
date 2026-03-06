# [OPEN] Gemini/Vertex 400: Value is not a struct: null

## Symptom
- `ask_with_tools_messages` 报错：400 `INVALID_ARGUMENT` / `Value is not a struct: null`

## Expected
- Tools 模式在 Gemini/Vertex(OpenAI-compatible) 下可稳定完成 tool-call loop

## Hypotheses (falsifiable)
1. messages 数组里存在 `null`（例如 assistant/tool 的 `content: null`），Gemini 侧严格校验导致 400。
2. `message.model_dump()` 产物含 `null` 字段或不兼容字段（例如 `function_call: null`），Gemini 侧把 `null` 当作非法 struct。
3. tool message 结构不兼容（tool_call_id/name/content 组合缺失或类型不符），Gemini 侧报 400。
4. 某条历史消息不是 dict（None/字符串混入 messages），Gemini 侧认为“Value is not a struct”。
5. tools/tool_choice 字段整体不被该兼容层支持，导致请求体校验失败（但错误文本指向 null，更可能是 1/2/4）。

## Evidence Plan
- 仅采集“结构化元信息”，不上传原始文本内容：
  - 每次请求前：messages 长度、每条 role/keys、content 是否为 None、content 长度、是否包含 tool_calls/tool_call_id 等
  - 捕获异常：异常类型/异常字符串、最近 N 条消息的结构摘要

## Debug Server
- 启动：`python /Users/bytedance/.trae-cn/builtin_skills/TRAE-debugger/tools/debug-server/python/debug-server.py --port 7777 --outdir .dbg --idle 1200 --clean`
- 环境变量：
  - `TRAE_DEBUG_API_URL=http://127.0.0.1:7777/event`
  - `TRAE_DEBUG_SESSION_ID=ask-tools-400`

