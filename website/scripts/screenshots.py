"""Log in to the demo panel and save the site screenshots (run demo_instance.py first)."""

import argparse
import json
from pathlib import Path
import time
import urllib.request

from playwright.sync_api import sync_playwright

PAGES = {'home': '/#/overview', 'persona': '/#/personas?persona=companion&tab=effect',
         'plugins': '/#/plugins?view=discover', 'scenes': '/#/groups/onebot:group:80001/live',
         'connection': '/#/system?tab=connection', 'usage': '/#/models?tab=usage',
         'reference': '/#/groups/onebot:group:80001/reference', 'memory': '/#/groups/onebot:group:80001/memory'}
SCENE = 'onebot:group:80001'
# Sent before the pages are taken, so the groups show finished turns; each last line ends its turn.
MESSAGES = [({'group': 80001, 'user': 70002, 'text': '周六带什么零食好', 'at': True}, '抹茶饼干我也带一盒'),
            ({'group': 80002, 'user': 70003, 'text': '三脚架买哪种好', 'at': True}, '手就不会抖啦')]
TRIAL = '周六带什么零食好'
MEMORY = ('events/周六桌游.md', '# 周六桌游\n\n## 时间地点\n\n每周六 18:00 在东门桌游吧 3 号包间开局，晚到的人负责点外卖。\n\n'
          '## 口味\n\n- 老周一点辣都不吃\n- 橘子点名要抹茶饼干\n\n## 器材\n\n- 老周带卡坦岛和航海家扩展\n')
# Group files of the demo instance imported into the reference tab.
GROUP_FILES = [('/f-rules', '桌游规则速查.md'), ('/f-venue', '场地预约.txt'), ('/f-expansion', '卡坦岛航海家扩展.md')]


def inject(control: str, message: dict) -> None:
    request = urllib.request.Request(control + '/inject', data=json.dumps(message).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
    urllib.request.urlopen(request, timeout=10).close()


def said(page, panel: str, group: int, text: str) -> bool:
    timeline = page.request.get(f'{panel}/api/host/scenes/onebot:group:{group}/timeline?limit=50').json()
    return text in json.dumps(timeline, ensure_ascii=False)


def answer(page, panel: str, control: str, message: dict, last: str) -> None:
    """Send the message unless the bot already answered it, and wait for the answer's last line."""
    if said(page, panel, message['group'], last):
        return
    inject(control, message)
    deadline = time.monotonic() + 60
    while not said(page, panel, message['group'], last):
        if time.monotonic() > deadline:
            raise TimeoutError(f"no reply in {message['group']}")
        page.wait_for_timeout(500)


def seed(page, panel: str) -> None:
    """A memory file and three reference files, written the way the panel writes them."""
    headers = {'Origin': panel}
    path, content = MEMORY
    page.request.put(panel + '/api/host/memory/file', headers=headers, fail_on_status_code=True, data={
        'scene': SCENE, 'path': path, 'scope': 'scene', 'content': content, 'reason': '群友约定的固定安排'})
    for file_id, name in GROUP_FILES:
        page.request.post(f'{panel}/api/host/scenes/{SCENE}/reference/group-files', headers=headers,
                          fail_on_status_code=True, data={'file_id': file_id, 'busid': 102, 'name': name})


def prepare(page, name: str) -> None:
    """Bring each page to the state its screenshot shows."""
    if name == 'persona':
        # A new trial each time, so the chat shows one question and its answer.
        start, stop = page.get_by_role('button', name='开始试聊'), page.get_by_role('button', name='结束试聊')
        start.or_(stop).wait_for()
        if stop.is_visible():
            stop.click()
            page.get_by_role('alertdialog').get_by_role('button', name='结束试聊').click()
        start.click()
        page.get_by_role('button', name='@ 群友').click()
        page.get_by_role('menuitem', name='小然').click()
        page.locator('textarea').first.fill(TRIAL)
        page.keyboard.press('Enter')
        page.get_by_text(MESSAGES[0][1]).wait_for(timeout=60000)
        # Sending focuses the input and scrolls it into view; the shot starts at the persona header.
        page.locator('textarea').first.blur()
        page.evaluate('() => document.querySelectorAll("*").forEach(element => { element.scrollTop = 0 })')
    if name == 'reference':
        page.get_by_text('已索引').first.wait_for(timeout=30000)
    if name == 'memory':
        page.get_by_text('events', exact=True).click()
        page.get_by_text(Path(MEMORY[0]).name, exact=True).click()
        page.get_by_text('晚到的人负责点外卖').wait_for(timeout=10000)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panel', default='http://127.0.0.1:18088')
    parser.add_argument('--control', default='http://127.0.0.1:18099')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'public/screenshots')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900}, device_scale_factor=2, locale='zh-CN')
        page.goto(args.panel + '/#/login')
        page.get_by_label('用户名').fill('demo')
        page.get_by_label('密码').fill('demo-password')
        page.get_by_role('button', name='登录').click()
        page.wait_for_url('**/#/overview')
        seed(page, args.panel)
        for message, last in MESSAGES:
            answer(page, args.panel, args.control, message, last)
        for name, path in PAGES.items():
            page.goto(args.panel + path)
            page.wait_for_load_state('networkidle')
            prepare(page, name)
            page.mouse.move(0, 0)
            # Entrance animations and the live-status dot settle within a second.
            page.wait_for_timeout(1500)
            page.screenshot(path=args.output / f'{name}.png')
            print(args.output / f'{name}.png')
        browser.close()


if __name__ == '__main__':
    main()
