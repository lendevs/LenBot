"""同一 HTTP 响应经过声明模型前后，字段、嵌套结构和值的类型必须一致。"""

import asyncio
from contextlib import asynccontextmanager
import json

from fastapi import FastAPI
from fastapi.routing import APIRoute
import httpx
from pydantic import TypeAdapter

from len_bot.next.config import load_host_config
from len_bot.next.memory.service import open_memory
from len_bot.next.models.client import ChatModel
from len_bot.next.panel.app import create_app
from len_bot.next.panel.setup import create_setup_app
from len_bot.next.persona.profile import load_persona
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from len_bot.next.work.store import TaskStore
from test_next_panel_acts_as_owner import SCENE, write_instance


@asynccontextmanager
async def panel(root):
    write_instance(root, ['onebot:70001'])
    file = root / 'lenbot.config.json'
    source = json.loads(file.read_text())
    source['memory'] = {'backend': 'local', 'local': {'directory': 'memory'}}
    source['panel']['update_check'] = False
    source['plugins'] = {'paths': ['plugins']}
    file.write_text(json.dumps(source))
    # 已发现但未启用的插件：清单里的地址字段要按字符串输出。
    plugin = root / 'plugins' / 'linked'
    plugin.mkdir(parents=True)
    (plugin / '__init__.py').write_text('')
    (plugin / 'plugin.toml').write_text('\n'.join([
        'name = "linked"', 'version = "1.0.0"', 'interface = 1', 'requires_lenbot = ">=0.2,<1"',
        'requires_python = ">=3.13"', 'platforms = ["linux", "darwin", "win32"]', 'reload = "plugin"',
        'authors = ["LEN5010"]', 'license = "MIT"', 'description = "带仓库地址的样本。"',
        'repository = "https://example.com/plugins/linked"', 'homepage = "https://example.com/linked"']))
    config = load_host_config(root)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store) as memory:
            runtime = NetworkRuntime(config, [(config.scene_config(SCENE), load_persona(config.scenes[SCENE].persona))],
                                     store, mind, memory=memory)
            app = create_app(config, runtime, root=root)
            # 对照端仍调用相同业务入口及鉴权依赖，只取消响应过滤。
            raw = FastAPI()
            for route in app.routes:
                if isinstance(route, APIRoute):
                    raw.router.routes.append(APIRoute(route.path, route.endpoint, methods=route.methods,
                        response_model=None, dependencies=route.dependencies, response_class=route.response_class,
                        status_code=route.status_code))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                response = await client.post('/api/auth/login', json={
                    'username': 'host-operator', 'password': 'synthetic-password'})
                assert response.status_code == 200
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=raw), base_url='http://testserver',
                                             cookies=client.cookies) as unfiltered:
                    yield app, client, unfiltered
            await app.state.trials.close()


def assert_unchanged(route, value):
    assert route.response_model is not None, route.path
    adapter = TypeAdapter(route.response_model)
    result = json.loads(adapter.dump_json(adapter.validate_python(value),
        exclude_unset=route.response_model_exclude_unset))
    # 比较 JSON 文本还区分 1、1.0 和 true，普通 dict 相等无法区分它们。
    assert json.dumps(result, sort_keys=True, ensure_ascii=False) == json.dumps(value, sort_keys=True, ensure_ascii=False), route.path


