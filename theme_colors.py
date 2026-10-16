"""Small, portable Tk theme palette helpers (no third-party dependencies)."""
from __future__ import annotations
import re

DEFAULT_THEME = {
    'foreground': '#6CCF83',
    'background': '#000000',
    'accent': '#7ADF95',
}


def normalize_hex(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('색상은 #RRGGBB 형식으로 입력해야 합니다.')
    value = value.strip()
    if re.fullmatch(r'[a-fA-F0-9]{6}', value):
        value = '#' + value
    if not re.fullmatch(r'#[a-fA-F0-9]{6}', value):
        raise ValueError(f'잘못된 색상: {value!r}. 예: #6CCF83')
    return value.upper()


def mix(first: str, second: str, fraction: float) -> str:
    """Linear sRGB blend: fraction=0 first, fraction=1 second."""
    a = normalize_hex(first)
    b = normalize_hex(second)
    if not 0 <= fraction <= 1:
        raise ValueError('fraction must be between 0 and 1')
    return '#' + ''.join(f'{round(int(a[i:i+2], 16)*(1-fraction)+int(b[i:i+2], 16)*fraction):02X}' for i in (1, 3, 5))


def resolve_theme(colors: dict) -> dict:
    if not isinstance(colors, dict):
        raise ValueError('테마 색상이 올바르지 않습니다.')
    fg = normalize_hex(colors['foreground'])
    bg = normalize_hex(colors['background'])
    accent = normalize_hex(colors['accent'])
    return {
        'foreground': fg,
        'background': bg,
        'accent': accent,
        'muted': mix(bg, fg, 0.78),
        'edge': mix(bg, accent, 0.40),
        'hover': mix(bg, accent, 0.14),
        'select': mix(bg, accent, 0.25),
        'dot_on': mix(accent, '#FFFFFF', 0.15),
    }
