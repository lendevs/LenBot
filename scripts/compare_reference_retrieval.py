"""Reference lookup on a fixed fictional corpus, one row per case of the reference comparison set.

    uv run --no-sync python scripts/compare_reference_retrieval.py [--instance DIR] [--answer]

Without ``--instance`` only full text is compared. ``--instance`` reads that instance's
``lenbot.config.json`` and adds vectors through ``memory.local.embedding``; ``--answer`` also asks
each question in a simulated group with the instance's ``mind`` model and records the reply, the
wait for the first reply and the tokens used. Vectors and answers are paid requests.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
from types import SimpleNamespace

from len_bot.next.persona.knowledge import PersonaDocument
from len_bot.next.reference.library import ReferenceLibrary, reference_embedding

SCENE, OTHER = "onebot:group:80001", "onebot:group:80002"
FILLER = "\n\n".join(f"第 {number} 条：活动期间请保持手机畅通，有事在群里说一声。" for number in range(40))
HANDBOOK = f"""# 秋季登山活动手册

## 报名

报名截止时间是十一月三日晚上八点，在群公告的表格里填写姓名和学号。

## 须知

{FILLER}

## 集合

十一月八日周六早上八点半在学校东门集合，统一坐大巴出发，八点四十五分准时发车。

## 费用

每人八十元，包含往返大巴和一天的意外保险，午饭自理。

## 安全

全程不得单独离队，下山时间为下午四点，迟到超过十五分钟视为放弃乘车。
"""
NOTICE = "社团会费每学期五十元，在第一次例会时交给财务。\n"
OTHER_GROUP = "# 读书会\n\n本周读书会在图书馆二楼，周日下午三点开始。\n"
KNOWLEDGE = "# 角色资料\n\n- 爱好：周末爬山，但是有点恐高，只走缓坡。\n- 最近在画一本关于各地早餐的绘本。\n"
UPDATED = HANDBOOK.replace("十一月三日晚上八点", "十一月五日晚上十点")


@dataclass(frozen=True)
class Case:
    name: str
    scene: str
    question: str
    query: str
    evidence: tuple[str, ...]
    # Expected location of the first evidence: filename and heading or page.
    location: tuple[str, str | int] | None = None
    # Facts the reply should state, each a regular expression.
    answer: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    setup: str | None = None


CASES = [
    Case("long-middle", SCENE, "这次登山几点在哪集合？", "集合 东门", ("八点半在学校东门集合",),
         ("秋季登山活动手册.md", "集合"), (r"(8|八)\s*点\s*(半|30)", "东门")),
    Case("paraphrase", SCENE, "出去玩一趟要掏多少钱呀", "掏多少钱", ("每人八十元",),
         ("秋季登山活动手册.md", "费用"), (r"80|八十",)),
    Case("pdf-page", SCENE, "期末论文最晚什么时候交？", "essay deadline", ("essay deadline is Friday noon",),
         ("final.pdf", 2), (r"(周五|星期五|Friday)", r"(中午|noon|12)")),
    Case("after-update", SCENE, "报名截止是哪天？", "报名 截止", ("十一月五日晚上十点",),
         ("秋季登山活动手册.md", "报名"), (r"(11|十一)\s*月\s*(5|五)",), ("十一月三日",), setup="update"),
    Case("after-delete", SCENE, "会费交多少？", "会费", (), None, (), ("五十元",), setup="delete"),
    Case("other-group", OTHER, "登山几点集合？", "登山 集合", (), None, (), ("东门", "八点半")),
    Case("no-answer", SCENE, "活动那天会下雨吗？", "下雨 天气", (), None, (), ()),
    Case("both-sources", SCENE, "你会去爬山吗？手册里下山是几点", "爬山 登山 下山", ("恐高", "下山时间为下午四点"),
         None, (r"(4|四)\s*点",)),
]


def pdf(pages: list[str]) -> bytes:
    """A minimal PDF with one Helvetica line per page."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Kids [" + " ".join(f"{4 + 2 * index} 0 R" for index in range(len(pages)))
               + f"] /Count {len(pages)} >>",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for index, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objects.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * index} 0 R >>")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    data, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n{body}\nendobj\n".encode()
    table = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    data += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{table}\n%%EOF\n".encode()
    return bytes(data)