def test_host_read_responses_keep_the_unfiltered_json(tmp_path):
    async def run():
        async with panel(tmp_path) as (app, client, raw):
            key = (await client.get('/api/host/personas')).json()['roles'][0]['key']
            checked = set()
            for route in app.routes:
                if not isinstance(route, APIRoute) or 'GET' not in route.methods or not route.path.startswith('/api/'):
                    continue
                if any(part in route.path for part in ('plugin-catalog', 'plugin-market', 'updates/releases')):
                    continue
                path = route.path.replace('{scene}', SCENE).replace('{key}', key)
                if '{' in path:
                    continue
                params = {'scene': SCENE, 'directory': str(tmp_path / 'persona')}
                before = await raw.get(path, params=params)
                if before.status_code != 200 or 'application/json' not in before.headers.get('content-type', ''):
                    continue
                assert_unchanged(route, before.json())
                after = await client.get(path, params=params)
                assert after.status_code == before.status_code, (path, after.text)
                checked.add(route.path)
                if route.path in {'/api/host/state', '/api/host/settings', '/api/host/personas',
                                  '/api/host/plugins', '/api/host/mcp', '/api/host/memory/browse'}:
                    assert before.json() == after.json(), path
            assert len(checked) >= 50
            linked = (await client.get('/api/host/plugins')).json()['available']['linked'][0]
            assert (linked['repository'], linked['homepage']) == ('https://example.com/plugins/linked',
                                                                  'https://example.com/linked')
    asyncio.run(run())


def test_write_responses_keep_the_unfiltered_json(tmp_path):
    async def run():
        async with panel(tmp_path) as (app, client, raw):
            key = (await client.get('/api/host/personas')).json()['roles'][0]['key']
            profile = (await client.get(f'/api/host/personas/{key}/profile')).json()
            operations = [
                ('POST', '/api/host/personas', {'folder': 'second', 'name': '第二角色'}),
                ('PUT', f'/api/host/personas/{key}/profile', {'directory': profile['directory'], 'profile': profile['profile']}),
                ('POST', f'/api/host/personas/{key}/profile/draft', {'directory': profile['directory'], 'profile': profile['profile']}),
                ('PUT', '/api/host/memory/file', {'scene': SCENE, 'scope': 'scene', 'path': 'notes.md', 'content': '# 事项\n周末看展。', 'reason': '记录'}),
                ('POST', '/api/host/memory/search', {'scene': SCENE, 'query': '看展', 'limit': 5}),
                ('POST', '/api/host/memory/delete', {'scene': SCENE, 'path': 'notes.md', 'reason': '删除', 'forget': False}),
                ('POST', f'/api/host/scenes/{SCENE}/history/new-context?confirmed=true', None),
                ('PUT', '/api/host/control/chat', {'enabled': False}),
                ('PUT', '/api/host/control/chat', {'enabled': True}),
                ('PUT', f'/api/host/scenes/{SCENE}/control/open', {'enabled': False}),
                ('PUT', f'/api/host/scenes/{SCENE}/control/open', {'enabled': True}),
                ('POST', f'/api/host/schedules?scene={SCENE}', {'when': '2099-01-01T08:00:00+00:00', 'note': '看展', 'for': 'self'}),
            ]
            for method, path, body in operations:
                response = await raw.request(method, path, json=body)
                assert response.status_code == 200, (path, response.text)
                scope = {'type': 'http', 'path': path.split('?')[0], 'method': method, 'root_path': ''}
                route = next(route for route in app.routes if isinstance(route, APIRoute)
                             and route.matches(scope)[0].name == 'FULL')
                assert_unchanged(route, response.json())
    asyncio.run(run())


def test_setup_responses_keep_the_unfiltered_json(tmp_path):
    app = create_setup_app(tmp_path, 'local-token', asyncio.Event())
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
            for path in ('/api/setup/protocols', '/api/setup/plugins'):
                response = await client.get(path, headers={'X-Setup-Token': 'local-token'})
                assert response.status_code == 200
                route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == path)
                assert_unchanged(route, response.json())
    asyncio.run(run())


