"""Draw the animated SVG cards shown in the README.

Every card is written in Chinese and English, each in a light and a dark version. The cards use CSS animations
and system fonts only, so they also play when GitHub shows them as images. Icon outlines come from Lucide (ISC).

    python3 website/scripts/readme_cards.py
"""

import argparse
from html import escape
from pathlib import Path
import re

OUT = Path(__file__).resolve().parents[1] / 'public/readme'
FONT = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', "
        "'Noto Sans CJK SC', 'Noto Sans SC', Helvetica, Arial, sans-serif")
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
EASE = 'cubic-bezier(.22,1,.36,1)'

LIGHT = {
    'card': '#ffffff', 'page': '#fbf7f8', 'fill': '#f4f3f6', 'soft': '#fbeff3', 'soft2': '#f6dde6',
    'ink': '#1d1b20', 'ink2': '#3f3c44', 'muted': '#6b6870', 'subtle': '#9b98a1', 'line': '#ebe8ec',
    'strong': '#d9d8dd', 'primary': '#b4476a', 'brand': '#e2809f', 'accent': '#e8935a', 'success': '#22875a',
    'code': '#f7f5f8', 'string': '#2c7a52', 'glow': '#f4b6c8', 'glow2': '#f8d3b0', 'shadow': '#1d1b20',
    'shadow_opacity': '0.10', 'term': '#24212a', 'term_ink': '#ecebef', 'on_primary': '#ffffff',
    'avatars': ['#e3f1d8:#4b7a2a', '#ede1f6:#77479a', '#fde6d2:#a1561a', '#dfeaf8:#2f6db0', '#dcf1ec:#1f7a66'],
}
DARK = {
    'card': '#1c1b20', 'page': '#141317', 'fill': '#26252b', 'soft': '#3a2530', 'soft2': '#4a2d3b',
    'ink': '#ecebef', 'ink2': '#cfcdd4', 'muted': '#a19ea8', 'subtle': '#77747d', 'line': '#2e2d33',
    'strong': '#3d3c43', 'primary': '#ec8fae', 'brand': '#e891ad', 'accent': '#f0ad7c', 'success': '#5cc792',
    'code': '#18171b', 'string': '#7fd3a5', 'glow': '#6d2f48', 'glow2': '#6b4224', 'shadow': '#000000',
    'shadow_opacity': '0.45', 'term': '#0f0e12', 'term_ink': '#ecebef', 'on_primary': '#1d1b20',
    'avatars': ['#26361d:#a8d68a', '#33254a:#cfa8ec', '#3d2a1a:#f3b27d', '#1d2c40:#8db9ec', '#183631:#7fd3bd'],
}

ICONS = {
    'search': '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    'zap': '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 '
           '.78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    'moon': '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    'sparkles': '<path d="M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.14-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 '
                '8.5l1.58-6.14a.5.5 0 0 1 .96 0L14.06 8.5A2 2 0 0 0 15.5 9.94l6.14 1.58a.5.5 0 0 1 0 .96L15.5 '
                '14.06a2 2 0 0 0-1.44 1.44l-1.58 6.14a.5.5 0 0 1-.96 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/>',
    'eye': '<path d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0"/>'
           '<circle cx="12" cy="12" r="3"/>',
    'alarm': '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2"/><path d="M5 3 2 6"/><path d="m22 6-3-3"/>',
    'file': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 '
            '2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    'folder': '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 '
              '2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    'user': '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
    'code': '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>',
    'check': '<path d="M20 6 9 17l-5-5"/>',
    'message': '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    'clock': '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    'container': '<path d="M22 7.7c0-.6-.4-1.2-.8-1.5l-6.3-3.9a1.72 1.72 0 0 0-1.7 0l-10.3 6c-.5.2-.9.8-.9 1.4v6.6c0 '
                 '.5.4 1.2.8 1.5l6.3 3.9a1.72 1.72 0 0 0 1.7 0l10.3-6c.5-.3.9-1 .9-1.5Z"/><path d="M10 21.9V14L2.1 9.1"/>'
                 '<path d="m10 14 11.9-6.9"/><path d="M14 19.8v-8.1"/><path d="M18 17.5V9.4"/>',
    'package': '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 '
               '8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="m3.3 7 7.7 4.73a2 2 0 0 0 2 0L20.7 7"/>'
               '<path d="m7.5 4.27 9 5.15"/>',
    'terminal': '<path d="M12 19h8"/><path d="m4 17 6-6-6-6"/>',
    'plus': '<path d="M5 12h14"/><path d="M12 5v14"/>',
    'brain': '<path d="M12 18V5"/><path d="M15 13a4.17 4.17 0 0 1-3-4 4.17 4.17 0 0 1-3 4"/><path d="M17.6 6.5A3 3 0 '
             '1 0 12 5a3 3 0 1 0-5.6 1.5"/><path d="M18 18a4 4 0 0 0 2-7.46"/><path d="M6 18a4 4 0 0 1-2-7.46"/>'
             '<path d="M18 18a4 4 0 0 1-12 0"/>',
}

MARK = ('<path class="{k}-antenna" d="M47 27C44 18 47 11 55 9C61 8 64 13 60 16C57 17.5 55.5 14.5 58.5 12.5" '
        'fill="none" stroke="#E2809F" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M48 26C67 26 79 37 79 51S67 76 48 76C44.5 76 41 75.5 38 74.6L22 81L26 69C20 64.5 17 58 17 51C17 '
        '37 29 26 48 26Z" fill="#E2809F"/>'
        '<rect class="{k}-eye" x="35" y="43" width="7" height="14" rx="3.5" fill="#2A2530"/>'
        '<rect class="{k}-eye" x="54" y="43" width="7" height="14" rx="3.5" fill="#2A2530"/>'
        '<path d="M42.5 62Q45.25 65 48 62Q50.75 65 53.5 62" fill="none" stroke="#2A2530" stroke-width="3" '
        'stroke-linecap="round" stroke-linejoin="round"/>')


def wide(char: str) -> bool:
    return ord(char) >= 0x2E80 or char in '…—“”'


def char_width(char: str) -> float:
    if wide(char):
        return 1.0
    if char == ' ':
        return 0.28
    if char in "il.,:;'|!·":
        return 0.28
    if char in 'fjtr()[]{}-/"':
        return 0.37
    if char in 'mwMW%@':
        return 0.9
    if char.isupper():
        return 0.68
    if char.isdigit():
        return 0.58
    return 0.54


def text_width(text: str, size: float, mono: bool = False) -> float:
    if mono:
        return sum(1.0 if wide(char) else 0.61 for char in text) * size
    return sum(char_width(char) for char in text) * size * 1.04


TOKEN = re.compile(r"[A-Za-z0-9@#'’.,:;!?%/_+\-]+|\s+|.")


def wrap(text: str, size: float, limit: float) -> list[str]:
    lines, current = [], ''
    for token in TOKEN.findall(text):
        if current and text_width((current + token).rstrip(), size) > limit:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current += token
    if current.strip():
        lines.append(current.rstrip())
    return lines


