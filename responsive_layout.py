"""Screen-workarea-based geometry and live width breakpoints (no Tk imports)."""
from __future__ import annotations


def recommended_geometry(work: tuple[int, int, int, int],
                         preferred=(1260, 890)) -> tuple[int, int, int, int]:
    """Return x, y, width, height wholly inside the OS-provided work area.

    Work area excludes a Windows taskbar; it may start at negative coordinates
    for a monitor positioned to the left of the primary monitor.
    """
    left, top, right, bottom = work
    available_width = max(1, right - left)
    available_height = max(1, bottom - top)
    pad_w = 16 if available_width >= 700 else 4
    pad_h = 24 if available_height >= 600 else 4
    width = max(1, min(preferred[0], available_width - pad_w))
    height = max(1, min(preferred[1], available_height - pad_h))
    x = left + max(0, (available_width - width) // 2)
    y = top + max(0, (available_height - height) // 2)
    return (x, y, width, height)


def choose_layout(width: int) -> str:
    """Return footer/header arrangement for the actual client pixel width."""
    if width >= 1130:
        return 'wide'
    if width >= 820:
        return 'medium'
    if width >= 760:
        return 'narrow'
    return 'extra_narrow'
