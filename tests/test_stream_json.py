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
    line = '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"running"},{"type":"tool_use","name":"Read","input":{"file_path":"a"}}]}}'
    evs = parse_stream_line(line)
    assert {"kind": "text", "text": "running"} in evs
    assert {"kind": "tool_use", "tool": "Read", "input": {"file_path": "a"}} in evs
