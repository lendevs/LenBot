"""Stand-in for Pi 0.87.1 in RPC mode, driven by markers in the prompt text.

It speaks the JSONL commands and events that ``PiRpc`` parses, reads the
generated ``models.json`` and ``task-api.json`` like the image's extension, and
reaches the host only through the model bridge. ``LENBOT_CONTROL`` names the
host directory mounted at ``/run/lenbot`` when the stand-in runs unsandboxed. Markers it acts on, in order:

- ``[进度]`` appends a ``lenbot_progress`` entry
- ``[提问]`` asks one ``input`` question; ``[确认]`` asks one ``confirm``
- ``[等待]`` blocks until a ``steer`` command arrives
- ``[交付]`` writes ``out/report.txt`` and calls ``/task/deliver-file``
- ``[失败]`` ends the assistant message with ``stopReason: error``
- ``[探测]`` tries the writes, reads and connections listed after ``探测：`` and
  reports each outcome
- ``[联网]`` sends the requests listed after ``联网：`` through ``HTTP_PROXY``
- ``[环境]`` reports the proxy variables of its own process
- ``[写入]`` writes one file per size listed after ``写入：`` into ``out/``

Every prompt is appended to ``session.jsonl`` in the working directory, so a
continued task can show that it reopened the same session.
"""

import errno
import json
import os
from pathlib import Path
import queue
import socket
import sys
import threading
import urllib.error
import urllib.request


ARGUMENTS = sys.argv[1:]
PROVIDER = MODEL = None
if "--provider" in ARGUMENTS:
    PROVIDER = ARGUMENTS[ARGUMENTS.index("--provider") + 1]
    MODEL = ARGUMENTS[ARGUMENTS.index("--model") + 1]
CONTROL = Path(os.environ.get("LENBOT_CONTROL", "/run/lenbot"))
AGENT = Path(os.environ["PI_CODING_AGENT_DIR"])
inbox: queue.Queue = queue.Queue()
steering: list[str] = []


def read_stdin() -> None:
    for line in sys.stdin.buffer:
        inbox.put(json.loads(line))
    inbox.put(None)


def emit(body: dict) -> None:
    sys.stdout.buffer.write(json.dumps(body, ensure_ascii=False).encode() + b"\n")
    sys.stdout.buffer.flush()


def handle(command: dict) -> None:
    kind = command["type"]
    if kind == "get_state":
        emit({"id": command["id"], "type": "response", "command": kind, "success": True,
              "data": {"model": {"provider": PROVIDER, "id": MODEL}}})
    elif kind == "steer":
        steering.append(command["message"])
        emit({"id": command["id"], "type": "response", "command": kind, "success": True})
    else:
        emit({"id": command["id"], "type": "response", "command": kind, "success": False,
              "error": f"stand-in does not implement {kind}"})


def receive(wanted) -> dict:
    """Handle commands until one record matches, the way Pi keeps serving RPC while a tool waits."""
    while True:
        record = inbox.get()
        if record is None:
            raise SystemExit(0)
        if wanted(record):
            return record
        handle(record)


def post(port: int, path: str, token: str, body: dict) -> bytes:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        return response.read()


def ask_model(prompt: str) -> str:
    provider = json.loads((AGENT / "models.json").read_text())["providers"][PROVIDER]
    port = int(provider["baseUrl"].rsplit(":", 1)[1].split("/", 1)[0])
    raw = post(port, "/v1/chat/completions", provider["apiKey"], {
        "model": MODEL, "stream": True, "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": prompt}]})
    text = []
    for line in raw.decode().splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            for choice in json.loads(line[6:]).get("choices", []):
                text.append(choice.get("delta", {}).get("content") or "")
    return "".join(text)


def probe(targets: dict) -> dict:
    """Each attempted boundary crossing and how it ended: the success word or the errno name."""
    def outcome(action, success: str) -> str:
        try:
            action()
            return success
        except OSError as error:
            return errno.errorcode.get(error.errno, type(error).__name__)
    results = {}
    for path in targets["writes"]:
        results["write " + path] = outcome(lambda: Path(path).write_text("probe"), "written")
    for path in targets["reads"]:
        results["read " + path] = outcome(lambda: Path(path).read_bytes(), "read")
    for host, port in targets["connections"]:
        results[f"connect {host}:{port}"] = outcome(
            lambda: socket.create_connection((host, port), timeout=2).close(), "connected")
    return results


