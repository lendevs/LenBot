import asyncio
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from len_bot.next.work.egress_policy import (
    EgressBlocked,
    NetworkSettings,
    blocked_address_reason,
    blocked_resolved_reason,
    parse_public_dns,
)


def test_fake_ip_range_admits_only_addresses_resolved_inside_it():
    networks = NetworkSettings(fake_ip_networks=["198.18.0.0/15"]).networks()
    # The address a proxy in fake-ip mode returned for www.google.com on 2026-10-05.
    assert blocked_resolved_reason("198.18.0.26", networks) is None
    assert blocked_resolved_reason("100.64.0.1", networks) == "私有或保留地址"
    assert blocked_address_reason("::ffff:100.64.0.1") == "私有或保留地址"
    assert blocked_resolved_reason("192.168.1.10", networks) is not None
    assert blocked_resolved_reason("93.184.216.34", networks) is None
    assert blocked_resolved_reason("198.18.0.26", ()) == "私有或保留地址"


@pytest.mark.parametrize("value", [["10.0.0.0/8"], ["100.64.0.0/10"], ["100.100.1.0/24"],
                                   ["0.0.0.0/0"], ["8.8.8.0/24"], ["fd00::/8"], ["198.18.0.1/15"]])
def test_fake_ip_range_must_be_a_reserved_stand_in_range(value):
    with pytest.raises(ValidationError):
        NetworkSettings(fake_ip_networks=value)


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.5', '100.64.0.1', '169.254.169.254', '198.18.0.26'])
def test_real_dns_response_cannot_turn_a_fake_address_into_private_egress(address):
    with pytest.raises(EgressBlocked, match=address):
        parse_public_dns({'Status': 0, 'Answer': [{'type': 1, 'data': address}]}, 1)


def test_public_dns_keeps_only_numeric_answers_for_the_requested_type():
    body = {'Status': 0, 'Answer': [{'type': 5, 'data': 'public.example.'}, {'type': 1, 'data': '93.184.216.34'}]}
    assert parse_public_dns(body, 1) == ['93.184.216.34']


@pytest.mark.asyncio
async def test_worker_egress_dial_public_tries_next_validated_ip_on_failure(monkeypatch):
    from len_bot.next.work import worker_egress

    server = await asyncio.start_server(lambda _r, w: w.close(), '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    tried: list[str] = []

    async def fake_public_addresses(host, p, fake_ips, dns_url, timeout):
        assert host == 'dual.example' and p == port
        return ['93.184.216.1', '93.184.216.2']

    loop = asyncio.get_running_loop()
    real_sock_connect = loop.sock_connect

    async def fake_sock_connect(sock: socket.socket, address):
        tried.append(address[0])
        if address[0] == '93.184.216.1':
            raise ConnectionRefusedError('first IP refused')
        return await real_sock_connect(sock, ('127.0.0.1', port))

    monkeypatch.setattr(worker_egress, 'public_addresses', fake_public_addresses)
    monkeypatch.setattr(loop, 'sock_connect', fake_sock_connect)

    transport = worker_egress.EgressTransport(
        SimpleNamespace(returncode=None), stderr_file=None, port=18182,
        connect_timeout_seconds=5.0, fake_ip_networks=(), bytes_per_second=1024 * 1024,
        before_bytes=lambda *_: None, on_connection=lambda *_: None, on_bytes=lambda *_: None,
    )
    async with server:
        ip, _reader, writer = await transport._dial_public('dual.example', port)
        writer.close()
        await writer.wait_closed()
    assert tried == ['93.184.216.1', '93.184.216.2']
    assert ip == '93.184.216.2'


def test_execution_final_failure_extracts_stop_reason_and_error_message():
    from len_bot.next.work.execution import _final_failure

    summary = _final_failure({
        'role': 'assistant',
        'content': [],
        'stopReason': 'error',
        'errorMessage': '429 Too Many Requests: upstream quota exceeded',
        'usage': {'input': 1234, 'output': 0},
    })
    assert summary == 'Pi 未正常完成：stopReason=error；429 Too Many Requests: upstream quota exceeded'


@pytest.mark.asyncio
async def test_bwrap_version_probe_is_async_and_docker_tmpfs_includes_nodev(tmp_path, monkeypatch):
    from len_bot.next.work.bwrap import BwrapSandbox, BwrapSettings
    from len_bot.next.work.sandbox import DockerSandbox, DockerSettings

    fake_bwrap = tmp_path / 'bwrap'
    fake_bwrap.write_text('#!/bin/sh\necho "bubblewrap 0.9.0"\n', encoding='utf-8')
    fake_bwrap.chmod(0o755)
    bwrap = BwrapSandbox(BwrapSettings(
        bwrap_binary=fake_bwrap, task_runtime=tmp_path / 'rt',
        workspace_root=tmp_path / 'ws', runtime_root=tmp_path / 'run',
        memory_bytes=128 * 1024 * 1024, pids_limit=64, file_bytes=1024 * 1024, tmpfs_bytes=64 * 1024 * 1024,
    ))
    assert await bwrap._tmpfs_size() == ['--size', str(64 * 1024 * 1024)]

    captured: list[tuple[str, ...]] = []
    docker = DockerSandbox(DockerSettings(
        docker_binary=Path('/usr/bin/docker'), docker_host='unix:///var/run/docker.sock',
        image='lenbot-worker:test', workspace_root=tmp_path / 'dws', runtime_root=tmp_path / 'drun',
        uid=1000, gid=1000, tmpfs_size='128m',
    ))

    async def fake_docker(*args: str) -> str:
        captured.append(args)
        if args[0] == 'create':
            return 'cid-123'
        return ''

    monkeypatch.setattr(docker, '_docker', fake_docker)
    await docker.ensure('onebot:group:80001', '1')
    create_cmd = captured[0]
    tmpfs_index = create_cmd.index('--tmpfs')
    assert create_cmd[tmpfs_index + 1] == '/tmp:rw,noexec,nosuid,nodev,size=128m'
