"""Small Newick tree previewer and SVG exporter (not a full tree editor)."""
from __future__ import annotations
from dataclasses import dataclass, field
from html import escape
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from ui_controls import TickCheckbutton
from theme_colors import DEFAULT_THEME, resolve_theme

TREE_LINE = "#3F8552"
TREE_TEXT = "#6CCF83"
TREE_SUPPORT = "#7ADF95"


@dataclass
class Node:
    name: str = ""
    length: float | None = None
    children: list["Node"] = field(default_factory=list)
    x: float = 0
    y: float = 0


class Parser:
    def __init__(self, text: str):
        self.s = text.lstrip("\ufeff").strip()
        self.i = 0

    def skip(self):
        s = self.s
        while self.i < len(s):
            if s[self.i].isspace():
                self.i += 1
            elif s[self.i] == "[":
                depth = 1
                self.i += 1
                while self.i < len(s) and depth:
                    if s[self.i] == "[": depth += 1
                    if s[self.i] == "]": depth -= 1
                    self.i += 1
            else:
                break

    def label(self):
        self.skip()
        if self.i >= len(self.s): return ""
        if self.s[self.i] == "'":
            self.i += 1
            chars = []
            while self.i < len(self.s):
                ch = self.s[self.i]
                self.i += 1
                if ch == "'":
                    if self.i < len(self.s) and self.s[self.i] == "'":
                        self.i += 1
                        chars.append("'")
                        continue
                    break
                chars.append(ch)
            return "".join(chars)
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in ",():;[]\t\r\n ":
            self.i += 1
        return self.s[start:self.i]

    def subtree(self, depth=0):
        if depth > 1500:
            raise ValueError("Newick 트리가 너무 깊습니다.")
        self.skip()
        kids = []
        if self.i < len(self.s) and self.s[self.i] == "(":
            self.i += 1
            while True:
                kids.append(self.subtree(depth + 1))
                self.skip()
                if self.i >= len(self.s): raise ValueError("닫는 괄호가 없습니다.")
                ch = self.s[self.i]
                self.i += 1
                if ch == ")": break
                if ch != ",": raise ValueError("Newick 구문 오류: ',' 또는 ')'가 필요합니다.")
        name = self.label()
        self.skip()
        length = None
        if self.i < len(self.s) and self.s[self.i] == ":":
            self.i += 1
            self.skip()
            begin = self.i
            while self.i < len(self.s) and self.s[self.i] not in ",);[\t\r\n ":
                self.i += 1
            raw = self.s[begin:self.i]
            try:
                length = float(raw)
                if not math.isfinite(length) or length < 0:
                    raise ValueError()
            except ValueError:
                raise ValueError(f"잘못된 branch length: {raw}")
        self.skip()
        return Node(name=name, length=length, children=kids)

    def parse(self):
        result = self.subtree()
        self.skip()
        if self.i < len(self.s) and self.s[self.i] == ";": self.i += 1
        self.skip()
        if self.i != len(self.s):
            raise ValueError("Newick 트리 뒤에 예상하지 못한 데이터가 있습니다.")
        return result


def traverse(root):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def tree_layout(root, use_lengths=True, row_space=25, scale=900, margin=35):
    leaves = [n for n in traverse(root) if not n.children]
    if not leaves:
        raise ValueError("리프가 없는 트리입니다.")
    if len(leaves) > 12000:
        raise ValueError("미리보기는 최대 12,000개 리프까지 지원합니다.")
    totals = {id(root): 0.0}
    depths = {id(root): 0}
    stack = [root]
    while stack:
        n = stack.pop()
        for ch in n.children:
            totals[id(ch)] = totals[id(n)] + (ch.length if ch.length is not None else 1)
            depths[id(ch)] = depths[id(n)] + 1
            stack.append(ch)
    has_length = any(n.length is not None for n in traverse(root))
    vals = totals if use_lengths and has_length else depths
    max_distance = max(float(vals[id(n)]) for n in leaves)
    if max_distance <= 0:
        vals = depths
        max_distance = max(float(vals[id(n)]) for n in leaves) or 1.0
    for i, leaf in enumerate(leaves):
        leaf.y = margin + i * row_space
    for n in reversed(list(traverse(root))):
        if n.children:
            n.y = sum(ch.y for ch in n.children) / len(n.children)
        n.x = margin + (float(vals[id(n)]) / max_distance) * scale
    max_label = max((len(n.name) for n in leaves), default=1)
    width = int(margin + scale + max(170, min(800, max_label * 7 + 50)))
    height = int(margin * 2 + (len(leaves) - 1) * row_space)
    return max(450, width), max(180, height), len(leaves)


def segments(root, show_support=True):
    for n in traverse(root):
        if n.children:
            yield ("line", n.x, n.children[0].y, n.x, n.children[-1].y)
            for ch in n.children:
                yield ("line", n.x, ch.y, ch.x, ch.y)
                if ch.children and show_support and ch.name:
                    yield ("support", ch.x + 3, ch.y - 6, ch.name)
        else:
            yield ("label", n.x + 6, n.y, n.name)


