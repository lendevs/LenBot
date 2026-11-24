"""Public HTTP bytes on the numeric address checked for each redirect hop."""

from __future__ import annotations

import ipaddress
import zlib
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from ..work.egress_policy import blocked_address_reason, public_addresses
from .host_traffic import MeteredTransport, admit


MAX_REDIRECTS = 5
ERROR_BYTES = 2048
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _target(url: str) -> tuple[str, str, int, str, str]:
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise ValueError("HTTP read URL contains whitespace or control characters")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.hostname is None:
        raise ValueError(f"HTTP read requires a complete HTTP(S) URL: {url[:200]}")
    if parts.username is not None or parts.password is not None:
        raise ValueError("HTTP read URL must not contain credentials")
    host = parts.hostname
    if "%" in host:
        raise ValueError("HTTP read URL must not contain an address scope identifier")
    port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
    if port == 0:
        raise ValueError("HTTP read URL port must be 1..65535")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        ascii_host = host.encode("idna").decode("ascii")
    else:
        ascii_host = str(address)
    host_header = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    if parts.port is not None:
        host_header += f":{port}"
    clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
    return clean_url, ascii_host, port, host_header, parts.scheme


async def _numeric_address(host: str, port: int, fake_ip_networks: tuple,
                           public_dns_url: str | None, timeout_seconds: float) -> str:
    try:
        address = str(ipaddress.ip_address(host))
    except ValueError:
        return (await public_addresses(host, port, fake_ip_networks, public_dns_url, timeout_seconds))[0]
    else:
        reason = blocked_address_reason(address)
    if reason is not None:
        raise ValueError(f"HTTP read destination {address} blocked: {reason}")
    return address


async def _error_fragment(response: httpx.Response) -> str:
    fragment = bytearray()
    async for chunk in response.aiter_raw(chunk_size=512):
        fragment.extend(chunk[: ERROR_BYTES - len(fragment)])
        if len(fragment) == ERROR_BYTES:
            break
    return fragment.decode("utf-8", errors="replace")


def _parse_content_encoding(raw: str) -> str:
    encodings = [part.strip().lower() for part in raw.split(",") if part.strip()]
    encodings = [item for item in encodings if item != "identity"]
    if not encodings:
        return "identity"
    if len(encodings) == 1 and encodings[0] in {"gzip", "x-gzip"}:
        return "gzip"
    if len(encodings) == 1 and encodings[0] == "deflate":
        return "deflate"
    raise ValueError(f"HTTP read unsupported Content-Encoding: {raw}")