def fetch(requests: list[dict]) -> list[str]:
    """Each request's status, the proxy's refusal text, or the client error."""
    proxy = os.environ.get("HTTP_PROXY")
    if proxy is None:
        return ["no proxy"] * len(requests)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    results = []
    for item in requests:
        body = b"x" * item["bytes"] if item.get("bytes") else None
        request = urllib.request.Request(item["url"], data=body, method=item.get("method", "GET"))
        try:
            with opener.open(request, timeout=30) as response:
                results.append(f"{response.status}")
        except urllib.error.HTTPError as error:
            results.append(f"HTTP {error.code}: {error.read().decode(errors='replace')[:300]}")
        except OSError as error:
            results.append(f"{type(error).__name__}: {error}")
    return results


def question(number: int, body: dict) -> dict:
    ident = f"standin-question-{number}"
    emit({"type": "extension_ui_request", "id": ident, **body})
    return receive(lambda record: record.get("type") == "extension_ui_response" and record.get("id") == ident)


def run(message: str) -> None:
    session = Path("session.jsonl")
    with session.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"prompt": message}, ensure_ascii=False) + "\n")
    executions = len(session.read_text(encoding="utf-8").splitlines())
    emit({"type": "agent_start"})
    emit({"type": "message_start", "message": {"role": "assistant", "content": []}})
    reply = ask_model(message)
    emit({"type": "message_update", "usage": {"input": 1, "output": 1},
          "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": reply}})
    lines = [f"第{executions}次执行", f"模型：{reply}"]
    if "[进度]" in message:
        emit({"type": "entry_appended", "entry": {"type": "custom", "customType": "lenbot_progress",
                                                  "data": {"text": "已读完要求"}}})
    if "[提问]" in message:
        answer = question(1, {"method": "input", "title": "要哪种格式？"})
        lines.append("回答：" + ("未回答" if answer.get("cancelled") else answer["value"]))
    if "[确认]" in message:
        answer = question(2, {"method": "confirm", "title": "确认执行？", "message": "覆盖 out/report.txt"})
        lines.append(f"确认：{answer.get('confirmed')}")
    if "[写入]" in message:
        sizes, _ = json.JSONDecoder().raw_decode(message.split("写入：", 1)[1])
        Path("out").mkdir(exist_ok=True)
        for number, size in enumerate(sizes):
            Path(f"out/fill-{number}.bin").write_bytes(b"x" * size)
    if "[等待]" in message:
        while not steering:
            handle(receive(lambda record: record.get("type") == "steer"))
    if "[探测]" in message:
        targets, _ = json.JSONDecoder().raw_decode(message.split("探测：", 1)[1])
        lines.append("探测结果：" + json.dumps(probe(targets), ensure_ascii=False))
    if "[联网]" in message:
        requests, _ = json.JSONDecoder().raw_decode(message.split("联网：", 1)[1])
        lines.append("联网结果：" + json.dumps(fetch(requests), ensure_ascii=False))
    if "[环境]" in message:
        names = ("HTTP_PROXY", "NO_PROXY", "NODE_USE_ENV_PROXY")
        lines.append("环境：" + json.dumps({name: os.environ.get(name) for name in names}, ensure_ascii=False))
    lines.extend(f"追加：{text}" for text in steering)
    steering.clear()
    if "[交付]" in message:
        Path("out").mkdir(exist_ok=True)
        Path("out/report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        api = json.loads((CONTROL / "task-api.json").read_text())
        provider = json.loads((AGENT / "models.json").read_text())["providers"][PROVIDER]
        port = int(provider["baseUrl"].rsplit(":", 1)[1].split("/", 1)[0])
        result = json.loads(post(port, "/task/deliver-file", api["token"],
                                 {"path": "out/report.txt", "name": "报告.txt", "note": "测试交付"}))
        lines.append(f"交付编号：{result['id']}")
    text = "\n".join(lines)
    emit({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                                             "stopReason": "error" if "[失败]" in message else "stop"}})
    emit({"type": "agent_end", "messages": [], "willRetry": False})
    emit({"type": "agent_settled"})


def main() -> None:
    if ARGUMENTS == ["--version"]:
        print("0.87.1")
        return
    threading.Thread(target=read_stdin, daemon=True).start()
    while True:
        command = receive(lambda record: record.get("type") == "prompt")
        emit({"id": command["id"], "type": "response", "command": "prompt", "success": True})
        run(command["message"])


if __name__ == "__main__":
    main()