def export_svg(root, dest, use_lengths=True, show_support=True, scale=1000, row_space=25):
    w, h, _ = tree_layout(root, use_lengths, row_space, scale)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<g fill="none" stroke="#263746" stroke-width="1.3">']
    data = list(segments(root, show_support))
    for s in data:
        if s[0] == "line":
            lines.append(f'<line x1="{s[1]:.2f}" y1="{s[2]:.2f}" x2="{s[3]:.2f}" y2="{s[4]:.2f}"/>')
    lines.append('</g><g font-family="Arial, sans-serif" fill="#1d2b3a">')
    for s in data:
        if s[0] == "label":
            lines.append(f'<text x="{s[1]:.2f}" y="{s[2] + 4:.2f}" font-size="12">{escape(s[3])}</text>')
        elif s[0] == "support":
            lines.append(f'<text x="{s[1]:.2f}" y="{s[2]:.2f}" font-size="10" fill="#176f80">{escape(s[3])}</text>')
    lines.append('</g></svg>')
    Path(dest).write_text('\n'.join(lines), encoding='utf-8')


class TreeViewer(tk.Toplevel):
    def __init__(self, master, file):
        super().__init__(master)
        self.title('Tree preview — IQ-TREE 2 GUI')
        self.geometry('1150x760')
        self.palette = resolve_theme(getattr(master, 'theme_choice', DEFAULT_THEME))
        self.configure(bg=self.palette['background'])
        self.root_node = Parser(Path(file).read_text(encoding='utf-8', errors='replace')).parse()
        self.path = str(file)
        self.show_support = tk.BooleanVar(value=True)
        self.use_lengths = tk.BooleanVar(value=True)
        self.scale = tk.IntVar(value=900)
        toolbar = ttk.Frame(self, padding=10)
        toolbar.pack(fill='x')
        ttk.Label(toolbar, text=Path(file).name, font=('Segoe UI', 12, 'bold')).pack(side='left', padx=8)
        tick_options = dict(background=self.palette['background'], foreground=self.palette['foreground'],
                            muted=self.palette['muted'], outline=self.palette['edge'], font=('Segoe UI', 11))
        self.length_tick = TickCheckbutton(toolbar, text='Branch length 비례', variable=self.use_lengths, command=self.render, **tick_options)
        self.length_tick.pack(side='left', padx=8)
        self.support_tick = TickCheckbutton(toolbar, text='Support 표시', variable=self.show_support, command=self.render, **tick_options)
        self.support_tick.pack(side='left', padx=8)
        ttk.Label(toolbar, text='가로 배율').pack(side='left', padx=4)
        ttk.Scale(toolbar, from_=300, to=2500, variable=self.scale, command=lambda _: self.render()).pack(side='left', padx=4)
        ttk.Button(toolbar, text='SVG 내보내기', command=self.save_svg).pack(side='right', padx=8)
        frame = tk.Frame(self, bg=self.palette['background'])
        self.display_frame = frame
        frame.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        self.canvas = tk.Canvas(frame, background=self.palette['background'], highlightthickness=0)
        h = ttk.Scrollbar(frame, orient='horizontal', command=self.canvas.xview)
        v = ttk.Scrollbar(frame, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=h.set, yscrollcommand=v.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        v.grid(row=0, column=1, sticky='ns')
        h.grid(row=1, column=0, sticky='ew')
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        ttk.Label(self, text='Newick 내부 node labels를 support로 표시합니다. 표시 방향은 파일의 Newick 구조를 따르며, 루팅을 새로 추정하지 않습니다.', padding=(14, 0, 10, 12)).pack(anchor='w')
        self.render()

    def update_theme(self, palette):
        self.palette = palette
        self.configure(bg=palette['background'])
        self.display_frame.configure(bg=palette['background'])
        self.canvas.configure(bg=palette['background'])
        for tick in (self.length_tick, self.support_tick):
            tick.set_theme(palette['background'], palette['foreground'], palette['muted'], palette['edge'])
        self.render()

    def render(self):
        scale = int(self.scale.get())
        w, h, count = tree_layout(self.root_node, self.use_lengths.get(), 25, scale)
        self.canvas.delete('all')
        self.canvas.configure(scrollregion=(0, 0, w, h))
        for s in segments(self.root_node, self.show_support.get()):
            if s[0] == 'line':
                self.canvas.create_line(s[1], s[2], s[3], s[4], fill=self.palette['edge'], width=1.5)
            elif s[0] == 'label':
                self.canvas.create_text(s[1], s[2], text=s[3].replace('_', ' '), anchor='w', fill=self.palette['foreground'], font=('Segoe UI', 11))
            elif s[0] == 'support':
                self.canvas.create_text(s[1], s[2], text=s[3], anchor='sw', fill=self.palette['accent'], font=('Segoe UI', 9))

    def save_svg(self):
        name = Path(self.path).stem + '.svg'
        out = filedialog.asksaveasfilename(parent=self, initialfile=name, defaultextension='.svg', filetypes=[('SVG image','*.svg')])
        if not out: return
        try:
            export_svg(self.root_node, out, self.use_lengths.get(), self.show_support.get(), scale=self.scale.get())
            messagebox.showinfo('완료', f'SVG 파일을 저장했습니다.\n{out}', parent=self)
        except Exception as ex:
            messagebox.showerror('오류', str(ex), parent=self)
