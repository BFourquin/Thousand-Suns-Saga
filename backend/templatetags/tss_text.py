"""
Formatting of the texts written by the players, with the tags proposed by includes/text_toolbar.html.
Everything is escaped and only the tags below give HTML : no image nor embedded content, an address stays a link.
"""

import re

from django import template
from django.utils.html import escape, urlize
from django.utils.safestring import mark_safe

register = template.Library()

MAX_DEPTH = 16  # Opening tags repeated thousands of times must not nest the page as deep
STYLES = {'b': 'strong', 'i': 'em', 'u': 'u', 's': 's'}
ALIGNMENTS = ('left', 'center', 'right', 'justify')
SIZES = {'1': '0.75rem', '2': '0.875rem', '3': '1rem', '4': '1.25rem', '5': '1.5rem', '6': '2rem', '7': '3rem'}  # rem : nested sizes don't multiply

URL = r'https?://[^\s"\'<>\[\]]+'
URL_VALUE = re.compile(URL, re.IGNORECASE)
COLOR_VALUE = re.compile(r'#[0-9a-f]{3}(?:[0-9a-f]{3})?', re.IGNORECASE)
TAG = re.compile(r'\[(/?)(b|i|u|s|left|center|right|justify|size|color|url)(?:=([^\[\]\n]*))?\]', re.IGNORECASE)
URL_AS_TEXT = re.compile(rf'\[url\]({URL})\[/url\]', re.IGNORECASE)
NEWLINE_AROUND_BLOCK = re.compile(r'\n?(\[/?(?:left|center|right|justify)\])\n?', re.IGNORECASE)  # A block already starts a new line


def opening_tag(name, value):
    # The HTML around the text of a tag. None when it is refused : it stays displayed as it was typed.
    if name in STYLES and value is None:
        return f'<{STYLES[name]}>', f'</{STYLES[name]}>'
    if name in ALIGNMENTS and value is None:
        return f'<div class="text-{name}">', '</div>'
    if name == 'size' and value in SIZES:
        return f'<span style="font-size:{SIZES[value]}">', '</span>'
    if name == 'color' and value and COLOR_VALUE.fullmatch(value):
        return f'<span style="color:{value}">', '</span>'
    if name == 'url' and value and URL_VALUE.fullmatch(value):
        return f'<a href="{escape(value)}" target="_blank" rel="nofollow noopener noreferrer">', '</a>'
    return None


@register.filter
def bbcode(text):
    text = URL_AS_TEXT.sub(r'[url=\1]\1[/url]', text.replace('\r\n', '\n'))
    text = NEWLINE_AROUND_BLOCK.sub(r'\1', text)
    html, opened, position = [], [], 0  # opened : (name, closing HTML) of the tags still open, always balanced at the end

    def add_text_until(end):
        part = text[position:end]
        html.append(escape(part) if any(name == 'url' for name, _ in opened) else urlize(part, nofollow=True, autoescape=True))

    for match in TAG.finditer(text):
        is_closing, name, value = match.group(1) == '/', match.group(2).lower(), match.group(3)
        names = [opened_name for opened_name, _ in opened]

        if is_closing:
            if value is not None or name not in names:
                continue
            add_text_until(match.start())
            while True:  # Also closes what was left open inside : the page around the message must stay intact
                closed_name, closing_html = opened.pop()
                html.append(closing_html)
                if closed_name == name:
                    break
        else:
            tag = opening_tag(name, value)
            if not tag or len(opened) >= MAX_DEPTH or (name == 'url' and name in names):
                continue
            add_text_until(match.start())
            html.append(tag[0])
            opened.append((name, tag[1]))
        position = match.end()

    add_text_until(len(text))
    html.extend(closing_html for _, closing_html in reversed(opened))
    return mark_safe(''.join(html).replace('\n', '<br>'))