def test_overview_waiting_tasks_and_task_detail_budget_watchdog(tmp_path):
    from types import SimpleNamespace

    async def run():
        async with panel(tmp_path) as (app, client, raw):
            with Store(tmp_path / 'host.sqlite3') as store:
                tasks = TaskStore(store)
                waiting = tasks.create(SCENE, 'onebot:70001', '整理季度数据', '报告.md', '', '请生成报告')
                tasks.start(SCENE, waiting.id)
                call_id = tasks.start_call(SCENE, waiting.id, {'provider': 'synthetic', 'model': 'm1'})
                tasks.finish_call(call_id, {'tokens': {'input': 120, 'output': 45, 'cached': 30}})
                tasks.add_watchdog_event(
                    SCENE,
                    waiting.id,
                    SimpleNamespace(action='steer', reason='repeat_tool', detail='连续重复调用工具，已提示调整策略'),
                )
                tasks.set_question(
                    SCENE,
                    waiting.id,
                    {'id': 'q-1', 'method': 'input', 'title': '需要确认导出格式'},
                )
                tasks.create(SCENE, 'onebot:70001', '排队中的任务', '结果.txt', '', '待执行')

            overview_route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == '/api/host/overview')
            raw_overview = await raw.get('/api/host/overview')
            assert raw_overview.status_code == 200, raw_overview.text
            assert_unchanged(overview_route, raw_overview.json())
            overview = (await client.get('/api/host/overview')).json()
            assert overview['active_tasks'] == 2
            assert len(overview['waiting_tasks']) == 1
            assert overview['waiting_tasks'][0]['id'] == waiting.id
            assert overview['waiting_tasks'][0]['scene'] == SCENE
            assert overview['waiting_tasks'][0]['goal'] == '整理季度数据'
            assert overview['waiting_tasks'][0]['requester'] == 'onebot:70001'
            assert overview['waiting_tasks'][0]['question_title'] == '需要确认导出格式'

            list_route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == '/api/host/tasks')
            raw_waiting = await raw.get('/api/host/tasks', params={'scene': SCENE, 'status': 'waiting_input'})
            assert raw_waiting.status_code == 200, raw_waiting.text
            assert_unchanged(list_route, raw_waiting.json())
            assert [item['id'] for item in raw_waiting.json()['items']] == [waiting.id]

            detail_route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == '/api/host/tasks/{id}')
            raw_detail = await raw.get(f'/api/host/tasks/{waiting.id}', params={'scene': SCENE})
            assert raw_detail.status_code == 200, raw_detail.text
            assert_unchanged(detail_route, raw_detail.json())
            detail = (await client.get(f'/api/host/tasks/{waiting.id}', params={'scene': SCENE})).json()
            assert detail['budget'] == {
                'calls': 1,
                'max_calls': None,
                'tokens': {'input': 120, 'output': 45, 'cached': 30, 'known_calls': 1, 'unknown_calls': 0},
                'max_tokens': None,
            }
            assert len(detail['watchdog']) == 1
            assert detail['watchdog'][0]['action'] == 'steer'
            assert detail['watchdog'][0]['reason'] == 'repeat_tool'
            assert detail['watchdog'][0]['detail'] == '连续重复调用工具，已提示调整策略'
            assert isinstance(detail['watchdog'][0]['id'], int)
            assert isinstance(detail['watchdog'][0]['created'], float)

            # After finish + continue requeue, calls resets to current execution while tokens stay cumulative.
            with Store(tmp_path / 'host.sqlite3') as store:
                tasks = TaskStore(store)
                tasks.set_question(SCENE, waiting.id, None)
                tasks.finish(SCENE, waiting.id, 'done', '首轮完成', None)
                tasks.requeue(SCENE, waiting.id, '补充第二章图表', requester='onebot:70001')
                tasks.start(SCENE, waiting.id)
                call_id_2 = tasks.start_call(SCENE, waiting.id, {'provider': 'synthetic', 'model': 'm1'})
                tasks.finish_call(call_id_2, {'tokens': {'input': 80, 'output': 20, 'cached': 10}})

            continued_detail = (await client.get(f'/api/host/tasks/{waiting.id}', params={'scene': SCENE})).json()
            assert_unchanged(detail_route, continued_detail)
            assert continued_detail['budget'] == {
                'calls': 1,
                'max_calls': None,
                'tokens': {'input': 200, 'output': 65, 'cached': 40, 'known_calls': 2, 'unknown_calls': 0},
                'max_tokens': None,
            }

    asyncio.run(run())
