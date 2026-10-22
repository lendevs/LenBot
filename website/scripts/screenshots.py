"""Log in to the demo panel and save the site screenshots (run demo_instance.py first)."""

import argparse
import json
from pathlib import Path
import urllib.request

from playwright.sync_api import sync_playwright

PAGES = {'home': '/#/overview', 'persona': '/#/personas?persona=companion&tab=profile',
         'plugins': '/#/plugins?view=discover', 'scenes': '/#/groups/onebot:group:80001/live',
         'connection': '/#/system?tab=connection'}
# Sent before the group page is taken, so it shows a finished turn; its last line ends the turn.
MESSAGE = {'group': 80001, 'user': 70002, 'text': '周六带什么零食好', 'at': True}
LAST_LINE = '抹茶饼干我也带一盒'


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
        for name, path in PAGES.items():
            page.goto(args.panel + path)
            page.wait_for_load_state('networkidle')
            if name == 'scenes' and page.get_by_text(LAST_LINE).count() == 0:
                request = urllib.request.Request(args.control + '/inject', data=json.dumps(MESSAGE).encode(),
                                                 headers={'Content-Type': 'application/json'}, method='POST')
                urllib.request.urlopen(request, timeout=10).close()
                page.get_by_text(LAST_LINE).wait_for(timeout=60000)
            page.mouse.move(0, 0)
            # Entrance animations and the live-status dot settle within a second.
            page.wait_for_timeout(1500)
            page.screenshot(path=args.output / f'{name}.png')
            print(args.output / f'{name}.png')
        browser.close()


if __name__ == '__main__':
    main()
