"""Low-frequency queries to the live OneBot platform: merged forwards, group members and scene names."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from string import Template
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .messages import Segment, render_body
from .onebot_messages import normalized_segment
from ..storage.store import Store, encode
from ..prompt_files import read_prompt


PlatformCall = Callable[[str, dict], Awaitable[dict]]
PAGE_CHARS = 4000
FORWARD_DEPTH = 3
FORWARD_NODES = 300
ROLES = ("owner", "admin", "member")


class OpenForwardArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str = Field(min_length=1)
    forward: int = Field(default=1, gt=0)
    offset: int = Field(default=0, ge=0)

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must be a nonblank platform message ID")
        return value


class MemberInfoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    user: str = Field(pattern=r"^onebot:[1-9][0-9]*$")


class MessageReactionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(pattern=r"^-?[1-9][0-9]*$", description='当前群中要回应的平台消息 ID。')
    emoji_id: str = Field(pattern=r"^[1-9][0-9]*$",
        description='QQ 表情编号，例如 76 赞、66 爱心、99 鼓掌、182 笑哭、264 捂脸；也可用 128077（👍）。')
    end_turn: bool = Field(default=True, description='这次贴表情完成本轮回应；还要继续说话时设为 false。')


MESSAGE_REACTION_TOOL = {"type": "function", "function": {
    "name": "message_reaction", "description": "偶尔给本群某条消息贴一个 QQ 表情回应，适合简短认同或接梗。"
    "这是低频的独立行动；通常仍使用 say 或 react。通过 NapCat、SnowLuma 的消息表情回应接口执行。",
    "parameters": MessageReactionArguments.model_json_schema(),
}}


async def message_reaction(store: Store, scene: str, args: MessageReactionArguments, call: PlatformCall) -> str:
    if store.find_message(scene, args.message) is None:
        raise ValueError(f'当前场景没有平台消息 {args.message}')
    raw = await call('set_msg_emoji_like', {'message_id': int(args.message), 'emoji_id': args.emoji_id, 'set': True})
    # SnowLuma returns data=null; NapCat returns the underlying operation result.
    if not isinstance(raw, dict) or raw.get('status') != 'ok' or raw.get('retcode') != 0:
        raise ValueError(f'set_msg_emoji_like 失败：{repr(raw)[:500]}')
    data = raw.get('data')
    if data is not None:
        result = data.get('result') if isinstance(data, dict) else None
        if result is not True and not (type(result) is int and result == 0):
            raise ValueError(f'set_msg_emoji_like 操作失败：{repr(raw)[:500]}')
    return encode({'message': args.message, 'emoji_id': args.emoji_id, 'set': True, 'status': 'sent'})


OPEN_FORWARD_TOOL = {"type": "function", "function": {
    "name": "open_forward", "description": "展开本场景已保存消息里的合并转发；message 是平台消息 ID，"
    "forward 是该消息第几个转发段，offset 是字符位置，每页 4000 字。嵌套转发最多展开 3 层。",
    "parameters": OpenForwardArguments.model_json_schema(),
}}
MEMBER_INFO_TOOL = {"type": "function", "function": {
    "name": "member_info", "description": "查询本群一名成员的平台当前资料（昵称、群名片、身份、头衔、入群与最后发言时间）；"
    "user 是实际平台账号，例如 onebot:70001。",
    "parameters": MemberInfoArguments.model_json_schema(),
}}


class GroupFilesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    folder: str | None = Field(default=None, min_length=1, description="文件夹 ID；不填列出根目录。")
    name: str = Field(default="", max_length=100, description="只列文件名包含这段文字的文件，不区分大小写；空字符串列出全部。")


GROUP_FILES_TOOL = {"type": "function", "function": {
    "name": "group_files", "description": "列出本群群文件里的真实文件和文件夹：文件名、大小、上传者、上传时间、file_id 与 busid。"
    "委托任务处理群文件时，把选中文件的 file_id、busid 和输入文件名填进 delegate 的 group_files；"
    "同名或对应哪一份不清楚时先问请求人。",
    "parameters": GroupFilesArguments.model_json_schema(),
}}


def _id(value: object, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value):
        raise ValueError(f"{field} must be a nonempty OneBot ID")
    return str(value)


def _optional_text(value: object, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    return value


def _succeeded(raw: object, action: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"{action} response must be an object: {repr(raw)[:500]}")
    if raw.get("status") != "ok" or raw.get("retcode") != 0:
        raise ValueError(f"{action} 失败：status={raw.get('status')!r} retcode={raw.get('retcode')!r} "
                         f"wording={raw.get('wording', raw.get('msg'))!r}；raw={repr(raw)[:500]}")
    data = raw.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"{action} data must be an object; raw={repr(raw)[:500]}")
    return data


@dataclass(frozen=True, slots=True)
class ForwardNode:
    uid: str
    name: str | None
    time: float
    segments: list[Segment]


def parse_forward(raw: object) -> list[ForwardNode]:
    """Parse NapCat's get_forward_msg ``data.messages`` array once at the platform boundary."""
    try:
        items = _succeeded(raw, "get_forward_msg")["messages"]
        if not isinstance(items, list):
            raise ValueError("data.messages must be an array")
        nodes = []
        for index, item in enumerate(items):
            if not isinstance(item, dict) or not isinstance(item["sender"], dict):
                raise ValueError(f"messages[{index}] must be an object with a sender object")
            sender = item["sender"]
            card = _optional_text(sender.get("card"), f"messages[{index}].sender.card")
            nickname = _optional_text(sender.get("nickname"), f"messages[{index}].sender.nickname")
            time = item["time"]
            if isinstance(time, bool) or not isinstance(time, (int, float)):
                raise ValueError(f"messages[{index}].time must be a Unix timestamp")
            wire = item["message"]
            if not isinstance(wire, list):
                raise ValueError(f"messages[{index}].message must be a segment array")
            segments = []
            for position, segment in enumerate(wire):
                if (not isinstance(segment, dict) or not isinstance(segment["type"], str) or not segment["type"]
                        or not isinstance(segment["data"], dict)):
                    raise ValueError(f"messages[{index}].message[{position}] must have type text and data object")
                if segment["type"] == "text" and not isinstance(segment["data"]["text"], str):
                    raise ValueError(f"messages[{index}].message[{position}].data.text must be text")
                segments.append(normalized_segment(segment["type"], segment["data"]))
            nodes.append(ForwardNode("onebot:" + _id(sender["user_id"], f"messages[{index}].sender.user_id"),
                                     card or nickname, float(time), segments))
        return nodes
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"get_forward_msg 返回无法解析：{error}; raw={repr(raw)[:500]}") from error


