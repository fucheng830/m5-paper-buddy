# m5 agent chat(stream-json)设计

## Context

m5-paper-buddy 的 web 模式(`tools/claude_code_bridge.py --web`)已实现手机 chat 续聊,但有两个体验限制让"手机像 chat app 一样实时驱动 claude"体验差:

1. **非流式**:`_send_prompt`(`tools/claude_code_bridge.py:373`)用 `claude -p text --continue`,同步调用——等 claude 跑完一次性拿 stdout,用户看不到中间过程。
2. **running 不能注入**:m5 是 **hook 观察者**,不持有 claude 进程(claude 是用户在终端独立开的)。running 的 claude 锁了 session 文件,`--continue` 注入不进去,只能对"空闲(done)"会话续聊。

根因:限制 1 是实现问题(可改),限制 2 是架构问题(hook 观察者不拥有 claude 进程的 stdin)。

本设计用 **stream-json agent 层**解决两者——借鉴 [AionUI](https://github.com/iofficeai/aionui) 的 spawn + stream-json + chat 解析模式,同时**保留** m5 现有的多终端 hook 监控能力。两套会话并存。

## 目标

- **新增 daemon 自启的 stream-json agent 会话**:手机创建会话(选项目 cwd)→ daemon spawn `claude --output-format stream-json --verbose` → chat 流式驱动(text 增量 + 工具调用卡片),**running 中可追加消息**
- **保留**现有 hook 监控:终端独立开的 claude 仍在仪表盘显示(状态/上下文/审批/通知/空闲续聊)
- 两类 session 并存在一个 web UI(图标区分)
- **范围**:先 claude;codex 多 agent 扩展(借鉴 AionUI)作为后续

## 非目标(YAGNI)

- 不做多 agent 并行组队(AionUI Cowork 特性)
- 不重写现有终端监控路径
- 不做语音输入

## 架构(并存)

一个 daemon + 一个 web UI,两类 session 共存:

| 类型 | 来源 | 驱动方式 | 状态来源 |
|---|---|---|---|
| **terminal session**(现有,保留) | 用户终端开的 claude | hook 上报 → 仪表盘/审批/通知;空闲时 `--continue` 续聊 | hooks(transcript JSONL) |
| **agent session**(新增) | daemon spawn stream-json claude | 手机 chat → 写 stdin → stdout 流式事件 | stream-json stdout |

agent session 是 daemon 自启的 claude,同样走 hooks(同一个 claude binary,hooks 已装),所以仪表盘也能显示其工具调用/上下文;但 agent chat 的**流式 text** 来自 stream-json(更实时),hook 补充状态。

## 组件

### 1. agent manager(新增,`claude_code_bridge.py` 内)

管理 daemon 自启的 stream-json claude 进程。

```
AGENTS: dict[agent_id, {
  agent_id, cwd, project,
  process,            # asyncio subprocess(Windows 用 ProactorEventLoop)
  status: 'starting'|'streaming'|'idle'|'error'|'stopped',
  created_at, last_msg_at,
  reader_task,        # asyncio task 读 stdout 流
}]
```

API:
- `spawn_agent(cwd, project) -> agent_id`:在 cwd spawn `claude --output-format stream-json --verbose --input-format stream-json`(streaming input mode);起 reader task 逐行解析 stdout
- `send_msg(agent_id, text)`:写 stdin(stream-json user message 格式)
- `stop_agent(agent_id)`:终止进程 + 清理
- reader:stdout 每行 JSON → 分类 → 推 WS + 更新 status

复用现有:`WS_CLIENTS` / `send_line()`(广播)、`STATE_LOCK`、`_append_session_transcript`(transcript 记录)。

### 2. stream-json 事件解析(新增)

claude stdout 每行一个 JSON 事件,分类(实现时对照 [Streaming Output 文档](https://code.claude.com/docs/en/agent-sdk/streaming-output) 确认 schema):

- assistant text delta → `{type:'agent_event', agent_id, kind:'text', text}`
- tool_use → `{type:'agent_event', agent_id, kind:'tool_use', tool, input}`
- tool_result → `{type:'agent_event', agent_id, kind:'tool_result', ...}`
- result(完成)→ `{type:'agent_event', agent_id, kind:'done', ...}` + status=idle
- error → `{type:'agent_event', agent_id, kind:'error', message}` + status=error

### 3. WS 协议扩展(在现有协议上增量)

客户端→服务端(新):
- `{cmd:'agent_new', cwd, project}` → 创建 agent 会话
- `{cmd:'agent_msg', agent_id, text}` → 发消息(写 stdin)
- `{cmd:'agent_stop', agent_id}` → 停止

服务端→客户端(新):
- `{type:'agent_event', agent_id, kind, ...}`
- `{type:'agent_list', agents:[{agent_id, project, status, ...}]}`
- heartbeat 的 `sessions[]` 增加 agent session(带 `type:'agent'` 标记)

复用现有 WS 通道(`send_line` 广播 + `on_json_obj` 路由)。

### 4. `web_buddy.html` 升级

- 新建 agent 入口:选项目 cwd(配置列表 `~/.claude-buddy/projects.json` 或手输绝对路径)
- **agent chat 视图**:流式 text 增量渲染、工具调用卡片(可折叠)、状态条(streaming/idle/error)、running 中输入框可继续发(排队/追加指示)
- 仪表盘:terminal + agent 两类 session,图标/标签区分;点 agent session 进 chat 流式视图
- 保留 terminal session 视图(现有 `--continue` 续聊)
- 复用现有 `md()` markdown 渲染、消息 bubble、AskUserQuestion overlay、通知/声音

### 5. hook 监控(保留,不动)

现有 `_session_start`/`_pretool`/`_user_prompt`/`_posttool`/`_session_stop` 等不变。agent session(daemon 自启的 claude)也触发这些 hooks,仪表盘自然包含。

## 数据流

```
手机输入 → WS {cmd:'agent_msg', agent_id, text}
        → agent_manager.send_msg → claude stdin(stream-json user msg)
claude stdout → asyncio 逐行 → 解析分类 → WS {type:'agent_event', agent_id, kind, ...}
        → web 流式渲染(text 增量 / 工具卡片)
running 中再发 → send_msg 写 stdin(claude 排队/中断)
```

## 关键实现点 / 风险

1. **streaming input mode 验证(核心风险)**:running 追加依赖 claude 的 streaming input(stdin 持续可写)。实现第一步:对照 [streaming-vs-single-mode 文档](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode) 确认 `--input-format stream-json` 的 stdin 消息格式,实测 running 追加是否工作。
   - **退路**:若 streaming input 不可用,用 single mode——每条消息 `claude -p text --resume <session_id> --output-format stream-json`(新进程,流式输出,但 running 追加受限:只能等当前完成再发下一条)。

2. **cwd/项目选择**:新建 agent 时从配置列表(`~/.claude-buddy/projects.json`)或手输绝对路径选;daemon 校验目录存在。

3. **工具权限**:agent session 走 hooks,沿用 web 模式现有 `_pretool` 逻辑——auto-approve 除 AskUserQuestion(`:1046`)。像 AionUI 自主驱动;若要审批门,后续加配置。

4. **Windows spawn**:claude 是 `claude.cmd`,subprocess spawn + asyncio(ProactorEventLoop)读 stdout 流;沿用现有 `CLAUDE_CODE_GIT_BASH_PATH` 环境变量处理(`:396`)。

5. **进程生命周期**:agent crash/退出 → status=error,web 提示,保留 transcript;手动 stop;空闲超时(可选,后续)。

6. **本地 claude 路径**:本地工作站 claude shim 路径串了 anaconda(`D:\Program Files\anaconda3\Library\c\...`),开发前需修;或在 0.13 开发测试(那里 claude.cmd 正常)。

## 文件改动

| 文件 | 改动 |
|---|---|
| `tools/claude_code_bridge.py` | 新增 agent manager + stream-json 解析 + WS 协议扩展(大改,但保留现有 hook 路径) |
| `tools/web_buddy.html` | 新建 agent 入口 + agent chat 流式视图 + 仪表盘两类 session |
| `README.md` | 补 agent chat 模式说明 |
| hooks 配置(`tools/hooks_settings.json` 等) | 无需改(hooks 不变) |

## 验证

1. **streaming input 验证**:手动 spawn `claude --output-format stream-json --verbose --input-format stream-json`,确认 stdin 消息格式 + running 追加行为(决定走 streaming input 还是退 single mode)
2. **0.13 跑 daemon --web**:手机新建 agent(选项目)→ 发消息 → 验证流式 text + 工具卡片渲染
3. **running 追加**:agent 处理中再发消息 → 验证排队/追加
4. **共存**:终端开个 claude → 仪表盘同时显示 terminal + agent session
5. **AskUserQuestion**(agent session 内)→ 触屏 4 选项

## 范围

先 claude。codex 多 agent(借鉴 AionUI 扩展 agent manager 支持多 binary)作为后续迭代。