class Card:
    """One SVG with its own loop length; every class and keyframe name starts with the card key."""

    def __init__(self, key: str, width: int, height: int, loop: float, palette: dict):
        self.key, self.width, self.height, self.loop, self.p = key, width, height, loop, palette
        self.parts: list[str] = []
        self.css: list[str] = []
        self.defs: list[str] = []
        self.count = 0

    def add(self, *parts: str) -> None:
        self.parts.extend(parts)

    def pct(self, seconds: float) -> str:
        return f'{max(0.0, min(100.0, seconds / self.loop * 100)):.2f}'

    def show(self, start: float, end: float | None = None, *, rise: float = 6, final: bool = True,
             zoom: bool = False) -> str:
        """A class that fades its element in at start and out at end (seconds into the loop)."""
        self.count += 1
        name = f'{self.key}-s{self.count}'
        end = self.loop - 0.8 if end is None else end
        hidden = 'opacity:0;transform:' + ('scale(.9)' if zoom else f'translateY({rise}px)')
        self.css.append(
            f'@keyframes {name}{{0%,{self.pct(start)}%{{{hidden}}}{self.pct(start + 0.45)}%,{self.pct(end)}%'
            f'{{opacity:1;transform:none}}{self.pct(end + 0.4)}%,100%{{opacity:0;transform:none}}}}'
            f'.{name}{{animation:{name} {self.loop}s {EASE} infinite;'
            + ('transform-box:fill-box;transform-origin:center;' if zoom else '')
            + ('' if final else 'opacity:0;') + '}')
        return name

    def grow(self, start: float) -> str:
        """A class that widens its element from the left edge at start."""
        self.count += 1
        name = f'{self.key}-s{self.count}'
        self.css.append(
            f'@keyframes {name}{{0%,{self.pct(start)}%{{opacity:1;transform:scaleX(0)}}{self.pct(start + 0.9)}%,'
            f'{self.pct(self.loop - 0.8)}%{{opacity:1;transform:scaleX(1)}}{self.pct(self.loop - 0.4)}%,100%{{transform:scaleX(1);'
            f'opacity:0}}}}.{name}{{transform-box:fill-box;transform-origin:left center;'
            f'animation:{name} {self.loop}s {EASE} infinite}}')
        return name

    def group(self, cls: str, *parts: str) -> str:
        return f'<g class="{cls}">{"".join(parts)}</g>'

    def svg(self, label: str) -> str:
        k, p = self.key, self.p
        base = (
            f'.{k}-spin{{transform-box:fill-box;transform-origin:center;animation:{k}-spin 0.9s linear infinite}}'
            f'@keyframes {k}-spin{{to{{transform:rotate(360deg)}}}}'
            f'.{k}-dot{{animation:{k}-dot 1s ease-in-out infinite}}'
            f'@keyframes {k}-dot{{0%,60%,100%{{opacity:.3;transform:none}}30%{{opacity:1;transform:translateY(-3px)}}}}'
            f'.{k}-float{{animation:{k}-float 6s ease-in-out infinite}}'
            f'@keyframes {k}-float{{0%,100%{{transform:none}}50%{{transform:translateY(-7px)}}}}'
            f'.{k}-bob{{animation:{k}-bob 3.6s ease-in-out infinite}}'
            f'@keyframes {k}-bob{{0%,100%{{transform:none}}50%{{transform:translateY(-2px)}}}}'
            f'.{k}-antenna{{transform-origin:47px 27px;animation:{k}-sway 3.6s ease-in-out infinite}}'
            f'@keyframes {k}-sway{{0%,100%{{transform:rotate(-5deg)}}50%{{transform:rotate(7deg)}}}}'
            f'.{k}-eye{{transform-box:fill-box;transform-origin:center;animation:{k}-blink 5s infinite}}'
            f'@keyframes {k}-blink{{0%,90%,96%,100%{{transform:none}}93%{{transform:scaleY(.12)}}}}'
            f'text{{font-family:{FONT}}}.{k}-mono{{font-family:{MONO}}}'
            '@media (prefers-reduced-motion:reduce){*{animation:none!important}}')
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}" role="img" aria-label="{escape(label)}">'
            f'<title>{escape(label)}</title>'
            f'<defs>{"".join(self.defs)}'
            f'<filter id="{k}-shadow" x="-10%" y="-10%" width="120%" height="130%">'
            f'<feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="{p["shadow"]}" '
            f'flood-opacity="{p["shadow_opacity"]}"/></filter></defs>'
            f'<style>{base}{"".join(self.css)}</style>{"".join(self.parts)}</svg>\n')


def text(x, y, value, size, color, *, weight=400, anchor='start', mono_key=None, spans=None) -> str:
    """A line of text; spans is a list of (text, color, weight or 0) drawn in sequence."""
    extra = f' text-anchor="{anchor}"' if anchor != 'start' else ''
    extra += f' class="{mono_key}-mono"' if mono_key else ''
    if spans:
        body = ''.join(f'<tspan fill="{fill}"' + (f' font-weight="{bold}"' if bold else '') + f'>{escape(part)}</tspan>'
                       for part, fill, bold in spans)
    else:
        body = escape(value)
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" font-weight="{weight}"{extra}>'
            f'{body}</text>')


def rect(x, y, w, h, r, fill, stroke=None, extra='') -> str:
    line = f' stroke="{stroke}"' if stroke else ''
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" fill="{fill}"{line}{extra}/>'


def bubble_path(x, y, w, h, r, corner) -> str:
    """A rounded box with one small corner: 'tl' for group members, 'tr' for the bot, like the panel."""
    tl, tr = (4, r) if corner == 'tl' else (r, 4)
    return (f'<path d="M{x + tl:.1f} {y:.1f}H{x + w - tr:.1f}Q{x + w:.1f} {y:.1f} {x + w:.1f} {y + tr:.1f}'
            f'V{y + h - r:.1f}Q{x + w:.1f} {y + h:.1f} {x + w - r:.1f} {y + h:.1f}H{x + r:.1f}'
            f'Q{x:.1f} {y + h:.1f} {x:.1f} {y + h - r:.1f}V{y + tl:.1f}Q{x:.1f} {y:.1f} {x + tl:.1f} {y:.1f}Z"')


def icon(name, x, y, size, color, width=2) -> str:
    scale = size / 24
    return (f'<g transform="translate({x:.1f},{y:.1f}) scale({scale:.4f})" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>')


def mark(card: Card, x, y, size, animate=False) -> str:
    key = card.key if animate else 'none'
    inner = MARK.format(k=key)
    if animate:
        inner = f'<g class="{card.key}-bob">{inner}</g>'
    return f'<svg x="{x:.1f}" y="{y:.1f}" width="{size * 80 / 88:.1f}" height="{size:.1f}" viewBox="8 0 80 88">{inner}</svg>'


def spinner(card: Card, cx, cy, r, color) -> str:
    length = 2 * 3.1416 * r
    return (f'<g class="{card.key}-spin"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linecap="round" stroke-dasharray="{length * 0.68:.1f} {length:.1f}"/></g>')


def avatar(card: Card, cx, cy, r, who: str, colors: str) -> str:
    background, color = colors.split(':')
    return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{background}"/>'
            + text(cx, cy + r * 0.36, who[0], round(r * 0.95), color, weight=600, anchor='middle'))


def bot_avatar(card: Card, cx, cy, r) -> str:
    return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{card.p["soft"]}"/>'
            + mark(card, cx - r * 0.78, cy - r * 0.82, r * 1.7))


def message(card: Card, x, y, width, who, value, *, me=False, verdict=None, time='', head=True, size=15,
            avatar_r=16, colors='', mention=None, mirror=False) -> tuple[str, float]:
    """A chat row in the panel's layout; returns the markup and its height.

    The group page puts the bot on the right; mirror puts it on the left, as the test chat page does.
    """
    p = card.p
    pad_x, pad_y, line_h = size * 0.75, size * 0.6, size * 1.45
    limit = width - avatar_r * 2 - 70
    lines = wrap(value, size, limit)
    inner_w = max(text_width(line, size) for line in lines)
    bubble_w, bubble_h = inner_w + pad_x * 2, pad_y * 2 + size + (len(lines) - 1) * line_h
    head_h = size * 1.15 if head else 0
    gap = avatar_r * 2 + 10
    parts = []
    right = me != mirror
    face = (lambda cx, cy: bot_avatar(card, cx, cy, avatar_r)) if me else (
        lambda cx, cy: avatar(card, cx, cy, avatar_r, who, colors))
    if right:
        if head:
            parts.append(face(x + width - avatar_r, y + avatar_r))
        bubble_x = x + width - gap - bubble_w
        name_x = x + width - gap
    else:
        if head:
            parts.append(face(x + avatar_r, y + avatar_r))
        bubble_x = x + gap
        name_x = bubble_x
    if head:
        label_size = round(size * 0.8, 1)
        name_w = text_width(who, label_size) + 6
        time_w = text_width(time, label_size)
        if right:
            parts.append(text(name_x, y + label_size, time, label_size, p['subtle'], anchor='end'))
            parts.append(text(name_x - time_w - 7, y + label_size, who, label_size, p['ink2'], weight=600, anchor='end'))
        else:
            parts.append(text(name_x, y + label_size, who, label_size, p['ink2'], weight=600))
            parts.append(text(name_x + name_w, y + label_size, time, label_size, p['subtle']))
            if verdict:
                ix = name_x + name_w + time_w + 7
                tint = p['primary'] if verdict == 'zap' else p['subtle']
                parts.append(icon(verdict, ix, y + label_size - label_size * 0.95, label_size * 1.05, tint, 2.2))
    top = y + head_h + 2
    fill = p['soft'] if right else (p['card'] if mirror else p['fill'])
    outline = f' stroke="{p["line"]}"' if mirror and not right else ''
    parts.append(f'{bubble_path(bubble_x, top, bubble_w, bubble_h, 12, "tr" if right else "tl")} fill="{fill}"{outline}/>')
    for index, line in enumerate(lines):
        baseline = top + pad_y + size * 0.85 + index * line_h
        if index == 0 and mention and line.startswith(mention):
            parts.append(text(bubble_x + pad_x, baseline, line, size, p['ink'],
                              spans=[(mention, p['primary'], 600), (line[len(mention):], p['ink'], 0)]))
        else:
            parts.append(text(bubble_x + pad_x, baseline, line, size, p['ink']))
    return ''.join(parts), head_h + 2 + bubble_h


def typing(card: Card, x, y, *, me=True, size=15, avatar_r=16, width=0, head=True) -> str:
    """Three bouncing dots in a bot bubble, placed where the next bot line will appear; me=False puts it left."""
    p = card.p
    w, h = 58, size * 2.2
    gap = avatar_r * 2 + 10
    bx = x + width - gap - w if me else x + gap
    top = y + (size * 1.15 if head else 0) + 2
    dots = ''.join(f'<g class="{card.key}-dot" style="animation-delay:{i * 0.15:.2f}s">'
                   f'<circle cx="{bx + 17 + i * 12:.1f}" cy="{top + h / 2:.1f}" r="3.2" fill="{p["primary"]}"/></g>'
                   for i in range(3))
    fill = f'fill="{p["soft"]}"' if me else f'fill="{p["card"]}" stroke="{p["line"]}"'
    return f'{bubble_path(bx, top, w, h, 12, "tr" if me else "tl")} {fill}/>{dots}'


