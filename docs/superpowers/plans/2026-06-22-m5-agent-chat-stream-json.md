# m5 agent chat(stream-json)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 m5-paper-buddy web 模式新增 daemon 自启的 stream-json agent 会话(running 可追加、流式 text + 工具卡片),保留现有终端 hook 监控。

**Architecture:** 并存——`terminal` session(hook 监控,保留)+ `agent` session(daemon spawn `claude` stream-json,新增)。daemon agent manager 用 asyncio 持有 claude 子进程,stdin 写消息、stdout 流式解析。借鉴 AionUI 的 spawn + stream-json + chat-parse。

**Tech Stack:** Python 3 asyncio(subprocess)、claude CLI stream-json、WebSocket(现有)、原生 HTML/JS、pytest(纯函数测试)。

**Spec:** `docs/superpowers/specs/2026-06-22-m5-agent-chat-stream-json-design.md`

---

## 协议参考(Task 1 探针确认后可能修订)

命令(单进程,stdin 持续可写):
```
claude -p --input-format stream-json --output-format stream-json --verbose --replay-user-messages
```

stdout NDJSON 事件(每行一个,基于 [cheatsheet](https://takopi.dev/reference/runners/claude/stream-json-cheatsheet/)):
- `{"type":"system","subtype":"init",...}` — 初始化
- `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"..."},{"type":"tool_use","name":"...","input":{...}}]}}` — 助手消息
- `{"type":"user","message":{"role":"user","content":[{"type":"tool_result",...}]}}` — 工具结果回传
- `{"type":"result","subtype":"success","result":"...","session_id":"...",...}` — 本轮完成

stdin NDJSON(third-party,Task 1 实测确认):
- user message: `{"type":"user","message":{"role":"user","content":[{"type":"text","text":"用户输入"}]}}`

> ⚠️ `--input-format stream-json` 的 stdin 格式官方未完整文档化。**Task 1 在 0.13 实测确认**,产出 `docs/stream-json-protocol.md`;若与上述不符,先改本 plan 再继续 Task 3+。

## File Structure

| 文件 | 责任 |
|---|---|
| `tools/stream_json.py` | **新**:纯函数 stream-json 解析器(可单测) |
| `tools/agent_manager.py` | **新**:agent 进程管理(spawn/send/read/stop,asyncio) |
| `tools/claude_code_bridge.py` | **改**:接入 agent_manager + WS 协议扩展(保留现有 hook 路径不动) |
| `tools/web_buddy.html` | **改**:agent chat 视图(流式 + 工具卡片)+ 仪表盘两类 session |
| `tests/test_stream_json.py` | **新**:解析器 pytest |
| `docs/stream-json-protocol.md` | **Task 1 产出**:0.13 实测的协议备忘录 |
| `requirements.txt` 或 README | 标注 `pytest` dev 依赖 |

**拆分理由**:解析器(纯函数,易测)与 agent_manager(asyncio I/O,难单测)分开;agent_manager 独立成模块,`claude_code_bridge.py` 只做集成,避免它继续膨胀(已 1300+ 行)。

---

## Task 1: 协议探针(0.13 实测确认)

**Files:**
- Create: `docs/stream-json-protocol.md`

- [ ] **Step 1: 确认 0.13 claude 支持 stream-json flags**

Run(via SSH):
```bash
ssh 192.168.0.13 'cmd /c "claude --help 2>&1 | findstr /i \"input-format output-format stream-json verbose\""'
```
Expected: 输出含 `--input-format`, `--output-format`, `stream-json`, `--verbose`。若无,需先升级 0.13 的 claude(`npm i -g @anthropic-ai/claude-code`),停止本 plan。

- [ ] **Step 2: 实测 stdout 事件格式**

Run:
```bash
ssh 192.168.0.13 'cmd /c "claude -p \"say hi in 3 words\" --output-format stream-json --verbose 2>nul"'
```
Expected: 多行 NDJSON,含 `{"type":"system",...}`、`{"type":"assistant",...}`(content 里有 `{"type":"text",...}`)、结尾 `{"type":"result","subtype":"success",...}`。把前 5 行原文复制到 `docs/stream-json-protocol.md`。

- [ ] **Step 3: 实测 stdin user message 格式(关键未文档化项)**

Run(通过管道喂一条 user message):
```bash
ssh 192.168.0.13 'cmd /c "echo {\"type\":\"user\",\"message\":{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"what is 2+2\"}]}} | claude -p --input-format stream-json --output-format stream-json --verbose --replay-user-messages 2>nul"'
```
Expected: claude 收到消息并回复(NDJSON assistant 事件)。若报错或无回复,尝试替代格式:`{"type":"user","content":"what is 2+2"}` 或纯文本行。**把确认能工作的 stdin 格式记入 `docs/stream-json-protocol.md`**。

- [ ] **Step 4: 实测 running 中追加消息**

Run(用一个长任务 + 两次 stdin 写入,验证第二条是否排队/中断):
```bash
ssh 192.168.0.13 'cmd /c "(echo {\"type\":\"user\",\"message\":{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"count to 100 slowly\"}]}} & timeout /t 2 & echo {\"type\":\"user\",\"message\":{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"actually stop\"}]}}) | claude -p --input-format stream-json --output-format stream-json --verbose 2>nul"'
```
Expected: 观察输出里第二个 user message 是否被处理(中断/排队)。**把 running 追加行为记入备忘录**,并决策:
- 若追加工作 → 后续用 streaming input(单进程)
- 若不工作 → 后续用 single mode(`claude -p msg --resume <session_id> --output-format stream-json`,每条消息新进程)

- [ ] **Step 5: 写协议备忘录并 commit**

`docs/stream-json-protocol.md` 记录:确认的命令、stdout 事件示例、**确认的 stdin 格式**、running 追加行为、streaming-vs-single 决策。
```bash
cd D:/workspace/projects/dev/m5-paper-buddy
git add docs/stream-json-protocol.md
git commit -m "docs: record stream-json protocol probe results (0.13)"
```

> Task 1 完成后,若备忘录与本 plan 的"协议参考"不符,更新本 plan 对应 task 的代码再继续。

---

## Task 2: stream-json 解析器(TDD 纯函数)

**Files:**
- Create: `tools/stream_json.py`
- Create: `tests/test_stream_json.py`

- [ ] **Step 1: 建 pytest 环境**

`requirements-dev.txt`(项目根):
```
pytest>=8.0
```
Run: `pip install -r requirements-dev.txt`(0.13 或本地 venv)。

- [ ] **Step 2: 写失败测试**

`tests/test_stream_json.py`:
```python
from tools.stream_json import parse_stream_line

def test_parses_assistant_text():
    line = '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"hello"}]}}'
    ev = parse_stream_line(line)
    assert ev == {"kind": "text", "text": "hello"}

def test_parses_tool_use():
    line = '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}'
    ev = parse_stream_line(line)
    assert ev == {"kind": "tool_use", "tool": "Bash", "input": {"command": "ls"}}

def test_parses_result_done():
    line = '{"type":"result","subtype":"success","result":"done"}'
    ev = parse_stream_line(line)
    assert ev == {"kind": "done", "text": "done"}

def test_ignores_system_init():
    line = '{"type":"system","subtype":"init","session_id":"abc"}'
    assert parse_stream_line(line) is None

def test_invalid_json_returns_none():
    assert parse_stream_line("not json") is None

def test_handles_multi_block_content():
    # assistant message with both text and tool_use → emit first text, caller sees tool via second pass
    line = '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"running"},{"type":"tool_use","name":"Read","input":{"file_path":"a"}}]}}'
    # parse_stream_line returns list when multiple actionable blocks exist
    evs = parse_stream_line(line)
    assert {"kind": "text", "text": "running"} in evs
    assert {"kind": "tool_use", "tool": "Read", "input": {"file_path": "a"}} in evs
```

- [ ] **Step 3: 跑测试确认失败**

Run: `pytest tests/test_stream_json.py -v`
Expected: FAIL(`ModuleNotFoundError: tools.stream_json`)。

- [ ] **Step 4: 实现解析器**

`tools/stream_json.py`:
```python
"""Parse claude --output-format stream-json NDJSON lines into chat events.

Returns one of:
  {"kind": "text", "text": str}
  {"kind": "tool_use", "tool": str, "input": dict}
  {"kind": "tool_result", "text": str}
  {"kind": "done", "text": str}
or None (system/init / uninteresting / invalid).
When a single assistant line carries multiple actionable content blocks,
returns a list of the above dicts.
"""
import json


def _content_blocks(message):
    content = (message or {}).get("content", [])
    return content if isinstance(content, list) else []


def parse_stream_line(line):
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None

    t = obj.get("type")
    if t == "result":
        return {"kind": "done", "text": str(obj.get("result", ""))}

    if t == "user":
        # tool_result echoes come back as user messages with tool_result content
        out = []
        for b in _content_blocks(obj.get("message", {})):
            if isinstance(b, dict) and b.get("type") == "tool_result":
                out.append({"kind": "tool_result", "text": _flatten(b.get("content", ""))})
        return out[0] if len(out) == 1 else (out if out else None)

    if t != "assistant":
        return None  # system/init etc.

    out = []
    for b in _content_blocks(obj.get("message", {})):
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text" and b.get("text"):
            out.append({"kind": "text", "text": b["text"]})
        elif bt == "tool_use":
            out.append({"kind": "tool_use", "tool": str(b.get("name", "?")), "input": b.get("input", {})})
    if not out:
        return None
    return out[0] if len(out) == 1 else out


def _flatten(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_stream_json.py -v`
Expected: 6 passed。

- [ ] **Step 6: Commit**

```bash
git add tools/stream_json.py tests/test_stream_json.py requirements-dev.txt
git commit -m "feat: add stream-json line parser with tests"
```

---

## Task 3: agent_manager(asyncio 进程管理)

**Files:**
- Create: `tools/agent_manager.py`

- [ ] **Step 1: 实现模块(基于 Task 1 备忘录的协议)**

`tools/agent_manager.py`(若 Task 1 决策为 single mode,见 Step 3 退路):
```python
"""Manage daemon-spawned stream-json claude agent sessions.

Each agent = one long-lived `claude -p --input-format stream-json
--output-format stream-json --verbose --replay-user-messages` process.
stdout is read line-by-line in an asyncio task; each line is parsed and
pushed to an event callback. stdin accepts NDJSON user messages.
"""
import asyncio
import json
import os
import shutil
import time

from tools.stream_json import parse_stream_line

# agent_id -> Agent
AGENTS = {}


class Agent:
    def __init__(self, agent_id, cwd, project, on_event):
        self.id = agent_id
        self.cwd = cwd
        self.project = project
        self.on_event = on_event          # async cb(agent_id, event_dict)
        self.proc = None
        self.status = "starting"
        self.reader = None
        self.created_at = time.time()

    async def start(self):
        claude_bin = shutil.which("claude") or "claude"
        env = os.environ.copy()
        # Windows: claude needs git-bash path (existing bridge.py pattern)
        if os.name == "nt" and not env.get("CLAUDE_CODE_GIT_BASH_PATH"):
            bash = shutil.which("bash")
            if bash:
                fixed = bash.replace("\\usr\\bin\\", "\\bin\\")
                env["CLAUDE_CODE_GIT_BASH_PATH"] = fixed if os.path.isfile(fixed) else bash
        self.proc = await asyncio.create_subprocess_exec(
            claude_bin, "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose", "--replay-user-messages",
            cwd=self.cwd, env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.status = "streaming"
        self.reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        assert self.proc and self.proc.stdout
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                ev = parse_stream_line(text)
                if ev is None:
                    continue
                events = ev if isinstance(ev, list) else [ev]
                for e in events:
                    await self.on_event(self.id, e)
                    if e.get("kind") == "done":
                        self.status = "idle"
        except Exception as e:
            await self.on_event(self.id, {"kind": "error", "text": f"reader: {e}"})
            self.status = "error"

    async def send(self, text):
        if not self.proc or not self.proc.stdin:
            return
        # stdin NDJSON user message — format per docs/stream-json-protocol.md (Task 1)
        msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        }, ensure_ascii=False) + "\n"
        self.proc.stdin.write(msg.encode("utf-8"))
        await self.proc.stdin.drain()
        self.status = "streaming"

    async def stop(self):
        self.status = "stopped"
        if self.reader:
            self.reader.cancel()
        if self.proc:
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass


async def spawn_agent(cwd, project, on_event):
    agent_id = f"agent_{int(time.time() * 1000)}"
    a = Agent(agent_id, cwd, project, on_event)
    AGENTS[agent_id] = a
    await a.start()
    return agent_id


def get(agent_id):
    return AGENTS.get(agent_id)


def list_agents():
    return [{"id": a.id, "project": a.project, "cwd": a.cwd, "status": a.status,
             "type": "agent"} for a in AGENTS.values()]
```

- [ ] **Step 2: Windows asyncio 事件循环策略**

`tools/agent_manager.py` 顶部 import 后加(Windows ProactorEventLoop 支持 subprocess):
```python
import sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
```

- [ ] **Step 3: 退路——若 Task 1 决策为 single mode**

若备忘录判定 streaming input 不工作,改 `send()` 为:不写 stdin,而是 spawn 一次性 `claude -p text --resume <session_id> --output-format stream-json --verbose`(用 `--resume` 续历史)。此时 Agent 不持有长进程,而是 per-message spawn(用 `asyncio.create_subprocess_exec` + 读 stdout 到 result 事件)。把这段替换 `send` + 去掉长进程 `_read_loop` 的 stdin 依赖。**具体代码以备忘录决策为准重写。**

- [ ] **Step 4: 冒烟测试(手动,在 0.13)**

Run(临时脚本验证 agent_manager 能 spawn + 收事件):
```bash
ssh 192.168.0.13 'cd C:\<m5 path> && python -c "import asyncio; from tools.agent_manager import spawn_agent; 
async def cb(aid,ev): print(aid,ev)
async def m():
    aid=await spawn_agent(r\"C:\Users\Administrator\", \"test\", cb)
    a=__import__(\"tools.agent_manager\",fromlist=[\"get\"]).get(aid)
    await a.send(\"say hi\"); await asyncio.sleep(8)
asyncio.run(m())"'
```
Expected: 打印 `{"kind":"text","text":"..."}` 和 `{"kind":"done",...}`。若报错,对照备忘录调 send 格式。

- [ ] **Step 5: Commit**

```bash
git add tools/agent_manager.py
git commit -m "feat: add asyncio agent manager for stream-json claude sessions"
```

---

## Task 4: 接入 daemon + WS 协议扩展

**Files:**
- Modify: `tools/claude_code_bridge.py`

- [ ] **Step 1: import + agent 事件循环启动**

在 `claude_code_bridge.py` 顶部 import 区加:
```python
from agent_manager import spawn_agent, get as get_agent, list_agents, AGENTS
```
(同目录 import,用 `from agent_manager import`;若包结构不同,调整。)

在 `main()` 里 `--web` 分支内启动一个 asyncio 线程跑 agent 事件循环:
```python
import threading, asyncio
def _agent_loop():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(asyncio.Future())  # keep loop alive; agent coroutines scheduled onto it
if args.web:
    threading.Thread(target=_agent_loop, daemon=True).start()
```
> ⚠️ agent_manager 的协程需跑在这个 dedicated loop 上。`send`/`spawn` 从 WS 线程调用时用 `asyncio.run_coroutine_threadsafe(coro, agent_loop)`。把 loop 存到模块全局:`AGENT_LOOP = None`,在 `_agent_loop` 里 `global AGENT_LOOP; AGENT_LOOP = asyncio.get_running_loop()`。

- [ ] **Step 2: WS 路由 agent 命令**

在 `on_json_obj(obj)`(现有,`src` 实际 `tools/claude_code_bridge.py:329`)的 `if/elif cmd ==` 链里加:
```python
    elif cmd == "agent_new":
        cwd = obj.get("cwd", "")
        project = obj.get("project", "") or os.path.basename(cwd.rstrip("/\\"))
        if not cwd or not os.path.isdir(cwd):
            return  # invalid, ignore (web should validate first)
        fut = asyncio.run_coroutine_threadsafe(
            spawn_agent(cwd, project, _on_agent_event), AGENT_LOOP)
        aid = fut.result(timeout=30)
        _broadcast({"type": "agent_list", "agents": list_agents()})
    elif cmd == "agent_msg":
        aid = obj.get("agent_id", "")
        a = get_agent(aid)
        if a:
            asyncio.run_coroutine_threadsafe(a.send(obj.get("text", "")), AGENT_LOOP)
    elif cmd == "agent_stop":
        aid = obj.get("agent_id", "")
        a = get_agent(aid)
        if a:
            asyncio.run_coroutine_threadsafe(a.stop(), AGENT_LOOP)
            _broadcast({"type": "agent_list", "agents": list_agents()})
```

- [ ] **Step 3: agent 事件 → WS 广播回调**

加函数(`_broadcast` 复用现有 `send_line` 的 WS 广播;若无,用 `WS_CLIENTS` 直接发):
```python
async def _on_agent_event(agent_id, event):
    payload = json.dumps({"type": "agent_event", "agent_id": agent_id, **event},
                         ensure_ascii=False)
    with WS_LOCK:
        for c in WS_CLIENTS:
            try: c["send_q"].put_nowait(payload)
            except Exception: pass
    # also bump dashboard if status changed
    _broadcast({"type": "agent_list", "agents": list_agents()})
```
(`send_q` 是现有 WS 客户端的 asyncio queue,见 `_ws_handler_async`。)

- [ ] **Step 4: heartbeat 暴露 agent session**

在 `build_heartbeat()` 的 `sessions_list` 构造后(`:666` 附近)加:
```python
        sessions_list.extend(list_agents())  # agent sessions混入仪表盘
```
(terminal session 仍由现有 `SESSIONS_TOTAL` 逻辑产出;agent session 带 `type:"agent"` 标记。)

- [ ] **Step 5: 手动验证 WS 命令**

启动 daemon(`--web`),用 `websocat` 或浏览器 console 发:
```js
ws.send(JSON.stringify({cmd:"agent_new", cwd:"C:\\Users\\Administrator", project:"test"}))
```
Expected: 收到 `{"type":"agent_list",...}` 含新 agent;再发 `{cmd:"agent_msg",agent_id:"...",text:"hi"}` → 收 `agent_event` text/done。

- [ ] **Step 6: Commit**

```bash
git add tools/claude_code_bridge.py
git commit -m "feat: wire agent manager into daemon + WS protocol"
```

---

## Task 5: web_buddy.html — agent chat 视图

**Files:**
- Modify: `tools/web_buddy.html`

- [ ] **Step 1: 仪表盘区分 terminal / agent session**

在 `renderSidebar()` 的 `session-item` 模板里,按 `s.type` 加图标/标签:
```js
const typeTag = s.type==='agent' ? '<span class="s-type agent">AGENT</span>' : '<span class="s-type term">TERM</span>';
// 加进 .s-top,并在 CSS 加 .s-type{font-size:9px;padding:1px 5px;border-radius:3px} .s-type.agent{background:#e3f2fd;color:#0055aa} .s-type.term{background:#eee;color:#888}
```
点击 agent session 走 `selectSession`(现有),但 detail 视图按 type 切 agent chat(Step 2)vs terminal transcript(现有)。

- [ ] **Step 2: agent chat 视图(流式 + 工具卡片)**

在 `applyMsg(obj)` 加 agent 事件处理:
```js
if (obj.type === 'agent_event') {
    const sid = obj.agent_id;
    if (!state.agentChats) state.agentChats = {};
    if (!state.agentChats[sid]) state.agentChats[sid] = [];
    const chat = state.agentChats[sid];
    const e = obj;
    if (e.kind === 'text') {
        // append to last assistant bubble if streaming, else new
        const last = chat[chat.length-1];
        if (last && last.role==='assistant' && last.streaming) last.text += e.text;
        else chat.push({role:'assistant', text:e.text, streaming:true, time:_hm()});
    } else if (e.kind === 'tool_use') {
        chat.push({role:'tool', tool:e.tool, input:e.input, time:_hm()});
    } else if (e.kind === 'tool_result') {
        chat.push({role:'tool_result', text:e.text, time:_hm()});
    } else if (e.kind === 'done') {
        const last = chat[chat.length-1];
        if (last && last.streaming) last.streaming = false;
    } else if (e.kind === 'error') {
        chat.push({role:'system', text:'ERROR: '+e.text, time:_hm()});
    }
    if (sid === state.selectedSid) renderAgentChat();
    return;
}
if (obj.type === 'agent_list') {
    for (const a of (obj.agents||[])) state.sessions[a.id] = {...state.sessions[a.id], ...a};
    render(); return;
}
```

- [ ] **Step 3: renderAgentChat + 工具卡片渲染**

```js
function renderAgentChat(){
    const chat=document.getElementById('chat');
    const msgs=state.agentChats[state.selectedSid]||[];
    chat.innerHTML=msgs.map(m=>{
        if(m.role==='tool')return `<div class="msg system"><div class="bubble">🔧 <b>${esc(m.tool)}</b><pre>${esc(JSON.stringify(m.input,null,2))}</pre></div></div>`;
        if(m.role==='tool_result')return `<div class="msg system"><div class="bubble">↳ <pre>${esc(m.text.slice(0,500))}</pre></div></div>`;
        const c=m.role==='assistant'?md(m.text):esc(m.text);
        return `<div class="msg ${m.role}"><div class="bubble">${c}</div>${m.time?`<div class="msg-time">${esc(m.time)}</div>`:''}</div>`;
    }).join('');
    chat.scrollTop=chat.scrollHeight;
}
function _hm(){return new Date().toLocaleTimeString('en',{hour:'2-digit',minute:'2-digit'});}
```

- [ ] **Step 4: 新建 agent 入口 + 发消息**

toolbar 加"＋ Agent"按钮,点击弹 cwd 选择(从配置或 prompt)。`sendPrompt()` 改为判断当前 session type:
```js
// 选 agent session 时,sendPrompt 发 agent_msg;否则现有 --continue prompt
function sendPrompt(){
    const ta=document.getElementById('input'); const text=ta.value.trim();
    if(!text||!state.connected)return;
    const s=state.sessions[state.selectedSid];
    if(s && s.type==='agent'){
        sendCmd({cmd:'agent_msg', agent_id:s.full||state.selectedSid, text});
        (state.agentChats[state.selectedSid] ||= []).push({role:'user',text,time:_hm()});
        renderAgentChat();
    } else {
        sendCmd({cmd:'prompt', text, sid:s.full});  // 现有
    }
    ta.value=''; autoResize();
}
```
新建 agent:
```js
function newAgentSession(){
    const cwd=prompt('项目目录(绝对路径):','');
    if(!cwd)return;
    sendCmd({cmd:'agent_new', cwd, project:cwd.split(/[\\/]/).pop()});
}
```

- [ ] **Step 5: 手动验证(浏览器)**

打开 daemon web,点"＋ Agent"输入 cwd → 仪表盘出现 AGENT 会话 → 点进 → 输入消息 → 验证流式 text + 工具卡片。

- [ ] **Step 6: Commit**

```bash
git add tools/web_buddy.html
git commit -m "feat: agent chat view in web_buddy (streaming + tool cards)"
```

---

## Task 6: 仪表盘共存 + 杂项

**Files:**
- Modify: `tools/web_buddy.html`, `README.md`

- [ ] **Step 1: terminal + agent 共存验证**

终端(0.13)开一个真 claude session(hook 上报)→ web 仪表盘应同时显示 TERM(终端)和 AGENT(daemon)两类 session,各自可点进。

- [ ] **Step 2: README 补 agent chat 模式**

`README.md` "日常使用"后加一节:
```markdown
## 🤖 Agent Chat 模式(--web)

不插墨水屏,手机/浏览器直接 chat 驱动 claude:
1. `python tools/claude_code_bridge.py --web`
2. 浏览器打开 `http://<IP>:9876/`
3. 点 "＋ Agent" 选项目目录 → 发消息 → 流式回复 + 工具调用卡片
4. running 中可继续追加消息

同时保留多终端 session 监控(仪表盘 TERM/AGENT 共存)。详见 `docs/superpowers/specs/2026-06-22-m5-agent-chat-stream-json-design.md`。
```

- [ ] **Step 3: Commit**

```bash
git add README.md tools/web_buddy.html
git commit -m "docs: document agent chat mode + dashboard coexistence"
```

---

## Task 7: 端到端验证(0.13 + 手机)

**Files:** 无(验证)

- [ ] **Step 1: 0.13 部署最新代码**

```bash
cd D:/workspace/projects/dev/m5-paper-buddy
git push origin feat/web-buddy
ssh 192.168.0.13 'cmd /c "cd C:\<m5 path> && git pull"'
```

- [ ] **Step 2: 启动 + 手机访问**

```bash
ssh 192.168.0.13 'cmd /c "cd C:\<m5 path> && start-web.bat"'
```
手机浏览器(同网或 Tailscale): `http://<0.13-ip>:9876/`

- [ ] **Step 3: 验收清单**

- [ ] 新建 agent(选项目)→ 发 "list files" → 流式 text + `tool_use(Bash)` 卡片 + `tool_result`
- [ ] agent running 中再发一条 → 验证追加/排队
- [ ] 终端另开 claude → 仪表盘两类 session 共存
- [ ] AskUserQuestion(agent 内)→ 触屏 4 选项
- [ ] 杀掉 agent → 状态 error + transcript 保留

- [ ] **Step 4: 记录已知限制 + 收尾**

若 running 追加不工作(Task 1 退路已切 single mode),在 README 注明"running 中消息排队到当前轮完成"。最终 commit 任何验证中发现的 fix。

---

## Self-Review(写计划后自查)

**Spec 覆盖**:
- daemon 自启 stream-json agent → Task 3 ✓
- 流式 text + 工具卡片 → Task 2(解析)+ Task 5(渲染)✓
- running 可追加 → Task 1 验证 + Task 3 send ✓
- 保留终端 hook 监控 → Task 4 Step 4(不动现有 hook)+ Task 6 共存 ✓
- WS 协议扩展 → Task 4 ✓
- cwd 选择 → Task 5 Step 4 ✓
- 工具权限(沿用 auto-approve)→ 不改 `_pretool`,agent session 走现有 hooks ✓
- Windows → Task 3 Step 2(ProactorEventLoop)+ git-bash ✓
- 本地 claude 修复 → Task 1 依赖 0.13(备注)✓

**Placeholder 扫描**:Task 3 Step 3(single mode 退路)说"以备忘录决策为准重写"——这是 Task 1 产出的真实分叉,不是偷懒 placeholder;给了 streaming input 完整代码 + 退路指引。Task 1 的实测命令具体可跑。

**类型一致**:`parse_stream_line` 返回 dict 或 list 或 None,Task 3 `_read_loop` 正确处理 `isinstance(ev, list)`。`agent_event` 的 `kind` 字段(text/tool_use/tool_result/done/error)Task 3→5 一致。`sessions[].type` ("agent")Task 4→5 一致。