async def _expand(call: PlatformCall, forward_id: str, timezone: str, depth: int,
                  budget: list[int], lines: list[str]) -> int:
    nodes = parse_forward(await call("get_forward_msg", {"id": forward_id}))
    indent = "  " * (depth - 1)
    zone = ZoneInfo(timezone)
    for number, node in enumerate(nodes, start=1):
        if budget[0] == 0:
            lines.append(f"{indent}[其余 {len(nodes) - number + 1} 条未展开：已达 {FORWARD_NODES} 条上限]")
            break
        budget[0] -= 1
        clock = datetime.fromtimestamp(node.time, zone).isoformat(sep=" ", timespec="seconds")
        speaker = f"{node.name}({node.uid})" if node.name else f"{node.uid}"
        lines.append(f"{indent}[{number}] [{clock}] {speaker}：")
        lines.extend(f"{indent}  {line}" for line in render_body(node.segments).splitlines())
        for segment in (item for item in node.segments if item.type == "forward"):
            if budget[0] == 0:
                lines.append(f"{indent}  [其余嵌套转发未展开：已达 {FORWARD_NODES} 条上限]")
                break
            nested = segment.data.get("id")
            if nested is None:
                lines.append(f"{indent}  [嵌套转发没有平台 id，未展开]")
            elif depth == FORWARD_DEPTH:
                lines.append(f"{indent}  [嵌套转发 id={nested}：超过 {FORWARD_DEPTH} 层未展开]")
            else:
                lines.append(f"{indent}  嵌套转发 id={nested}：")
                await _expand(call, _id(nested, "forward.data.id"), timezone, depth + 1, budget, lines)
    return len(nodes)