def chip(card: Card, x, y, name, label, detail='', *, size=13, h=30, state=None, start=0.0, done=0.0,
         mono=True) -> tuple[str, float]:
    """A tool call chip: icon, tool label and argument, with a spinner that turns into a check."""
    p = card.p
    label_w = text_width(label, size)
    detail_w = text_width(detail, size - 0.5, mono) if detail else 0
    w = 12 + 16 + 8 + label_w + (10 + detail_w if detail else 0) + (34 if state else 14)
    parts = [rect(x, y, w, h, 9, p['card'], p['line']), icon(name, x + 12, y + (h - 16) / 2, 16, p['primary'])]
    parts.append(text(x + 36, y + h / 2 + size * 0.36, label, size, p['ink'], weight=600))
    if detail:
        parts.append(text(x + 36 + label_w + 10, y + h / 2 + size * 0.36, detail, size - 0.5, p['muted'],
                          mono_key=card.key if mono else None))
    if state:
        cx, cy = x + w - 18, y + h / 2
        parts.append(card.group(card.show(start, done, final=False, rise=0), spinner(card, cx, cy, 6, p['primary'])))
        parts.append(card.group(card.show(done, zoom=True), icon('check', cx - 8, cy - 8, 16, p['success'], 2.6)))
    return ''.join(parts), w


def switch(card: Card, x, y, on_at: float, *, w=40, h=22) -> str:
    """A toggle whose knob slides right and track turns pink at on_at."""
    p = card.p
    card.count += 1
    name = f'{card.key}-k{card.count}'
    travel = w - h
    card.css.append(f'@keyframes {name}{{0%,{card.pct(on_at)}%{{transform:none}}{card.pct(on_at + 0.4)}%,'
                    f'{card.pct(card.loop - 0.6)}%{{transform:translateX({travel}px)}}100%{{transform:none}}}}'
                    f'.{name}{{animation:{name} {card.loop}s {EASE} infinite;transform:translateX({travel}px)}}')
    return (rect(x, y, w, h, h / 2, p['strong'])
            + card.group(card.show(on_at, rise=0), rect(x, y, w, h, h / 2, p['primary']))
            + f'<g class="{name}"><circle cx="{x + h / 2:.1f}" cy="{y + h / 2:.1f}" r="{h / 2 - 3}" fill="#ffffff"/></g>')


def frame(card: Card, icon_name: str, title: str) -> None:
    """The outer box of a feature card: a soft glow, an icon tile and a title."""
    p, k, w, h = card.p, card.key, card.width, card.height
    card.defs.append(
        f'<radialGradient id="{k}-glow" cx="0.92" cy="0.02" r="0.7"><stop offset="0" stop-color="{p["glow"]}" '
        f'stop-opacity=".55"/><stop offset=".55" stop-color="{p["glow2"]}" stop-opacity=".16"/>'
        f'<stop offset="1" stop-color="{p["card"]}" stop-opacity="0"/></radialGradient>')
    card.add(rect(1, 1, w - 2, h - 2, 22, p['card'], p['line']), rect(1, 1, w - 2, h - 2, 22, f'url(#{k}-glow)'))
    card.add(rect(28, 26, 44, 44, 13, p['soft']), icon(icon_name, 39, 37, 22, p['primary']))
    card.add(text(86, 55, title, 20, p['ink'], weight=700))


# Scenes. Each takes the language strings and the palette and returns a finished card.

def turn_card(t: dict, p: dict) -> Card:
    card = Card('tu', 1000, 690, 15, p)
    fx, fy, fw, fh = 20, 12, 960, 648
    card.add(f'<g filter="url(#tu-shadow)">{rect(fx, fy, fw, fh, 18, p["card"], p["line"])}</g>')
    # Group header and tabs, as on the panel's group page.
    card.add(rect(fx + 24, fy + 18, 40, 40, 11, p['soft2']),
             text(fx + 44, fy + 45, t['group'][0], 19, p['primary'], weight=700, anchor='middle'),
             text(fx + 78, fy + 35, t['group'], 17, p['ink'], weight=700),
             f'<circle cx="{fx + 82}" cy="{fy + 50}" r="3.5" fill="{p["success"]}"/>',
             text(fx + 91, fy + 54.5, t['meta'], 12.5, p['muted']))
    card.add(rect(fx + fw - 74, fy + 28, 46, 24, 12, p['primary']),
             f'<circle cx="{fx + fw - 40}" cy="{fy + 40}" r="9" fill="{p["on_primary"]}"/>',
             text(fx + fw - 86, fy + 45, t['chat'], 13, p['ink2'], weight=600, anchor='end'))
    tab_x = fx + 24
    for index, tab in enumerate(t['tabs']):
        color = p['ink'] if index == 0 else p['muted']
        card.add(text(tab_x, fy + 96, tab, 14, color, weight=600 if index == 0 else 400))
        if index == 0:
            card.add(rect(tab_x, fy + 106, text_width(tab, 14), 2.5, 1.2, p['primary']))
        tab_x += text_width(tab, 14) + 26
    card.add(f'<path d="M{fx} {fy + 108.5}H{fx + fw}" stroke="{p["line"]}"/>')

    # Chat on the left.
    cx, cw = fx + 28, 516
    y = fy + 130
    times = [0.4, 1.2, 2.1]
    colors = p['avatars']
    for index, (who, value, verdict) in enumerate(t['messages']):
        mention = t['mention'] if verdict == 'zap' else None
        markup, height = message(card, cx, y, cw, who, value, verdict=verdict, time=t['times'][index],
                                 colors=colors[[0, 1, 0][index]], mention=mention)
        card.add(card.group(card.show(times[index]), markup))
        y += height + 16
    first, height1 = message(card, cx, y, cw, t['bot'], t['lines'][0], me=True, time=t['times'][3])
    card.add(card.group(card.show(7.0, 7.8, final=False), typing(card, cx, y, width=cw)))
    card.add(card.group(card.show(7.8), first))
    y += height1 + 6
    second, height2 = message(card, cx, y, cw, t['bot'], t['lines'][1], me=True, head=False)
    card.add(card.group(card.show(8.7, 9.4, final=False), typing(card, cx, y, width=cw, head=False)))
    card.add(card.group(card.show(9.4), second))
    y += height2 + 16
    # The group carries on and the bot listens.
    for index, (who, value) in enumerate(t['after']):
        markup, height = message(card, cx, y, cw, who, value, verdict='moon', time=t['times'][3],
                                 colors=colors[[2, 1][index]])
        card.add(card.group(card.show(10.8 + index * 0.8), markup))
        y += height + 16

    # The turn on the right.
    tx, tw, ty = fx + 572, 364, fy + 128
    th = fh - (ty - fy) - 22
    card.add(card.group(card.show(2.7), rect(tx, ty, tw, th, 14, p['card'], p['strong'])))
    head = ty + 26
    card.add(card.group(card.show(2.7, 10.2, final=False, rise=0), spinner(card, tx + 24, head, 7, p['primary']),
                        text(tx + 42, head + 5, t['running'], 14, p['primary'], weight=700),
                        text(tx + 42 + text_width(t['running'], 14) + 8, head + 5, t['channel'], 13.5, p['ink2'])))
    card.add(card.group(card.show(10.2, zoom=True), icon('sparkles', tx + 15, head - 9, 18, p['primary'])))
    card.add(card.group(card.show(10.2, rise=0), text(tx + 42, head + 5, t['summary'], 13.5, p['ink2'])))
    card.add(text(tx + tw - 16, head + 5, t['times'][2], 12, p['subtle'], anchor='end'))
    card.add(card.group(card.show(2.7), f'<path d="M{tx} {ty + 50}H{tx + tw}" stroke="{p["line"]}"/>'))

    sx, sw = tx + 18, tw - 36
    y = ty + 76
    card.add(card.group(card.show(3.2), icon('brain', sx, y - 13, 16, p['muted']),
                        text(sx + 24, y, t['recall'], 13, p['muted'])))
    y += 30
    card.add(card.group(card.show(3.8), text(sx, y, t['step'].format(n=1), 12, p['subtle'], weight=600)))
    y += 22
    indent = text_width(t['thought'], 12) + 12
    thought = wrap(t['thoughts'][0], 13.5, sw - indent)
    card.add(card.group(card.show(3.8), text(sx, y, t['thought'], 12, p['primary'], weight=600),
                        *[text(sx + indent, y + i * 20, line, 13.5, p['ink2']) for i, line in enumerate(thought)]))
    y += len(thought) * 20 + 4
    markup, _ = chip(card, sx, y, 'search', t['tool'], t['query'], state=True, start=4.7, done=5.7)
    card.add(card.group(card.show(4.7), markup))
    y += 44
    result_lines = [line for item in t['results'] for line in wrap(item, 12.5, sw - 16)]
    card.add(card.group(card.show(5.8), f'<path d="M{sx + 1} {y - 4}V{y + len(result_lines) * 19 - 8}" '
                                        f'stroke="{p["strong"]}" stroke-width="2"/>',
                        *[text(sx + 12, y + 8 + i * 19, line, 12.5, p['muted']) for i, line in enumerate(result_lines)]))
    y += len(result_lines) * 19 + 22
    card.add(card.group(card.show(6.6), text(sx, y, t['step'].format(n=2), 12, p['subtle'], weight=600)))
    y += 22
    thought = wrap(t['thoughts'][1], 13.5, sw - indent)
    card.add(card.group(card.show(6.6), text(sx, y, t['thought'], 12, p['primary'], weight=600),
                        *[text(sx + indent, y + i * 20, line, 13.5, p['ink2']) for i, line in enumerate(thought)]))
    y += len(thought) * 20 + 4
    say_limit = sw - 64 - text_width(t['say'], 13)

    def preview(line: str) -> str:
        return line if text_width(line, 12.5) <= say_limit else wrap(line, 12.5, say_limit - 14)[0].rstrip(' ,，') + '…'

    markup, _ = chip(card, sx, y, 'message', t['say'], preview(t['lines'][0]), mono=False)
    card.add(card.group(card.show(7.8), markup))
    y += 52
    card.add(card.group(card.show(8.7), text(sx, y, t['step'].format(n=3), 12, p['subtle'], weight=600)))
    y += 12
    markup, _ = chip(card, sx, y, 'message', t['say'], preview(t['lines'][1]), mono=False)
    card.add(card.group(card.show(9.4), markup))
    card.add(card.group(card.show(10.2), f'<path d="M{tx} {ty + th - 44}H{tx + tw}" stroke="{p["line"]}"/>',
                        text(sx, ty + th - 17, t['footer'], 12.5, p['muted'])))
    return card