def prepare(root: Path, library: ReferenceLibrary) -> None:
    directory = library.directory(SCENE)
    directory.mkdir(parents=True)
    (directory / "秋季登山活动手册.md").write_text(HANDBOOK, encoding="utf-8")
    (directory / "会费通知.txt").write_text(NOTICE, encoding="utf-8")
    (directory / "final.pdf").write_bytes(pdf(["Final arrangements", "The essay deadline is Friday noon."]))
    library.directory(OTHER).mkdir(parents=True)
    (library.directory(OTHER) / "读书会.md").write_text(OTHER_GROUP, encoding="utf-8")


def apply(setup: str | None, library: ReferenceLibrary) -> None:
    if setup == "update":
        (library.directory(SCENE) / "秋季登山活动手册.md").write_text(UPDATED, encoding="utf-8")
    elif setup == "delete":
        (library.directory(SCENE) / "会费通知.txt").unlink()


def judge_hits(case: Case, hits) -> dict:
    texts = [hit.text for hit in hits[:5]]
    first = next((hit for hit in hits if any(item in hit.text for item in case.evidence)), None)
    location = None if first is None else (first.path, first.page if first.page is not None else first.heading[-1])
    leaked = [item for item in case.absent if any(item in text for text in texts)]
    return {
        "evidence": all(any(item in text for text in texts) for item in case.evidence),
        "location": case.location is None or location == case.location,
        "absent": not leaked,
        "irrelevant_chars": sum(len(text) for text in texts if not any(item in text for item in case.evidence)),
        "hits": [[hit.path, hit.page or (hit.heading[-1] if hit.heading else None), list(hit.matched)] for hit in hits[:5]],
    }


async def retrieval(embedding_factory) -> list[dict]:
    rows = []
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        library = ReferenceLibrary(root, embedding=embedding_factory())
        prepare(root, library)
        persona = SimpleNamespace(id="sample", knowledge={"角色资料.md": PersonaDocument(KNOWLEDGE, ())})
        for case in CASES:
            apply(case.setup, library)
            started = time.monotonic()
            hits = await library.search(case.scene, persona, case.query)
            rows.append({"case": case.name, "seconds": round(time.monotonic() - started, 3), **judge_hits(case, hits)})
    return rows


def group_event(scene: str, ident: int, text: str, bot: str) -> dict:
    return {"post_type": "message", "message_type": "group", "self_id": int(bot), "group_id": int(scene.rsplit(":", 1)[1]),
            "user_id": 70001, "message_id": ident, "time": int(time.time()),
            "sender": {"nickname": "群友阿青", "card": "阿青", "role": "member"},
            "message": [{"type": "at", "data": {"qq": bot}}, {"type": "text", "data": {"text": " " + text}}]}


