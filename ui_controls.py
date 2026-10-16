"""A true tick-mark checkbox, consistently drawn on Windows and Linux Tk."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk


class TickCheckbutton(tk.Frame):
    """Tk widget with a ✓ mark, BooleanVar binding, keyboard access and ttk-like state."""

    def __init__(self, parent, text='', variable=None, command=None, background='#000000',
                 foreground='#56AD6B', muted='#438B55', outline='#245335',
                 font=('Segoe UI', 11), **kwargs):
        super().__init__(parent, bg=background, takefocus=1, **kwargs)
        self.variable = variable if variable is not None else tk.BooleanVar(master=self, value=False)
        self.command = command
        self.normal_fg = foreground
        self.muted_fg = muted
        self.outline = outline
        self.bg = background
        self._disabled = False
        self.box = tk.Canvas(self, width=21, height=21, bg=background, highlightthickness=0, bd=0)
        self.box.pack(side='left', padx=(0, 7))
        self.label = tk.Label(self, text=text, bg=background, fg=foreground, font=font, anchor='w')
        self.label.pack(side='left')
        for widget in (self, self.box, self.label):
            widget.bind('<Button-1>', self._click)
        self.bind('<space>', self._key)
        self.bind('<Return>', self._key)
        self._trace = self.variable.trace_add('write', lambda *_: self._redraw())
        self._redraw()

    def set_theme(self, background, foreground, muted, outline):
        """Update an existing custom checkbox without losing its selection."""
        self.bg = background
        self.normal_fg = foreground
        self.muted_fg = muted
        self.outline = outline
        super().configure(bg=background)
        self.box.configure(bg=background)
        self.label.configure(bg=background)
        self._redraw()

    def _redraw(self):
        self.box.delete('all')
        line = self.muted_fg if self._disabled else self.outline
        self.box.create_rectangle(2, 2, 19, 19, outline=line, fill=self.bg, width=1.5)
        if self.variable.get():
            color = self.muted_fg if self._disabled else self.normal_fg
            # Draw an actual V-shaped check, not a solid-filled checkbox.
            self.box.create_line(5, 10, 9, 14, 16, 6, fill=color, width=2.4, capstyle='round', joinstyle='round')
        self.label.configure(fg=self.muted_fg if self._disabled else self.normal_fg)
        self.configure(cursor='' if self._disabled else 'hand2')
        self.label.configure(cursor='' if self._disabled else 'hand2')
        self.box.configure(cursor='' if self._disabled else 'hand2')

    def _toggle(self):
        if self._disabled:
            return
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def _click(self, event=None):
        self.focus_set()
        self._toggle()

    def _key(self, event=None):
        self._toggle()
        return 'break'

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        state = kwargs.pop('state', None)
        if state is not None:
            self._disabled = str(state).lower() == 'disabled'
        result = super().configure(**kwargs) if kwargs else None
        if state is not None and hasattr(self, 'box'):
            self._redraw()
        return result

    config = configure