def listen_card(t: dict, p: dict) -> Card:
    card = Card('li', 480, 390, 12, p)
    frame(card, 'eye', t['title'])
    x, w, y = 28, 424, 98
    colors = p['avatars']
    (who1, line1), (who2, line2), (who3, line3) = t['messages']
    markup, h = message(card, x, y, w, who1, line1, verdict='zap', time='14:52', size=14, avatar_r=14, colors=colors[2])
    card.add(card.group(card.show(0.4), markup))
    y += h + 12
    markup, h = message(card, x, y, w, who2, line2, verdict='moon', time='14:52', size=14, avatar_r=14, colors=colors[0])
    card.add(card.group(card.show(1.3), markup))
    y += h + 12
    # The compact turn card: running, then listened.
    pill_w = max(text_width(t['pill'], 13), text_width(t['running'], 13)) + 52
    px = x + 38
    card.add(card.group(card.show(2.1), rect(px, y, pill_w, 30, 9, p['card'], p['strong'])))
    card.add(card.group(card.show(2.1, 3.6, final=False, rise=0), spinner(card, px + 17, y + 15, 6, p['primary']),
                        text(px + 32, y + 19.5, t['running'], 13, p['primary'], weight=600)))
    card.add(card.group(card.show(3.6, zoom=True), icon('eye', px + 9, y + 7, 16, p['primary'])))
    card.add(card.group(card.show(3.6, rise=0), text(px + 32, y + 19.5, t['pill'], 13, p['ink2'])))
    y += 44
    markup, h = message(card, x, y, w, who3, line3, verdict='zap', time='14:53', size=14, avatar_r=14,
                        colors=colors[0], mention=t['mention'])
    card.add(card.group(card.show(5.0), markup))
    y += h + 8
    card.add(card.group(card.show(5.8, 6.7, final=False), typing(card, x, y, size=14, avatar_r=14, width=w)))
    markup, _ = message(card, x, y, w, t['bot'], t['reply'], me=True, time='14:53', size=14, avatar_r=14)
    card.add(card.group(card.show(6.7), markup))
    return card


def lookup_card(t: dict, p: dict) -> Card:
    card = Card('lo', 480, 390, 12, p)
    frame(card, 'search', t['title'])
    x, w, y = 28, 424, 98
    markup, h = message(card, x, y, w, t['asker'], t['question'], verdict='zap', time='20:15', size=14, avatar_r=14,
                        colors=p['avatars'][3], mention=t['mention'])
    card.add(card.group(card.show(0.4), markup))
    y += h + 14
    markup, chip_w = chip(card, x + 38, y, 'file', t['tool'], t['file'], state=True, start=1.3, done=2.4, mono=False)
    card.add(card.group(card.show(1.3), markup))
    y += 40
    quote_w = w - 38
    card.add(card.group(card.show(2.5),
                        rect(x + 38, y, quote_w, 58, 10, p['code'], p['line']),
                        rect(x + 38, y, 3, 58, 1.5, p['brand']),
                        text(x + 52, y + 22, t['section'], 12, p['muted'], mono_key='lo'),
                        text(x + 52, y + 44, t['snippet'], 13.5, p['ink'], weight=600)))
    y += 70
    card.add(card.group(card.show(3.2, 4.0, final=False), typing(card, x, y, size=14, avatar_r=14, width=w)))
    markup, h = message(card, x, y, w, t['bot'], t['answer'], me=True, time='20:15', size=14, avatar_r=14)
    card.add(card.group(card.show(4.0), markup))
    markup, _ = message(card, x, y + h + 12, w, t['asker'], t['after'], verdict='moon', time='20:16', size=14,
                        avatar_r=14, colors=p['avatars'][3])
    card.add(card.group(card.show(5.4), markup))
    return card


def follow_card(t: dict, p: dict) -> Card:
    card = Card('fo', 480, 390, 13, p)
    frame(card, 'alarm', t['title'])
    x, w, y = 28, 424, 98
    markup, h = message(card, x, y, w, t['asker'], t['ask'], verdict='zap', time='周四' if t['lang'] == 'zh' else 'Thu',
                        size=14, avatar_r=14, colors=p['avatars'][0], mention=t['mention'])
    card.add(card.group(card.show(0.4), markup))
    y += h + 12
    markup, _ = chip(card, x + 38, y, 'alarm', t['tool'], t['when'], state=True, start=1.3, done=2.3, mono=False)
    card.add(card.group(card.show(1.3), markup))
    y += 40
    card.add(card.group(card.show(2.4, 3.1, final=False), typing(card, x, y, size=14, avatar_r=14, width=w)))
    markup, h = message(card, x, y, w, t['bot'], t['ok'], me=True, time='周四' if t['lang'] == 'zh' else 'Thu',
                        size=14, avatar_r=14)
    card.add(card.group(card.show(3.1), markup))
    y += h + 8
    # Time passes: a divider with a clock whose hand turns.
    label_w = text_width(t['divider'], 12.5) + 30
    mid = x + w / 2
    card.add(card.group(card.show(4.3),
                        f'<path d="M{x} {y + 14}H{mid - label_w / 2 - 8}M{mid + label_w / 2 + 8} {y + 14}H{x + w}" '
                        f'stroke="{p["line"]}" stroke-dasharray="4 5"/>',
                        rect(mid - label_w / 2, y + 2, label_w, 24, 12, p['soft']),
                        f'<circle cx="{mid - label_w / 2 + 14}" cy="{y + 14}" r="6.5" fill="none" stroke="{p["primary"]}" stroke-width="1.6"/>',
                        f'<g class="fo-spin" style="animation-duration:1.2s"><path d="M{mid - label_w / 2 + 14} {y + 14}V{y + 10}" '
                        f'stroke="{p["primary"]}" stroke-width="1.6" stroke-linecap="round"/></g>',
                        text(mid - label_w / 2 + 25, y + 18.5, t['divider'], 12.5, p['primary'], weight=600)))
    y += 38
    card.add(card.group(card.show(5.1, 5.9, final=False), typing(card, x, y, size=14, avatar_r=14, width=w)))
    markup, _ = message(card, x, y, w, t['bot'], t['remind'], me=True, time='17:00', size=14, avatar_r=14)
    card.add(card.group(card.show(5.9), markup))
    return card


def memory_card(t: dict, p: dict) -> Card:
    card = Card('me', 480, 390, 12, p)
    frame(card, 'file', t['title'])
    x, y = 28, 96
    tree_w = 168
    card.add(rect(x, y, 424, 210, 14, p['code'], p['line']))
    card.add(f'<path d="M{x + tree_w} {y}V{y + 210}" stroke="{p["line"]}"/>')
    rows = [(0, 'folder', 'people/'), (1, 'folder', 'onebot:70003/'), (2, 'file', 'profile.md'),
            (2, 'file', 'preferences.md'), (0, 'folder', 'events/'), (0, 'folder', 'learning/')]
    ry = y + 16
    for index, (depth, kind, name) in enumerate(rows):
        selected = name == 'preferences.md'
        if selected:
            card.add(card.group(card.show(0.6, rise=0), rect(x + 6, ry - 2, tree_w - 12, 26, 7, p['soft'])))
        color = p['primary'] if selected else (p['ink2'] if kind == 'folder' else p['muted'])
        card.add(icon(kind, x + 14 + depth * 14, ry + 3, 14, color),
                 text(x + 34 + depth * 14, ry + 15, name, 12, color, weight=600 if selected else 400, mono_key='me'))
        ry += 30
    ex = x + tree_w + 18
    card.add(icon('file', ex, y + 15, 14, p['muted']), text(ex + 20, y + 27, 'preferences.md', 12, p['muted'], mono_key='me'))
    card.add(f'<path d="M{x + tree_w} {y + 42}H{x + 424}" stroke="{p["line"]}"/>')
    ly = y + 70
    for index, line in enumerate(t['lines']):
        start = 1.0 + index * 0.8
        color = p['primary'] if line.startswith('#') else p['ink']
        card.add(card.group(card.show(start, rise=3), text(ex, ly, line, 13.5, color,
                                                           weight=700 if line.startswith('#') else 400)))
        ly += 27
    card.add(card.group(card.show(1.0 + len(t['lines']) * 0.8, rise=0), rect(ex, ly - 14, 2, 18, 1, p['primary'])))
    by = y + 226
    markup, _ = chip(card, x, by, 'sparkles', t['upkeep'], t['upkeep_when'], state=True, start=4.6, done=5.8, mono=False)
    card.add(card.group(card.show(4.6), markup))
    return card