async def answers(host, client) -> list[dict]:
    from len_bot.next.chat.attention import SceneRunner
    from len_bot.next.chat.session import Chat
    from len_bot.next.models.client import ChatModel
    from len_bot.next.persona.profile import load_persona
    from len_bot.next.storage.store import Store

    rows = []
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        package = root / "persona"
        shutil.copytree(Path(__file__).resolve().parents[1] / "examples/personas/companion", package)
        shutil.rmtree(package / "knowledge")
        (package / "knowledge").mkdir()
        (package / "knowledge" / "角色资料.md").write_text(KNOWLEDGE, encoding="utf-8")
        persona = load_persona(package)
        base = host.scene_config(next(iter(host.scenes)))
        bot = host.bot_id.split(":", 1)[1]
        with Store(root / "state.db") as store:
            async with AsyncExitStack() as stack:
                mind = await stack.enter_async_context(ChatModel(host.model_settings("mind")))
                vision = (await stack.enter_async_context(ChatModel(host.model_settings("vision")))
                          if host.models.roles.vision is not None else None)
                library = ReferenceLibrary(root, embedding=None if client is None else reference_embedding(client, store, None))
                prepare(root, library)
                done: asyncio.Queue = asyncio.Queue()
                runners = {}
                for scene in (SCENE, OTHER):
                    config = base.model_copy(update={"scene": scene, "delivery": "simulated", "memory": None, "worker": None,
                                                     "learning": None, "memory_plugin": None, "recap_plugin": None})
                    object.__setattr__(config, "_source_root", root)
                    chat = Chat(config, persona, store, mind, vision=vision, reference=library)
                    runners[scene] = SceneRunner(chat, lambda result, scene=scene: done.put_nowait((scene, result)))
                tasks = [asyncio.create_task(runner.run()) for runner in runners.values()]
                for ident, case in enumerate(CASES, 1001):
                    apply(case.setup, library)
                    before = store.db.execute("SELECT coalesce(sum(input), 0), coalesce(sum(output), 0) FROM usage").fetchone()
                    last = store.db.execute("SELECT coalesce(max(seq), 0) FROM messages").fetchone()[0]
                    started = time.time()
                    runners[case.scene].receive(group_event(case.scene, ident, case.question, bot))
                    while (await asyncio.wait_for(done.get(), 300))[0] != case.scene:
                        pass
                    said = [json.loads(row[0]) for row in store.db.execute(
                        "SELECT body FROM messages WHERE scene=? AND seq>? AND json_extract(body, '$.is_self') ORDER BY seq",
                        (case.scene, last))]
                    reply = " ".join(segment["data"]["text"] for message in said for segment in message["segments"]
                                     if segment["type"] == "text")
                    wait = store.db.execute("SELECT first_expression_at - wake_received_at FROM turns"
                                            " WHERE scene=? AND started>=? ORDER BY started LIMIT 1",
                                            (case.scene, started)).fetchone()
                    after = store.db.execute("SELECT coalesce(sum(input), 0), coalesce(sum(output), 0) FROM usage").fetchone()
                    cited = case.location is None or (Path(case.location[0]).stem in reply and str(case.location[1]) in reply)
                    rows.append({"case": case.name, "reply": reply,
                                 "facts": all(re.search(pattern, reply) for pattern in case.answer),
                                 "absent": not any(item in reply for item in case.absent),
                                 "cited": cited,
                                 "first_reply_seconds": None if wait is None or wait[0] is None else round(wait[0], 1),
                                 "input_tokens": after[0] - before[0], "output_tokens": after[1] - before[1]})
                for runner in runners.values():
                    runner.close_input()
                await asyncio.gather(*tasks, return_exceptions=True)
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--answer", action="store_true")
    options = parser.parse_args()
    result = {"text": await retrieval(lambda: None)}
    if options.instance is None:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return
    from len_bot.next.config import load_host_config
    from len_bot.next.memory.embeddings import EmbeddingClient, EmbeddingSettings
    from len_bot.next.storage.store import Store

    host = load_host_config(options.instance.resolve())
    binding = None if host.memory is None else host.memory.local.embedding
    async with AsyncExitStack() as stack:
        client = None
        if binding is not None:
            provider = host.models.providers[binding.provider]
            client = await stack.enter_async_context(EmbeddingClient(EmbeddingSettings(
                **binding.model_dump(), base_url=provider.base_url, api_key=provider.api_key, proxy=provider.proxy)))
            with tempfile.TemporaryDirectory() as folder, Store(Path(folder) / "usage.db") as store:
                result["hybrid"] = await retrieval(lambda: reference_embedding(client, store, None))
        if options.answer:
            result["answer"] = await answers(host, client)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
