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
import sys
import time

# Windows asyncio subprocess needs ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from stream_json import parse_stream_line   # same-dir import (tools/ is not a package; bridge.py runs as `python tools/claude_code_bridge.py`)

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
