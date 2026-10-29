"""Received OneBot images, vision HTTP replies and the operator's scene-local review API."""

import asyncio
from contextlib import AsyncExitStack
import json

import httpx
import pytest
from PIL import Image

from len_bot.next.config import load_host_config
from len_bot.next.learning.sticker_collection import StickerCollector
from len_bot.next.models.client import ChatModel
from len_bot.next.panel.app import create_app
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from len_bot.next.trials.replay_images import RecordedImages
from test_next_native_models import peer_server
from test_next_panel_acts_as_owner import SCENE, write_instance

OTHER = 'onebot:group:80002'


def reply(annotation):
    return (200, 'application/json', json.dumps({
        'choices': [{'message': {'role': 'assistant', 'content': json.dumps(annotation, ensure_ascii=False)},
                     'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 30, 'completion_tokens': 12},
    }).encode())


def receive(store, message_id, images, *, scene=SCENE, sender=70001):
    raw = {'post_type': 'message', 'message_type': 'group', 'group_id': int(scene.rsplit(':', 1)[1]),
           'self_id': 90001, 'user_id': sender, 'message_id': message_id, 'time': 1790000000,
           'sender': {'nickname': '群友', 'role': 'member'},
           'message': [{'type': 'image', 'data': data} for data in images]}
    store.enqueue(parse_message(raw, own_message_ids=set()), raw, 1790000001, collect_stickers=True)


async def settled(collector, scene=SCENE):
    collector.request(scene)
    async with asyncio.timeout(10):
        while True:
            state = collector.state(scene)
            assert state['worker_error'] is None, state
            if not state['counts']['queued'] and not state['counts']['running']:
                return state
            await asyncio.sleep(.01)


@pytest.mark.asyncio
@pytest.mark.parametrize('mind_images', [True, False])
async def test_sticker_intake_dedup_review_and_scene_isolation(tmp_path, mind_images):
    write_instance(tmp_path, ['onebot:70001'])
    path = tmp_path / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['models']['roles']['mind']['image_input'] = mind_images
    source['models']['roles']['vision'] = {
        'provider': 'local', 'model': 'synthetic-vision', 'context_window_tokens': 8192,
        'image_input': not mind_images}
    source['scenes'][SCENE]['learning'] = {'extract': False, 'collect_stickers': True}
    source['scenes'][OTHER] = source['scenes'][SCENE].copy()
    path.write_text(json.dumps(source))
    config = load_host_config(tmp_path)
    annotation = {'description': '开心地笑', 'text': '', 'emotions': ['开心'], 'tags': ['赞同'], 'is_sticker': True}
    photo = {**annotation, 'description': '软件界面截图', 'is_sticker': False}
    received = []
    server = await peer_server([reply(annotation), reply({**annotation, 'is_sticker': 'true'}),
                                reply(annotation), reply(photo), reply(annotation)], received)
    for color in ('red', 'green', 'blue'):
        Image.new('RGB', (8, 6), color).save(tmp_path / f'{color}.png')
    (tmp_path / 'manifest.json').write_text(json.dumps({
        'source': 'OneBot 图片段与隔离生成的原图', 'images': [
            {'message': message, 'image': index, 'file': f'{color}.png', 'fetched_at': 1790000001}
            for message, index, color in [('100', 2, 'red'), ('101', 1, 'red'), ('102', 1, 'green'),
                                           ('103', 1, 'blue'), ('104', 1, 'red'), ('105', 1, 'red'),
                                           ('106', 1, 'blue'), ('109', 1, 'green')]]}))
    recording = RecordedImages(tmp_path / 'manifest.json', max_bytes=config.images.max_bytes)
    async with server, AsyncExitStack() as stack:
        config.models.providers['local'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        mind = await stack.enter_async_context(ChatModel(config.model_settings('mind')))
        vision = await stack.enter_async_context(ChatModel(config.model_settings('vision')))
        with Store(config.database) as store:
            collector = StickerCollector(config, store, mind if mind_images else vision, recording=lambda _: recording)
            persona = load_persona(config.scenes[SCENE].persona)
            runtime = NetworkRuntime(config, [(config.scene_config(scene), persona) for scene in config.scenes],
                                     store, mind, vision=vision, sticker_collection=collector)
            app = create_app(config, runtime, root=tmp_path)
            runtime.accepting = True
            collector.start()
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                    await client.post('/api/auth/login', json={'username': 'host-operator', 'password': 'synthetic-password'})
                    base = f'/api/host/scenes/{SCENE}/learning/stickers'

                    async def candidates(review):
                        result = await client.get(base + '/candidates', params={'review': review, 'status': 'complete'})
                        assert result.status_code == 200, result.text
                        return result.json()['items']

                    receive(store, '100', [{'sub_type': 0}, {'sub_type': 1}])
                    await settled(collector)
                    [first] = await candidates('pending')
                    assert first['image_index'] == 2 and first['posts'] == first['posters'] == 1
                    receive(store, '101', [{'sub_type': 1}], sender=70002)
                    await settled(collector)
                    receive(store, '102', [{'sub_type': 1}])
                    assert (await settled(collector))['counts']['failed'] == 1
                    [failed] = (await client.get(base + '/candidates', params={'status': 'failed'})).json()['items']
                    assert 'is_sticker must be a boolean' in failed['error']
                    receive(store, '109', [{'sub_type': 1}])
                    await settled(collector)
                    repeated, newer = await candidates('pending')
                    assert repeated['id'] == first['id'] and newer['id'] > first['id']
                    assert (repeated['posts'], repeated['posters']) == (2, 2)
                    retry = await client.post(base + f"/candidates/{failed['id']}/retry")
                    assert retry.status_code == 200, retry.text
                    assert (await settled(collector))['counts']['failed'] == 0
                    assert (await client.get(base + f"/candidates/{failed['id']}")).status_code == 404
                    receive(store, '103', [{}])
                    await settled(collector)
                    [rejected] = await candidates('rejected')
                    assert rejected['is_sticker'] is False and rejected['status'] == 'complete'
                    changed = await client.put(base + f"/candidates/{first['id']}", json={
                        'description': '群里常用的笑脸', 'text': '', 'emotions': ['开心'], 'tags': [], 'review': 'adopted'})
                    assert changed.status_code == 200, changed.text
                    receive(store, '104', [{'sub_type': 1}])
                    await settled(collector)
                    [adopted] = await candidates('adopted')
                    assert (adopted['id'], adopted['posts'], adopted['posters']) == (first['id'], 3, 2)
                    assert store.platform_image(SCENE, '101', 1)[0] == 'image/png'
                    assert store.db.execute('SELECT description FROM message_media WHERE media_id=?',
                                            (first['media_id'],)).fetchall()[0][0] == '群里常用的笑脸'
                    receive(store, '105', [{'sub_type': 1}], scene=OTHER)
                    await settled(collector, OTHER)
                    other_base = f'/api/host/scenes/{OTHER}/learning/stickers'
                    [other] = (await client.get(other_base + '/candidates')).json()['items']
                    assert other['review'] == 'pending' and (other['posts'], other['posters']) == (1, 1)
                    assert other['media_id'] != first['media_id']
                    denied = await client.get(other_base + f"/candidates/{first['id']}/image")
                    assert denied.status_code == 404
                    receive(store, '106', [{}])
                    await settled(collector)
                    [rejected] = await candidates('rejected')
                    assert rejected['posts'] == 2
                    receive(store, '108', [{'sub_type': '0'}])
                    receive(store, '107', [{'sub_type': 1}], sender=90001)
                    await settled(collector)
                    assert collector.records.counts(SCENE)['complete'] == 3
                    assert len(received) == 5
                    assert {request[2]['model'] for request in received} == {
                        'synthetic-mind' if mind_images else 'synthetic-vision'}
                    assert store.db.execute('SELECT count(*) FROM usage WHERE purpose=?', ('sticker',)).fetchone()[0] == 5
            finally:
                await collector.close()
                await runtime.reference.close()