def persona_card(t: dict, p: dict) -> Card:
    card = Card('pe', 480, 390, 12, p)
    frame(card, 'user', t['title'])
    x, y, w = 28, 96, 424
    card.add(rect(x, y, w, 76, 14, p['code'], p['line']), bot_avatar(card, x + 38, y + 38, 24))
    card.add(text(x + 74, y + 32, t['name'], 17, p['ink'], weight=700),
             text(x + 74, y + 56, t['brief'], 13, p['muted']),
             text(x + w - 14, y + 30, 'persona.yaml', 11.5, p['subtle'], anchor='end', mono_key='pe'))
    y += 98
    card.add(text(x, y, t['styles_label'], 12.5, p['muted'], weight=600))
    picks = [0, 1, 0, 2]
    span = 2.4
    for turn, pick in enumerate(picks):
        start, end = 0.9 + turn * span, 0.9 + (turn + 1) * span - 0.15
        card.add(card.group(card.show(start, end if turn < 3 else None, rise=0, final=turn == 3),
                            text(x + w, y, t['turn'].format(n=turn + 1), 12.5, p['primary'], weight=600, anchor='end')))
    y += 14
    for index, (name, weight) in enumerate(t['styles']):
        ry = y + index * 40
        for turn, pick in enumerate(picks):
            if pick == index:
                start, end = 0.9 + turn * span, 0.9 + (turn + 1) * span - 0.15
                card.add(card.group(card.show(start, end if turn < 3 else None, rise=0, final=turn == 3),
                                    rect(x - 6, ry - 2, w + 12, 36, 10, p['soft'])))
        bar_x, bar_w = x + 120, w - 120 - 52
        card.add(text(x + 6, ry + 21, name, 13.5, p['ink'], weight=600),
                 rect(bar_x, ry + 13, bar_w, 8, 4, p['fill']),
                 text(x + w - 6, ry + 21, f'{round(weight * 100)}%', 12.5, p['muted'], anchor='end'))
        card.add(card.group(card.grow(0.3 + index * 0.2), rect(bar_x, ry + 13, bar_w * weight, 8, 4, p['brand'])))
    y += 3 * 40 + 8
    fx = x
    for index, name in enumerate(t['files']):
        fw = text_width(name, 11.5, mono=True) + 18
        card.add(card.group(card.show(0.4 + index * 0.15, rise=3), rect(fx, y, fw, 24, 8, p['card'], p['line']),
                            text(fx + 9, y + 16, name, 11.5, p['muted'], mono_key='pe')))
        fx += fw + 8
    return card


def plugin_card(t: dict, p: dict) -> Card:
    card = Card('pl', 480, 390, 12, p)
    frame(card, 'code', t['title'])
    x, y, w = 28, 94, 424
    kw, deco, string, plain, name = p['primary'], p['accent'], p['string'], p['ink2'], p['ink']
    code = [
        [('class ', kw), ('Counter', name), ('(Plugin):', plain)],
        [('    ', plain), ('@fullmatch', deco), ('(', plain), (t['trigger_q'], string), (', ', plain),
         (t['desc_q'], string), (')', plain)],
        [('    ', plain), ('async def ', kw), ('increment', name), ('(self, ctx):', plain)],
        [('        value = ', plain), ('await ', kw), ('ctx.get_kv(ctx.scene, 0) + 1', plain)],
        [('        ', plain), ('await ', kw), ('ctx.set_kv(ctx.scene, value)', plain)],
        [('        ', plain), ('await ', kw), ('ctx.reply(', plain), (t['reply_f'], string), (')', plain)],
    ]
    card.add(rect(x, y, w, 146, 14, p['code'], p['line']))
    for index, spans in enumerate(code):
        line = ''.join(part for part, _ in spans)
        card.add(card.group(card.show(0.3 + index * 0.32, rise=3),
                            text(x + 14, y + 26 + index * 20, line, 11.5, plain, mono_key='pl',
                                 spans=[(part.replace(' ', '\u00a0'), color, 0) for part, color in spans])))
    y += 160
    for round_index, (start, end) in enumerate([(2.8, 6.4), (6.8, None)]):
        markup, h = message(card, x, y, w, t['user'], t['trigger'], time='21:0' + str(round_index + 3), size=14,
                            avatar_r=14, colors=p['avatars'][2])
        card.add(card.group(card.show(start, end, final=end is None), markup))
        markup, _ = message(card, x, y + h + 4, w, t['bot'], t['result'].format(n=round_index + 1), me=True,
                            time='21:0' + str(round_index + 3), size=14, avatar_r=14)
        card.add(card.group(card.show(start + 0.5, end, final=end is None), markup))
    return card


def setup_card(t: dict, p: dict) -> Card:
    card = Card('se', 1000, 280, 12, p)
    w, h = 1000, 280
    card.add(rect(1, 1, w - 2, h - 2, 22, p['card'], p['line']))
    xs = [130, 370, 630, 870]
    line_y = 52
    card.add(rect(xs[0], line_y - 2, xs[-1] - xs[0], 4, 2, p['fill']))
    # The progress line grows from step to step.
    for index in range(3):
        start = 0.6 + index * 2.4 + 0.9
        seg = f'se-g{index}'
        card.css.append(f'@keyframes {seg}{{0%,{card.pct(start)}%{{opacity:1;transform:scaleX(0)}}{card.pct(start + 1.4)}%,'
                        f'{card.pct(card.loop - 0.8)}%{{opacity:1;transform:scaleX(1)}}{card.pct(card.loop - 0.4)}%,100%'
                        f'{{transform:scaleX(1);opacity:0}}}}'
                        f'.{seg}{{transform-box:fill-box;transform-origin:left center;'
                        f'animation:{seg} {card.loop}s {EASE} infinite}}')
        card.add(f'<g class="{seg}">{rect(xs[index], line_y - 2, xs[index + 1] - xs[index], 4, 2, p["brand"])}</g>')
    for index, cx in enumerate(xs):
        start = 0.6 + index * 2.4
        card.add(f'<circle cx="{cx}" cy="{line_y}" r="19" fill="{p["card"]}" stroke="{p["strong"]}" stroke-width="2"/>',
                 text(cx, line_y + 6, str(index + 1), 15, p['muted'], weight=700, anchor='middle'))
        card.add(card.group(card.show(start, zoom=True),
                            f'<circle cx="{cx}" cy="{line_y}" r="19" fill="{p["primary"]}"/>',
                            text(cx, line_y + 6, str(index + 1), 15, p['on_primary'], weight=700, anchor='middle')))
        card.add(text(cx, 106, t['steps'][index], 16, p['ink'], weight=700, anchor='middle'))
    # 1: three ways to deploy; the highlight passes over each in turn.
    tx, ty = xs[0] - 104, 126
    card.add(rect(tx, ty, 208, 118, 12, p['code'], p['line']))
    beat, k = 1.2, 0
    while 0.6 + (k + 1) * beat <= card.loop - 0.8:
        start = 0.6 + k * beat
        last = 0.6 + (k + 2) * beat > card.loop - 0.8
        card.add(card.group(card.show(start, None if last else start + beat - 0.2, rise=0, final=last),
                            rect(tx + 8, ty + 8 + (k % 3) * 34, 192, 32, 9, p['soft'])))
        k += 1
    for i, (name, label) in enumerate(zip(('container', 'package', 'terminal'), t['deploy'])):
        card.add(icon(name, tx + 20, ty + 16 + i * 34, 16, p['primary']),
                 text(tx + 46, ty + 29 + i * 34, label, 13.5, p['ink'], weight=600))
    # 2: the five wizard steps fill one by one.
    wx, wy = xs[1] - 104, 126
    card.add(rect(wx, wy, 208, 118, 12, p['code'], p['line']))
    label_size = 11.5 if max(text_width(label, 11.5) for label in t['wizard']) <= 38 else 10
    for i, label in enumerate(t['wizard']):
        dx = wx + 22 + i * 41
        card.add(f'<circle cx="{dx}" cy="{wy + 34}" r="11" fill="{p["fill"]}" stroke="{p["strong"]}"/>')
        card.add(card.group(card.show(3.2 + i * 0.35, zoom=True), f'<circle cx="{dx}" cy="{wy + 34}" r="11" fill="{p["brand"]}"/>',
                            icon('check', dx - 6, wy + 28, 12, '#ffffff', 3)))
        card.add(text(dx, wy + 66, label, label_size, p['muted'], anchor='middle'))
    card.add(card.group(card.show(5.0), rect(wx + 40, wy + 82, 128, 24, 12, p['primary']),
                        text(wx + 104, wy + 98.5, t['save'], 12, p['on_primary'], weight=600, anchor='middle')))
    # 3: a test group chat: pick who speaks, the bot answers.
    cx0, cy0 = xs[2] - 110, 126
    card.add(rect(cx0, cy0, 220, 118, 12, p['code'], p['line']))
    chip_x = cx0 + 10
    chips = []
    for i, who in enumerate(t['members']):
        cw = text_width(who, 11.5) + 32
        chips.append((chip_x, cw))
        card.add(rect(chip_x, cy0 + 10, cw, 22, 11, p['card'], p['line']))
        chip_x += cw + 6
    for i, (start, end) in enumerate([(5.4, 5.9), (5.9, None)]):
        cxi, cw = chips[i]
        card.add(card.group(card.show(start, end, rise=0, final=end is None),
                            rect(cxi, cy0 + 10, cw, 22, 11, p['soft'], p['primary'])))
    for i, who in enumerate(t['members']):
        cxi, cw = chips[i]
        card.add(avatar(card, cxi + 11, cy0 + 21, 8, who, p['avatars'][i]),
                 text(cxi + 24, cy0 + 25, who, 11.5, p['ink2']))
    q_w = text_width(t['test_q'], 12.5) + 20
    card.add(card.group(card.show(6.2), f'{bubble_path(cx0 + 210 - q_w, cy0 + 44, q_w, 28, 10, "tr")} fill="{p["soft"]}"/>',
                        text(cx0 + 220 - q_w, cy0 + 62.5, t['test_q'], 12.5, p['ink'])))
    a_w = text_width(t['test_a'], 12.5) + 20
    card.add(card.group(card.show(7.0), f'{bubble_path(cx0 + 10, cy0 + 80, a_w, 28, 10, "tl")} fill="{p["card"]}" stroke="{p["line"]}"/>',
                        text(cx0 + 20, cy0 + 98.5, t['test_a'], 12.5, p['ink'])))
    # 4: the groups are switched on one after another.
    sx0, sy0 = xs[3] - 104, 126
    card.add(rect(sx0, sy0, 208, 118, 12, p['code'], p['line']))
    for i, group_name in enumerate(t['groups']):
        gy = sy0 + 16 + i * 46
        card.add(rect(sx0 + 14, gy, 30, 30, 8, p['soft2']),
                 text(sx0 + 29, gy + 20.5, group_name[0], 14, p['primary'], weight=700, anchor='middle'),
                 text(sx0 + 54, gy + 20, group_name, 13, p['ink'], weight=600),
                 switch(card, sx0 + 154, gy + 4, 8.4 + i * 0.6))
    return card