async def _read_body(response: httpx.Response, media_type: str,
                     byte_limit: Callable[[str, bytes], int]) -> bytes:
    encoding = _parse_content_encoding(response.headers.get("content-encoding", ""))
    body = bytearray()
    prefix = bytearray()
    if encoding == "identity":
        async for chunk in response.aiter_raw(chunk_size=65536):
            if len(prefix) < 5:
                prefix.extend(chunk[: 5 - len(prefix)])
            limit = byte_limit(media_type, bytes(prefix))
            if len(body) + len(chunk) > limit:
                raise ValueError(f"HTTP read resource exceeds {limit} decoded bytes")
            body.extend(chunk)
        return bytes(body)

    wbits = 16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS
    decompressor = zlib.decompressobj(wbits)
    raw_deflate_tried = False
    produced = False
    gzip_between_members = False
    raw_bytes = 0

    def append_decoded(piece: bytes) -> None:
        nonlocal produced
        if not piece:
            return
        produced = True
        if len(prefix) < 5:
            prefix.extend(piece[: 5 - len(prefix)])
        limit = byte_limit(media_type, bytes(prefix))
        if len(body) + len(piece) > limit:
            raise ValueError(f"HTTP read resource exceeds {limit} decoded bytes")
        body.extend(piece)

    async for chunk in response.aiter_raw(chunk_size=65536):
        if not chunk:
            continue
        raw_bytes += len(chunk)
        current_limit = byte_limit(media_type, bytes(prefix))
        if raw_bytes > current_limit * 2 + 65536:
            raise ValueError(f"HTTP read compressed stream exceeds safe size for {current_limit} decoded bytes")
        if gzip_between_members:
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            gzip_between_members = False
        buf = chunk
        while buf:
            limit = byte_limit(media_type, bytes(prefix))
            remaining = limit - len(body)
            max_length = min(5 - len(prefix), remaining + 1) if len(prefix) < 5 else remaining + 1
            if max_length <= 0:
                raise ValueError(f"HTTP read resource exceeds {limit} decoded bytes")
            try:
                piece = decompressor.decompress(buf, max_length)
            except zlib.error as error:
                if encoding == "deflate" and not produced and not raw_deflate_tried:
                    raw_deflate_tried = True
                    decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
                    continue
                raise ValueError(f"HTTP read invalid {encoding} body: {error}") from error
            append_decoded(piece)
            if decompressor.eof:
                unused = decompressor.unused_data
                try:
                    tail = decompressor.flush()
                except zlib.error as error:
                    raise ValueError(f"HTTP read invalid {encoding} body: {error}") from error
                append_decoded(tail)
                if encoding == "gzip":
                    if unused:
                        buf = unused
                        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    else:
                        gzip_between_members = True
                        buf = b""
                else:
                    buf = b""
            elif decompressor.unconsumed_tail:
                buf = decompressor.unconsumed_tail
            else:
                buf = b""
    if raw_bytes and not gzip_between_members:
        try:
            tail = decompressor.flush()
        except zlib.error as error:
            raise ValueError(f"HTTP read invalid {encoding} body: {error}") from error
        append_decoded(tail)
        if encoding == "gzip" and not decompressor.eof:
            raise ValueError("HTTP read truncated gzip body")
    return bytes(body)


async def fetch_public(url: str, timeout_seconds: float,
                       byte_limit: Callable[[str, bytes], int], *,
                       fake_ip_networks: tuple, public_dns_url: str | None = None,
                       headers: dict[str, str] | None = None) -> tuple[str, str, bytes]:
    """GET once per hop with checked first address, preserving original Host and TLS name."""
    current = url
    for redirect in range(MAX_REDIRECTS + 1):
        current, host, port, host_header, scheme = _target(current)
        # Every hop, redirects included, is checked against a task's egress mode before any lookup.
        admit(current)
        address = await _numeric_address(host, port, fake_ip_networks, public_dns_url, timeout_seconds)
        numeric_host = f"[{address}]" if ":" in address else address
        authority = numeric_host if port == (443 if scheme == "https" else 80) else f"{numeric_host}:{port}"
        parts = urlsplit(current)
        numeric_url = urlunsplit((scheme, authority, parts.path, parts.query, ""))
        request_headers = dict(headers) if headers else {}
        if not any(key.lower() == "user-agent" for key in request_headers):
            request_headers["User-Agent"] = USER_AGENT
        request_headers["Host"] = host_header
        request_headers["Accept-Encoding"] = "gzip, deflate"
        # A client belongs to exactly one hop, preventing cross-origin connection reuse.
        async with httpx.AsyncClient(
            timeout=timeout_seconds, trust_env=False, follow_redirects=False,
            transport=MeteredTransport(httpx.AsyncHTTPTransport(retries=0, trust_env=False), host=host, ip=address),
        ) as client:
            async with client.stream(
                "GET", numeric_url, headers=request_headers,
                extensions={"sni_hostname": host},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if location is None or not location.strip():
                        fragment = await _error_fragment(response)
                        raise ValueError(f"HTTP read status {response.status_code} redirect has no Location; "
                                         f"response fragment: {fragment}")
                    if redirect == MAX_REDIRECTS:
                        fragment = await _error_fragment(response)
                        raise ValueError(f"HTTP read status {response.status_code}: exceeded {MAX_REDIRECTS} redirects; "
                                         f"response fragment: {fragment}")
                    current = urljoin(current, location)
                    continue
                if not response.is_success:
                    fragment = await _error_fragment(response)
                    raise ValueError(f"HTTP read status {response.status_code}: {fragment}")
                media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                body = await _read_body(response, media_type, byte_limit)
                return current, response.headers.get("content-type", ""), body
    raise AssertionError("redirect loop exhausted without returning")
