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
        out = []
        for b in _content_blocks(obj.get("message", {})):
            if isinstance(b, dict) and b.get("type") == "tool_result":
                out.append({"kind": "tool_result", "text": _flatten(b.get("content", ""))})
        return out[0] if len(out) == 1 else (out if out else None)

    if t != "assistant":
        return None

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