def playground_card(t: dict, p: dict) -> Card:
    """The test chat page: pick which member speaks, type, and watch the bot's turns."""
    card = Card('pg', 1000, 600, 16, p)
    fx, fy, fw, fh = 20, 12, 960, 566
    card.add(f'<g filter="url(#pg-shadow)">{rect(fx, fy, fw, fh, 18, p["page"], p["line"])}</g>')
    card.add(text(fx + 28, fy + 43, t['page'], 18, p['ink'], weight=700))
    chip_x = fx + 28 + text_width(t['page'], 18) + 14
    for label, fill, color in ((t['persona'], p['soft'], p['primary']), (t['scene'], p['fill'], p['ink2'])):
        width = text_width(label, 12.5) + 22
        card.add(rect(chip_x, fy + 25, width, 26, 13, fill), text(chip_x + 11, fy + 42.5, label, 12.5, color, weight=600))
        chip_x += width + 8
    # The chat window.
    wx, wy, ww, wh = fx + 24, fy + 68, 600, fh - 68 - 22
    card.add(rect(wx, wy, ww, wh, 14, p['card'], p['line']))
    card.add(text(wx + 18, wy + 30, t['group'], 14.5, p['ink'], weight=700),
             text(wx + 18 + text_width(t['group'], 14.5) + 10, wy + 30, t['people'], 12.5, p['muted']),
             f'<circle cx="{wx + ww - 52}" cy="{wy + 25}" r="3.5" fill="{p["success"]}"/>',
             text(wx + ww - 18, wy + 29.5, t['live'], 12.5, p['muted'], anchor='end'))
    composer = wy + wh - 98
    card.add(f'<path d="M{wx} {wy + 46}H{wx + ww}M{wx} {composer}H{wx + ww}" stroke="{p["line"]}"/>',
             f'<rect x="{wx + 0.5}" y="{wy + 46.5}" width="{ww - 1}" height="{composer - wy - 47}" fill="{p["fill"]}" opacity=".6"/>')
    # Who speaks: one chip per member, the selected one outlined.
    chips, cx = [], wx + 16
    for index, (who, role) in enumerate(t['members']):
        width = text_width(who, 13) + (text_width(role, 11.5) + 6 if role else 0) + 40
        chips.append((cx, width))
        card.add(rect(cx, composer + 14, width, 28, 14, p['card'], p['line']))
        cx += width + 8
    card.add(rect(cx, composer + 14, 28, 28, 14, p['card'], p['line']), icon('plus', cx + 7, composer + 21, 14, p['muted']))
    picks = [(1, 0.4, 3.6), (2, 3.6, 6.4), (0, 6.4, None)]
    for member, start, end in picks:
        x0, width = chips[member]
        card.add(card.group(card.show(start, end, rise=0, final=end is None),
                            rect(x0, composer + 14, width, 28, 14, p['soft'], p['primary'])))
    for index, (who, role) in enumerate(t['members']):
        x0, width = chips[index]
        card.add(avatar(card, x0 + 14, composer + 28, 11, who, p['avatars'][index]),
                 text(x0 + 31, composer + 32.5, who, 13, p['ink']))
        if role:
            card.add(text(x0 + 37 + text_width(who, 13), composer + 32.5, role, 11.5, p['muted']))
    iy = composer + 52
    card.add(rect(wx + 16, iy, ww - 32 - 68, 34, 9, p['card'], p['strong']),
             rect(wx + ww - 16 - 60, iy, 60, 34, 9, p['primary']),
             text(wx + ww - 46, iy + 22, t['send'], 13, p['on_primary'], weight=600, anchor='middle'))
    typed = [(0.7, 1.6), (3.9, 4.6), (6.7, 7.6)]
    gaps = [(0, 0.7), (1.6, 3.9), (4.6, 6.7), (7.6, None)]
    for index, (start, end) in enumerate(gaps):
        who = t['members'][[1, 1, 2, 0][index]][0]
        card.add(card.group(card.show(start, end, rise=0, final=end is None),
                            text(wx + 30, iy + 22, t['placeholder'].format(name=who), 13, p['subtle'])))
    for (start, end), (_, value) in zip(typed, t['said']):
        card.add(card.group(card.show(start, end, rise=0, final=False), text(wx + 30, iy + 22, value, 13, p['ink']),
                            rect(wx + 32 + text_width(value, 13), iy + 9, 1.6, 16, 0.8, p['primary'])))
    # The conversation, members on the right and the bot on the left.
    y = wy + 64
    member_of = {who: index for index, (who, _) in enumerate(t['members'])}
    timeline = [(1.6, 'member', 0), (3.0, 'bot', 0), (4.6, 'member', 1), (7.6, 'member', 2), (9.0, 'bot', 1)]
    for at, kind, index in timeline:
        if kind == 'member':
            who, value = t['said'][index]
            mention = t['mention'] if value.startswith(t['mention']) else None
            markup, height = message(card, wx + 16, y, ww - 32, who, value, size=14, avatar_r=14, mirror=True,
                                     colors=p['avatars'][member_of[who]], mention=mention)
        else:
            card.add(card.group(card.show(at - 0.7, at, final=False),
                                typing(card, wx + 16, y, me=False, size=14, avatar_r=14, width=ww - 32)))
            markup, height = message(card, wx + 16, y, ww - 32, t['bot'], t['replies'][index], me=True, size=14,
                                     avatar_r=14, mirror=True)
        card.add(card.group(card.show(at), markup))
        y += height + 12
    # Turns, one row each.
    lx, ly, lw = fx + 640, wy, 296
    card.add(rect(lx, ly, lw, wh, 14, p['card'], p['line']), text(lx + 18, ly + 30, t['turns'], 14.5, p['ink'], weight=700))
    for index, ((channel, stats, listened), at) in enumerate(zip(t['turn_rows'], (3.0, 5.4, 9.0))):
        ry = ly + 48 + index * 62
        card.add(card.group(card.show(at),
                            rect(lx + 12, ry, lw - 24, 52, 10, p['card'], p['line']),
                            icon('eye' if listened else 'sparkles', lx + 24, ry + 10, 16, p['primary']),
                            text(lx + 48, ry + 22, channel, 13, p['ink'], weight=600),
                            text(lx + 48, ry + 41, stats, 12, p['muted'])))
    return card


