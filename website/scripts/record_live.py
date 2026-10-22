"""Record the live tab while the demo bot answers a mention, and save it as a GIF (run demo_instance.py first).

Needs ffmpeg on PATH. The turn card is opened as soon as it appears, so its steps are shown as they arrive.
"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

VIEWPORT = {'width': 1280, 'height': 960}
MESSAGE = {'group': 80001, 'user': 70002, 'text': '周六带什么零食好', 'at': True}
# The bot's last line for this message in demo_instance.SCRIPTS; its arrival ends the turn.
LAST_LINE = '抹茶饼干我也带一盒'
OPEN_THOUGHTS = '''for (const item of document.querySelectorAll('details'))
  if (item.querySelector('summary')?.textContent.trim() === '想法') item.open = true'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panel', default='http://127.0.0.1:18088')
    parser.add_argument('--control', default='http://127.0.0.1:18099')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'public/screenshots/live.gif')
    parser.add_argument('--width', type=int, default=960, help='GIF width in pixels')
    args = parser.parse_args()
    if shutil.which('ffmpeg') is None:
        parser.error('ffmpeg is not on PATH')
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, locale='zh-CN', record_video_dir=folder,
                                      record_video_size=VIEWPORT)
        started = time.monotonic()
        page = context.new_page()
        page.goto(args.panel + '/#/login')
        page.get_by_label('用户名').fill('demo')
        page.get_by_label('密码').fill('demo-password')
        page.get_by_role('button', name='登录').click()
        page.wait_for_url('**/#/overview')
        page.goto(args.panel + f'/#/groups/onebot:group:{MESSAGE["group"]}/live')
        page.wait_for_load_state('networkidle')
        page.mouse.move(0, 0)
        page.wait_for_timeout(1500)
        cards = page.get_by_text('被 @ 或回复')
        before, lines = cards.count(), page.get_by_text(LAST_LINE).count()
        begin = time.monotonic() - started - 0.8
        request = urllib.request.Request(args.control + '/inject', data=json.dumps(MESSAGE).encode(),
                                         headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(request, timeout=10).close()
        page.wait_for_function(f'document.body.innerText.split("被 @ 或回复").length > {before + 1}', timeout=30000)
        page.wait_for_timeout(300)
        cards.last.click()
        deadline = time.monotonic() + 60
        # Thoughts are folded on the panel; open each one as its step arrives.
        while page.get_by_text(LAST_LINE).count() <= lines + 1:
            if time.monotonic() > deadline:
                raise TimeoutError('The demo bot did not finish its turn within 60 seconds')
            page.evaluate(OPEN_THOUGHTS)
            page.wait_for_timeout(150)
        page.evaluate(OPEN_THOUGHTS)
        page.wait_for_timeout(2500)
        end = time.monotonic() - started
        video = page.video.path()
        context.close()
        browser.close()
        palette = (f'fps=12,scale={args.width}:-1:flags=lanczos,split[a][b];'
                   '[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', f'{begin:.2f}', '-to', f'{end:.2f}', '-i', str(video),
                        '-vf', palette, '-loop', '0', str(args.output)], check=True)
    print(args.output, f'{args.output.stat().st_size // 1024} KB')


if __name__ == '__main__':
    main()