async def open_forward(store: Store, scene: str, timezone: str, args: OpenForwardArguments,
                       call: PlatformCall) -> str:
    message = store.find_message(scene, args.message)
    if message is None:
        raise ValueError(f"当前场景没有平台消息 {args.message}")
    forwards = [segment for segment in message.segments if segment.type == "forward"]
    if args.forward > len(forwards):
        raise ValueError(f"消息 {args.message} 只有 {len(forwards)} 个合并转发段，没有第 {args.forward} 个")
    forward_id = _id(forwards[args.forward - 1].data.get("id"), "forward.data.id")
    lines: list[str] = []
    count = await _expand(call, forward_id, timezone, 1, [FORWARD_NODES], lines)
    text = "\n".join(lines)
    if args.offset > len(text):
        raise ValueError(f"offset {args.offset} exceeds forward text length {len(text)}")
    end = min(args.offset + PAGE_CHARS, len(text))
    result = {"message": args.message, "forward": args.forward, "forward_id": forward_id,
              "top_level_items": count, "offset": args.offset, "total_chars": len(text),
              "next_offset": None if end == len(text) else end, "text": text[args.offset:end]}
    return Template(read_prompt("next_forward.md")).substitute(
        scene=scene, result=encode(result)).strip()


async def scene_title(scene: str, call: PlatformCall) -> tuple[str, int | None]:
    """The group name and member count, or the private contact's nickname, for the panel."""
    platform, kind, number = scene.split(":", 2)
    action, field = ("get_group_info", "group_name") if kind == "group" else ("get_stranger_info", "nickname")
    raw = await call(action, {"group_id" if kind == "group" else "user_id": int(number)})
    try:
        data = _succeeded(raw, action)
        title = data[field]
        if not isinstance(title, str):
            raise ValueError(f"{field} must be text")
        if kind != "group":
            return title, None
        members = data["member_count"]
        if type(members) is not int or members < 0:
            raise ValueError("member_count must be a non-negative integer")
        return title, members
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{action} 返回无法解析：{error}; raw={repr(raw)[:500]}") from error


async def joined_groups(call: PlatformCall) -> list[dict]:
    raw = await call('get_group_list', {})
    try:
        if raw['status'] != 'ok' or type(raw['retcode']) is not int or raw['retcode'] != 0:
            raise ValueError('get_group_list did not succeed')
        if not isinstance(raw['data'], list):
            raise ValueError('data must be a group list')
        groups = []
        for item in raw['data']:
            group_id = _id(item['group_id'], 'group_id')
            if not isinstance(item['group_name'], str):
                raise ValueError('group_name must be text')
            groups.append({'scene': f'onebot:group:{group_id}', 'name': item['group_name'],
                           'members': item.get('member_count'), 'last_seen': None})
        return groups
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f'get_group_list 返回无法解析：{error}; raw={repr(raw)[:500]}') from error


GROUP_FILE_COUNT = 200


def _count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _entries(value: object, field: str) -> list[dict]:
    # go-cqhttp reports an empty folder as null.
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{field} must be a list of objects")
    return value


def parse_group_files(raw: object, action: str) -> dict:
    """One folder of get_group_root_files or get_group_files_by_folder (NapCat and SnowLuma share the fields)."""
    data = _succeeded(raw, action)
    try:
        files = []
        for item in _entries(data["files"], "files"):
            name = item["file_name"]
            if not isinstance(name, str) or not name:
                raise ValueError("file_name must be nonempty text")
            files.append({"file_id": _id(item["file_id"], "file_id"), "busid": _count(item["busid"], "busid"),
                          "name": name, "size": _count(item["file_size"], "file_size"),
                          "uploaded": _count(item["upload_time"], "upload_time"),
                          "uploader": _optional_text(item.get("uploader_name"), "uploader_name")})
        folders = []
        for item in _entries(data["folders"], "folders"):
            name = item["folder_name"]
            if not isinstance(name, str) or not name:
                raise ValueError("folder_name must be nonempty text")
            folders.append({"folder_id": _id(item["folder_id"], "folder_id"), "name": name,
                            "files": _count(item["total_file_count"], "total_file_count")})
        return {"files": files, "folders": folders}
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{action} 返回无法解析：{error}; raw={repr(raw)[:500]}") from error