def hero_card(t: dict, p: dict) -> Card:
    card = Card('he', 1280, 440, 12, p)
    w, h = 1280, 440
    card.defs.append(
        f'<linearGradient id="he-bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p["soft"]}"/>'
        f'<stop offset="1" stop-color="{p["page"]}"/></linearGradient>'
        '<linearGradient id="he-name" x1="0" y1="0" x2="1" y2="0.3"><stop offset="0" stop-color="#b4476a"/>'
        '<stop offset=".55" stop-color="#e0789a"/><stop offset="1" stop-color="#f0a868"/></linearGradient>'
        '<filter id="he-blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="46"/></filter>'
        f'<pattern id="he-dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.2" '
        f'fill="{p["primary"]}" opacity=".16"/></pattern>'
        '<clipPath id="he-clip"><rect x="0" y="0" width="1280" height="440" rx="28"/></clipPath>')
    card.css.append('.he-blob1{animation:he-drift1 14s ease-in-out infinite}.he-blob2{animation:he-drift2 17s ease-in-out infinite}'
                    '@keyframes he-drift1{0%,100%{transform:none}50%{transform:translate(90px,40px)}}'
                    '@keyframes he-drift2{0%,100%{transform:none}50%{transform:translate(-110px,-30px)}}')
    card.add('<g clip-path="url(#he-clip)">', rect(0, 0, w, h, 28, 'url(#he-bg)'),
             f'<g filter="url(#he-blur)"><g class="he-blob1"><circle cx="980" cy="90" r="170" fill="{p["glow"]}" opacity=".9"/></g>'
             f'<g class="he-blob2"><circle cx="1180" cy="380" r="150" fill="{p["glow2"]}" opacity=".8"/></g>'
             f'<g class="he-blob1"><circle cx="160" cy="420" r="120" fill="{p["glow"]}" opacity=".5"/></g></g>',
             rect(0, 0, w, h, 0, 'url(#he-dots)'), '</g>',
             rect(0.5, 0.5, w - 1, h - 1, 28, 'none', p['line']))
    card.add(mark(card, 86, 104, 232, animate=True))
    card.add(text(330, 196, 'LenBot', 104, 'url(#he-name)', weight=700))
    y = 252
    for line in t['tagline']:
        card.add(text(336, y, line, t['tagline_size'], p['ink'], weight=600))
        y += t['tagline_size'] * 1.3
    # The rotating part of the sentence.
    y += 18
    words = t['words']
    pill_w = max(text_width(word, 22) for word in words) + 36
    card.add(rect(336, y - 28, pill_w, 42, 21, p['card'], p['brand'], ' stroke-width="1.5"'))
    span = card.loop / len(words)
    for index, word in enumerate(words):
        start = index * span
        name = f'he-w{index}'
        card.css.append(f'@keyframes {name}{{0%,{card.pct(start)}%{{opacity:0;transform:translateY(14px)}}'
                        f'{card.pct(start + 0.4)}%,{card.pct(start + span - 0.4)}%{{opacity:1;transform:none}}'
                        f'{card.pct(start + span)}%,100%{{opacity:0;transform:translateY(-14px)}}}}'
                        f'.{name}{{animation:{name} {card.loop}s {EASE} infinite{"" if index == 0 else ";opacity:0"}}}')
        card.add(f'<g class="{name}">{text(336 + pill_w / 2, y, word, 22, p["primary"], weight=700, anchor="middle")}</g>')
    card.add(text(336 + pill_w + 16, y, t['decides'], 22, p['muted'], weight=500))
    # Floating pieces of a turn on the right.
    bx = t['bubbles_x']
    q = t['q']
    qw = text_width(q, 16) + 28
    card.add(f'<g class="he-float">{avatar(card, bx + 18, 128, 18, t["asker"], p["avatars"][0])}'
             f'{bubble_path(bx + 46, 110, qw, 40, 13, "tl")} fill="{p["card"]}" stroke="{p["line"]}"/>'
             + text(bx + 60, 135.5, q, 16, p['ink'], spans=[(t['mention'], p['primary'], 600), (q[len(t['mention']):], p['ink'], 0)])
             + '</g>')
    markup, chip_w = chip(card, bx + 88, 176, 'search', t['tool'], t['query'], size=14, h=36, mono=True)
    card.add(f'<g class="he-float" style="animation-delay:-2s">{markup}</g>')
    a = t['a']
    aw = text_width(a, 16) + 28
    right = w - 34
    card.add(f'<g class="he-float" style="animation-delay:-4s">{bubble_path(right - 46 - aw, 240, aw, 40, 13, "tr")} '
             f'fill="{p["soft2"]}"/>' + text(right - 46 - aw + 14, 265.5, a, 16, p['ink'])
             + bot_avatar(card, right - 18, 258, 18) + '</g>')
    card.add(f'<g class="he-float" style="animation-delay:-1s">'
             f'{rect(right - 46 - 150, 300, 150, 30, 15, p["card"], p["line"])}'
             f'{icon("sparkles", right - 46 - 138, 307, 16, p["primary"])}'
             f'{text(right - 46 - 116, 320, t["summary"], 12.5, p["muted"])}</g>')
    return card


ZH = {
    'lang': 'zh',
    'playground': {
        'label': '对话测试：以不同群友的身份发言，查看 Bot 的回复和回合', 'page': '对话测试', 'persona': '角色：小然',
        'scene': '周末桌游局', 'group': '周末桌游局', 'people': '4 人', 'live': '实时',
        'members': [('小满', ''), ('老周', '管理员'), ('橘子', '')], 'send': '发送', 'placeholder': '以 {name} 的身份发言',
        'said': [('老周', '小然 周六吃火锅去不去'), ('橘子', '那就点鸳鸯锅'), ('小满', '@小然 清汤你想要哪种锅底')],
        'mention': '@小然', 'bot': '小然', 'replies': ['去 不过我只能吃清汤那半边', '菌汤 番茄也行'], 'turns': '回合',
        'turn_rows': [('点名', '1 步 · 1 条发言', False), ('对话继续', '1 步 · 旁听', True), ('被 @ 或回复', '1 步 · 1 条发言', False)],
    },
    'hero': {
        'label': 'LenBot：自主决策的群聊 Agent', 'tagline': ['自主决策的群聊 Agent'], 'tagline_size': 36,
        'words': ['何时开口', '回复谁', '先查什么', '何时跟进'], 'decides': '由同一个聊天模型决定',
        'bubbles_x': 860, 'asker': '小满', 'mention': '@小然', 'q': '@小然 周六带什么零食好', 'tool': '查询聊天记录',
        'query': '零食 辣', 'a': '我带薯片和果干吧', 'summary': '3 步 · 2 条发言',
    },
    'turn': {
        'label': '群聊现场：群友 @ 小然问零食，小然先查询聊天记录，再分两条回复',
        'group': '周末桌游局', 'meta': '聊天中 · 80001 · 42 人 · 小然', 'chat': '聊天',
        'tabs': ['现场', '会话', '记忆', '资料', '任务', '学习', '设置'],
        'messages': [('小满', '这周六还是老地方吗', 'moon'), ('老周', '我带新到的那盒卡坦岛扩展', 'moon'),
                     ('小满', '@小然 周六带什么零食好', 'zap')],
        'mention': '@小然', 'times': ['14:38', '14:38', '14:39', '14:39'], 'bot': '小然',
        'lines': ['我带薯片和果干吧 老周不吃辣 辣条就不拿啦', '橘子要的抹茶饼干我也带一盒'],
        'after': [('橘子', '懂我'), ('老周', '那饮料我来')],
        'running': '进行中', 'channel': '被 @ 或回复', 'summary': '被 @ 或回复 · 3 步 · 2 条发言',
        'recall': '召回记忆 1 条', 'step': '第 {n} 步', 'thought': '想法',
        'thoughts': ['小满在问零食，大家之前说过口味，先翻翻群里的记录', '老周不吃辣，橘子点名要抹茶饼干'],
        'tool': '查询聊天记录', 'query': '零食 辣',
        'results': ['老周 · 10 月 26 日：我一点辣都不吃', '橘子 · 10 月 26 日：零食我要抹茶饼干'],
        'say': '发言', 'footer': '首句 2.4 秒 · 6.1k 入 · 240 出',
    },
    'listen': {
        'label': '看时机开口：被点名时先旁听，被问到才回答', 'title': '何时开口',
        'messages': [('橘子', '东门那家甜品店小然上次也说好吃'), ('小满', '对 就是她推荐的 周六顺路买点'),
                     ('小满', '@小然 你要什么口味')],
        'running': '进行中', 'pill': '点名 · 1 步 · 旁听', 'mention': '@小然', 'bot': '小然', 'reply': '抹茶的 别太甜就行',
    },
    'lookup': {
        'label': '先查再答：查群文件里的规则，再给出答案', 'title': '先查再答',
        'asker': '阿砚', 'question': '@小然 航海家扩展几分赢', 'mention': '@小然', 'tool': '查资料', 'file': '卡坦岛航海家扩展.md',
        'section': '## 胜利条件', 'snippet': '航海家扩展先到 13 分获胜。', 'bot': '小然', 'answer': '13 分 比基础版多 3 分',
        'after': '那今晚就玩航海家',
    },
    'follow': {
        'label': '到点提醒：群友让小然周六五点提醒出发，小然登记提醒并按时发出', 'title': '定时提醒',
        'asker': '小满', 'ask': '@小然 周六下午五点提醒大家出发', 'mention': '@小然',
        'tool': '创建提醒', 'when': '周六 17:00', 'bot': '小然', 'ok': '好 五点叫你们', 'divider': '周六 17:00',
        'remind': '出发啦 六点开局 晚到的负责点外卖',
    },
    'memory': {
        'label': '记得群里的事：记忆按群保存成 Markdown 文件', 'title': '长期记忆',
        'lines': ['# 相处偏好', '- 一点辣都不吃', '- 常带卡坦岛扩展来', '- 骰子被拿走会念叨很久'],
        'upkeep': '后台整理', 'upkeep_when': '群内空闲时',
    },
    'persona': {
        'label': '角色包：每个回合按权重抽取一种说话风格', 'title': '角色包',
        'name': '小一', 'brief': '班里爱聊天的同学，说话直接，喜欢接梗', 'styles_label': '轮换风格', 'turn': '第 {n} 回合',
        'styles': [('简短接话', 0.5), ('展开细聊', 0.3), ('轻快打趣', 0.2)],
        'files': ['voice.md', 'examples.yaml', 'knowledge/', 'stickers/'],
    },
    'plugin': {
        'label': 'Python 插件：一个按群计数的命令', 'title': 'Python 插件',
        'trigger_q': "'计数加一'", 'desc_q': "'增加本群计数'", 'reply_f': "f'本群计数：{value}'", 'user': '橘子',
        'trigger': '计数加一', 'bot': '小然', 'result': '本群计数：{n}',
    },
    'setup': {
        'label': '从部署到接入群聊的四步', 'steps': ['选择部署方式', '首次配置', '模拟群聊', '接入群聊'],
        'deploy': ['Docker', '部署包', '源码'], 'wizard': ['账号', 'QQ', '主人', '模型', '角色'], 'save': '保存并进入面板',
        'members': ['小满', '老周'], 'test_q': '小然 周六吃火锅吗', 'test_a': '去 我吃清汤那半边',
        'groups': ['周末桌游局', '读书会'],
    },
}

