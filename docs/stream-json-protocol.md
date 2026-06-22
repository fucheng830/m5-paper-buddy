# stream-json 协议备忘录(0.13 实测)

- **日期**:2026-06-22
- **环境**:0.13(Windows,claude 2.1.168,Python 3.14),`claude.CMD` 在 PATH
- **来源**:m5 plan Task 1 协议探针

## 命令(streaming input mode,持久进程)

```
claude -p --input-format stream-json --output-format stream-json --verbose --replay-user-messages
```

单进程,stdin 持续可写(running 中追加),stdout 流式 NDJSON(每行一个 JSON)。

## stdout 事件(实测)

| type | 说明 | 解析器处理 |
|---|---|---|
| `system` (subtype=init) | 初始化:cwd/session_id/tools/mcp_servers/model/permissionMode | 忽略 |
| `system` (subtype=thinking_tokens) | 逐 token thinking 进度(大量行) | 忽略 |
| `assistant` | 助手消息,`message.content[]` 含 `thinking` block(忽略)和 `text` block(提取) | 提取 text |
| `user` (--replay-user-messages 回显) | stdin 写入的 user message 回显 | 可忽略(确认接收) |
| `result` | 本轮完成:`subtype`/`is_error`/`result`/`session_id`/`usage`/`modelUsage` | 提取 done |

真实示例(截取):
```json
{"type":"assistant","message":{"role":"assistant","model":"glm-5.2","content":[{"type":"text","text":"Hi! How can I help you today?"}]},"session_id":"7bf7..."}
{"type":"result","subtype":"success","is_error":false,"result":"Hi!...","session_id":"7bf7...","modelUsage":{"claude-opus-4-8[1m]":{"inputTokens":28649,"outputTokens":99}}}
```

## stdin 格式(实测确认 ✅)

NDJSON user message(末尾 `\n`):
```json
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"用户输入"}]}}
```

实测:msg1 `"what is 2+2?"` → `4`;msg2 `"say hello"` → `hello`。

## running 追加(实测确认 ✅)

**工作**。持久进程,stdin 持续可写。msg1 处理中写 msg2 → claude 排队(msg1 result 后处理 msg2,产出两个 result)。

## 决策

**用 streaming input(持久进程)**。Task 3 `agent_manager` spawn 单进程,stdin 写消息,stdout 流式 readline。无需 single mode 退路。

## agent_manager 实现注意

- **bufsize 警告**:Python 3.14 subprocess `bufsize=1` 在 binary mode 不支持(回退默认 buffer)。asyncio subprocess 用 `readline()` 读,不受影响;若用 sync subprocess,用 `text=True` 或 binary + readline。
- **Windows**:`claude` 是 `claude.CMD`,`shutil.which("claude")` 拿到;asyncio 用 `WindowsProactorEventLoopPolicy`。
- **CLAUDE_CODE_GIT_BASH_PATH**:沿用 `claude_code_bridge.py:396` 现有处理。
- **apiKeySource:none**(init 里):实测仍成功(0.13 有认证/代理网关,`model:glm-5.2` 提示走代理)。不影响 agent 功能。