async def group_files(call: PlatformCall, group_id: str, folder: str | None) -> dict:
    """A group's files and folders at the root, or inside ``folder``."""
    params: dict = {"group_id": int(group_id)}
    if folder is None:
        action = "get_group_root_files"
    else:
        action, params["folder_id"] = "get_group_files_by_folder", folder
    # NapCat returns file_count entries, 50 when left out; SnowLuma reads the whole folder.
    params["file_count"] = GROUP_FILE_COUNT
    return parse_group_files(await call(action, params), action)


async def group_file_url(call: PlatformCall, group_id: str, file_id: str, busid: int) -> str:
    raw = await call("get_group_file_url", {"group_id": int(group_id), "file_id": file_id, "busid": busid})
    url = _succeeded(raw, "get_group_file_url").get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError(f"get_group_file_url 返回无法解析：url must be an http address; raw={repr(raw)[:500]}")
    return url


def parse_member(raw: object, *, group_id: str, qq: str) -> dict:
    """Parse get_group_member_info once; identity fields must match the request."""
    try:
        data = _succeeded(raw, "get_group_member_info")
        if _id(data["group_id"], "group_id") != group_id or _id(data["user_id"], "user_id") != qq:
            raise ValueError(f"response is for group {data['group_id']!r} user {data['user_id']!r}")
        role = data["role"]
        if role not in ROLES:
            raise ValueError(f"role must be one of {list(ROLES)}: {role!r}")
        result = {"user": "onebot:" + qq, "nickname": data["nickname"], "card": data["card"], "role": role}
        for field in ("nickname", "card"):
            if not isinstance(result[field], str):
                raise ValueError(f"{field} must be text")
        for field in ("join_time", "last_sent_time"):
            value = data[field]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field} must be an integer Unix timestamp")
            result[field] = value
        for field in ("title", "level"):
            if field in data:
                result[field] = _optional_text(data[field], field)
        return result
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"get_group_member_info 返回无法解析：{error}; raw={repr(raw)[:500]}") from error


async def member_info(scene: str, timezone: str, args: MemberInfoArguments, call: PlatformCall) -> str:
    platform, kind, group_id = scene.split(":", 2)
    if kind != "group":
        raise ValueError("member_info 只在群场景可用")
    raw = await call("get_group_member_info", {"group_id": int(group_id), "user_id": int(args.user.split(":", 1)[1]), "no_cache": True})
    member = parse_member(raw, group_id=group_id, qq=args.user.split(":", 1)[1])
    zone = ZoneInfo(timezone)
    for field in ("join_time", "last_sent_time"):
        member[field] = datetime.fromtimestamp(member[field], zone).isoformat(sep=" ", timespec="seconds")
    return Template(read_prompt("next_member_info.md")).substitute(
        scene=scene, result=encode(member)).strip()


async def list_group_files(scene: str, timezone: str, args: GroupFilesArguments, call: PlatformCall) -> str:
    """One folder of this group's files, filtered by name, with upload times in the host's time zone."""
    found = await group_files(call, scene.split(":", 2)[2], args.folder)
    wanted = args.name.casefold()
    zone = ZoneInfo(timezone)
    files = [{**item, "uploaded": datetime.fromtimestamp(item["uploaded"], zone).isoformat(timespec="minutes")}
             for item in found["files"] if wanted in item["name"].casefold()]
    return encode({"folder": args.folder, "files": files, "folders": found["folders"]})


async def download_group_file(call: PlatformCall, group_id: str, file_id: str, busid: int, max_bytes: int,
                              transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    """A group file's current content from the address OneBot gives, refused once it passes ``max_bytes``."""
    url = await group_file_url(call, group_id, file_id, busid)
    async with httpx.AsyncClient(timeout=60, trust_env=False, follow_redirects=True, transport=transport) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ValueError(f"群文件超过 worker.max_file_bytes：{len(data)} > {max_bytes}")
    return bytes(data)


def group_file_fetch(call: PlatformCall, group_id: str):
    """The delegate fetcher for one group's files: download by file_id and busid."""
    async def fetch(item, max_bytes: int) -> bytes:
        return await download_group_file(call, group_id, item.file_id, item.busid, max_bytes)
    return fetch