EN = {
    'lang': 'en',
    'playground': {
        'label': 'Playground: speak as different members and watch the bot reply, turn by turn', 'page': 'Playground',
        'persona': 'Persona: Xiaoran', 'scene': 'Weekend Board Games', 'group': 'Weekend Board Games', 'people': '4 people',
        'live': 'Live', 'members': [('Mia', ''), ('Joe', 'Admin'), ('Kit', '')], 'send': 'Send',
        'placeholder': 'Speak as {name}',
        'said': [('Joe', 'Xiaoran, hotpot on Saturday?'), ('Kit', 'split pot then'), ('Mia', '@Xiaoran which mild broth?')],
        'mention': '@Xiaoran', 'bot': 'Xiaoran', 'replies': ['sure, but only the mild side for me', 'mushroom, or tomato'],
        'turns': 'Turns',
        'turn_rows': [('Called by name', '1 step · 1 sent', False), ('Conversation continues', '1 step · listened in', True),
                      ('Mention or reply', '1 step · 1 sent', False)],
    },
    'hero': {
        'label': 'LenBot: a group chat agent that decides for itself', 'tagline': ['A group chat agent', 'that decides for itself'],
        'tagline_size': 34, 'words': ['when to speak', 'whom to answer', 'what to check', 'when to follow up'],
        'decides': 'one chat model decides', 'bubbles_x': 900, 'asker': 'Mia', 'mention': '@Xiaoran',
        'q': '@Xiaoran snacks for Saturday?', 'tool': 'Search chat', 'query': 'snacks spicy', 'a': "I'll bring chips",
        'summary': '3 steps · 2 sent',
    },
    'turn': {
        'label': 'Live view: a member asks Xiaoran about snacks; she searches the chat history first, then replies twice',
        'group': 'Weekend Board Games', 'meta': 'Chatting · 80001 · 42 members · Xiaoran', 'chat': 'Chat',
        'tabs': ['Live', 'Session', 'Memory', 'Files', 'Tasks', 'Learning', 'Settings'],
        'messages': [('Mia', 'Same place this Saturday?', 'moon'), ('Joe', "I'm bringing the new Catan expansion", 'moon'),
                     ('Mia', '@Xiaoran what snacks should we bring?', 'zap')],
        'mention': '@Xiaoran', 'times': ['14:38', '14:38', '14:39', '14:39'], 'bot': 'Xiaoran',
        'lines': ["I'll bring chips and dried fruit, no chili strips since Joe can't do spicy",
                  'and a box of the matcha cookies Kit wanted'],
        'after': [('Kit', 'you get me'), ('Joe', "I'll handle drinks then")],
        'running': 'Running', 'channel': 'Mention or reply', 'summary': 'Mention or reply · 3 steps · 2 sent',
        'recall': 'Recalled 1 memory', 'step': 'Step {n}', 'thought': 'Thoughts',
        'thoughts': ['Mia wants snack ideas. People said what they like before, so check the chat.',
                     "Joe can't do spicy and Kit asked for matcha cookies."],
        'tool': 'Search chat history', 'query': 'snacks spicy',
        'results': ["Joe · Oct 26: I don't eat anything spicy", 'Kit · Oct 26: matcha cookies for me'],
        'say': 'Say', 'footer': 'First reply 2.4 s · 6.1k in · 240 out',
    },
    'listen': {
        'label': 'Picks its moments: listens when mentioned in passing, answers when asked', 'title': 'When to speak',
       
        'messages': [('Kit', 'Xiaoran liked that dessert place too'), ('Mia', "yeah, she found it. I'll grab some"),
                     ('Mia', '@Xiaoran what flavor?')],
        'running': 'Running', 'pill': 'Called by name · 1 step · listened in', 'mention': '@Xiaoran', 'bot': 'Xiaoran',
        'reply': 'matcha, not too sweet',
    },
    'lookup': {
        'label': 'Checks before answering: looks up the rules in the group files first', 'title': 'Look up first',
        'asker': 'Ash', 'question': '@Xiaoran how many points to win Seafarers?',
        'mention': '@Xiaoran', 'tool': 'Knowledge', 'file': 'catan-seafarers.md', 'section': '## Winning',
        'snippet': 'Seafarers is won at 13 points.', 'bot': 'Xiaoran', 'answer': '13, three more than the base game',
        'after': 'Seafarers tonight then',
    },
    'follow': {
        'label': 'Reminders: asked to remind the group at five on Saturday, Xiaoran sets it and sends it on time',
        'title': 'Reminders', 'asker': 'Mia',
        'ask': '@Xiaoran remind us to leave at 5 on Sat', 'mention': '@Xiaoran', 'tool': 'Set reminder',
        'when': 'Sat 17:00', 'bot': 'Xiaoran', 'ok': "ok, I'll ping you at five", 'divider': 'Sat 17:00',
        'remind': 'time to go, we start at six',
    },
    'memory': {
        'label': 'Memory: kept per group as Markdown files', 'title': 'Long-term memory',
       
        'lines': ['# Preferences', "- Doesn't eat anything spicy", '- Usually brings the Catan expansion',
                  '- Grumbles when his dice go missing'],
        'upkeep': 'Background upkeep', 'upkeep_when': 'when the group is idle',
    },
    'persona': {
        'label': 'Personas: each turn draws one speaking style by weight', 'title': 'Persona packages',
        'name': 'Yi',
        'brief': 'A chatty classmate, blunt, loves running jokes', 'styles_label': 'Rotating styles', 'turn': 'Turn {n}',
        'styles': [('Short reply', 0.5), ('Go deeper', 0.3), ('Playful', 0.2)],
        'files': ['voice.md', 'examples.yaml', 'knowledge/', 'stickers/'],
    },
    'plugin': {
        'label': 'Python plugins: a per-group counter command', 'title': 'Python plugins',
        'trigger_q': "'count up'",
        'desc_q': "'Add one to this group'", 'reply_f': "f'Count: {value}'", 'user': 'Kit', 'trigger': 'count up',
        'bot': 'Xiaoran', 'result': 'Count: {n}',
    },
    'setup': {
        'label': 'Four steps from deployment to your groups', 'steps': ['Deploy', 'First setup', 'Test group chat',
                                                                         'Add groups'],
        'deploy': ['Docker', 'Release package', 'Source'], 'wizard': ['Panel', 'QQ', 'Owner', 'Model', 'Persona'],
        'save': 'Save and open panel', 'members': ['Mia', 'Joe'], 'test_q': 'hotpot on Saturday?',
        'test_a': 'sure, the mild side', 'groups': ['Board Games', 'Book Club'],
    },
}

SCENES = {'hero': hero_card, 'turn': turn_card, 'playground': playground_card, 'listen': listen_card, 'lookup': lookup_card, 'follow': follow_card,
          'memory': memory_card, 'persona': persona_card, 'plugin': plugin_card, 'setup': setup_card}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('names', nargs='*', help='Only these cards')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, draw in SCENES.items():
        if args.names and name not in args.names:
            continue
        for strings, suffix in ((ZH, ''), (EN, '.en')):
            for palette, theme in ((LIGHT, ''), (DARK, '.dark')):
                t = {**strings[name], 'lang': strings['lang']}
                path = args.output / f'{name}{suffix}{theme}.svg'
                path.write_text(draw(t, palette).svg(t['label']), encoding='utf-8')
                print(path)


if __name__ == '__main__':
    main()
