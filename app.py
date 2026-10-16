"""IQ-TREE 2 GUI — Windows / WSL desktop frontend (tkinter, stdlib-only)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import webbrowser

from iqtree_core import AnalysisConfig, build_command, available_windows_binaries, wsl_distributions, command_string, stop_wsl_pid
from tree_viewer import TreeViewer
from alignment_taxa import read_alignment_taxa, join_outgroups
from ui_controls import TickCheckbutton
from theme_colors import DEFAULT_THEME, normalize_hex, resolve_theme

APP_VERSION = "0.1.7"
BASE = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
RESOURCES = Path(getattr(sys, '_MEIPASS', BASE))
PREFS = Path.home() / '.iqtree2_gui_settings.json'
DOCS = 'https://iqtree.github.io/'
# Initial green-on-black theme; all three colors are user-selectable.
BG = '#000000'
SURFACE = '#000000'
SURFACE2 = '#000000'
ENTRY = '#000000'
FG = '#6CCF83'
MUTED = '#59AE6D'
ACCENT = '#7ADF95'
EDGE = '#2A5F3A'
HOVER = '#102A1A'
SELECT = '#1E4B2D'
STATUS_DOT_ON = '#96F2AE'
STATUS_DOT_OFF = BG
STATUS_DOT_IDLE = ACCENT
STATUS_DOT_WARN = '#C7D96E'
STATUS_DOT_ERROR = '#E67C7C'
FONT = ('Segoe UI', 11)


def enable_high_dpi():
    """Ask Windows for real monitor pixels *before* creating the Tk root.

    Per-monitor DPI awareness allows the window to follow a laptop when it is
    moved between 100%, 125%, and 150% displays. Some packaged executables
    set this awareness in their manifest; a failure here is harmless.
    """
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        try:
            # PER_MONITOR_AWARE_V2 = -4
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                return
        except (AttributeError, OSError):
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass
    except (ImportError, OSError):
        pass


def monitor_work_area():
    """Return the work rectangle of the monitor under the mouse, if available.

    Unlike winfo_screenheight, Windows' rcWork excludes the taskbar.
    If the platform does not provide it, fall back to Tk screen dimensions.
    """
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                        ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]

        user32 = ctypes.windll.user32
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
        user32.MonitorFromPoint.restype = wintypes.HANDLE
        monitor = user32.MonitorFromPoint(point, 2)  # nearest monitor
        if not monitor:
            return None
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MONITORINFO))
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        rect = info.rcWork
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)
    except (AttributeError, OSError, ImportError, TypeError, ValueError):
        return None


def open_local(path: str):
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.hscroll = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vscroll.set, xscrollcommand=self.hscroll.set)
        self.vscroll.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner = ttk.Frame(self.canvas, padding=(14, 8, 16, 20))
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', lambda e: self._sync_scroll_area())
        self.canvas.bind('<Configure>', lambda e: self._sync_scroll_area(e.width))
        # Wheel/Shift+wheel allow access to all settings even on very small screens.
        self.bind_all('<MouseWheel>', self._scroll, add=True)
        self.bind_all('<Shift-MouseWheel>', self._scroll_horizontal, add=True)
        self.bind_all('<Button-4>', self._scroll, add=True)
        self.bind_all('<Button-5>', self._scroll, add=True)

    def _sync_scroll_area(self, viewport_width=None):
        if viewport_width is None:
            viewport_width = self.canvas.winfo_width()
        intrinsic = self.inner.winfo_reqwidth()
        need_horizontal = intrinsic > viewport_width + 1
        # Native field controls have a minimum readable width. On narrower
        # screens the last resort is horizontal scrolling, never silent crop.
        if need_horizontal:
            if not self.hscroll.winfo_manager():
                self.hscroll.pack(side='bottom', fill='x', before=self.canvas)
        elif self.hscroll.winfo_manager():
            self.hscroll.pack_forget()
            self.canvas.xview_moveto(0)
        self.canvas.itemconfigure(self.window, width=max(viewport_width, intrinsic))
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _scroll_horizontal(self, e):
        if not self.canvas.winfo_ismapped():
            return
        if e.delta:
            self.canvas.xview_scroll(-3 if e.delta > 0 else 3, 'units')
        return 'break'

    def _scroll(self, e):
        if not self.canvas.winfo_ismapped(): return
        x, y = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
        if not (x <= e.x_root < x + self.canvas.winfo_width() and y <= e.y_root < y + self.canvas.winfo_height()):
            return
        if getattr(e, 'num', None) == 4: direction = -3
        elif getattr(e, 'num', None) == 5: direction = 3
        elif e.delta: direction = -3 if e.delta > 0 else 3
        else: return
        self.canvas.yview_scroll(direction, 'units')
        return 'break'


class IQTreeGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'IQ-TREE 2 GUI  •  v{APP_VERSION}')
        self.compact_layout = False
        self._last_layout = None
        self._resize_job = None
        self.configure(background=BG)
        self._apply_initial_geometry()
        self.theme_choice = self._read_theme_preferences()
        self._activate_palette(self.theme_choice)
        self._set_icon()
        self.style_widgets()
        self.process: subprocess.Popen | None = None
        self.worker: threading.Thread | None = None
        self.events: queue.Queue = queue.Queue()
        self.is_running = False
        self.stop_requested = False
        self.wsl_pid = None
        self.last_prefix = ''
        self.last_log_file = ''
        self.start_time = 0.0
        self.backend_command = []
        self.theme_dialog = None
        self.status_dot_label: tk.Label | None = None
        self.status_blink_job = None
        self._status_dot_phase = True
        self.vars: dict[str, tk.Variable] = {}
        self.ui_vars()
        self.build_ui()
        self.load_settings()
        self.watch_changes()
        self.on_mode_change()
        self.on_model_change()
        self.on_boot_change()
        self.refresh_preview()
        self.bind('<Configure>', self._on_window_configure, add=True)
        self.after_idle(self._apply_responsive_layout)
        # Windows itself knows how to fit a maximized window into the work
        # area even with non-standard taskbar positions / scaling.
        if sys.platform == 'win32' and self._available_work_height < 900:
            self.after_idle(self._maximize_for_laptop)
        self.after(100, self.poll_events)
        self.protocol('WM_DELETE_WINDOW', self.exit_app)

    def _apply_initial_geometry(self):
        from responsive_layout import recommended_geometry
        self.update_idletasks()
        rect = monitor_work_area() or (0, 0, self.winfo_screenwidth(), self.winfo_screenheight())
        self._available_work_height = rect[3] - rect[1]
        x, y, width, height = recommended_geometry(rect)
        self.compact_layout = height < 790 or width < 1160
        self.geometry(f'{width}x{height}+{x}+{y}')
        # Never require more pixels than the physical screen can provide.
        self.minsize(min(700, width), min(450, height))

    def _maximize_for_laptop(self):
        if not self.winfo_exists():
            return
        try:
            self.state('zoomed')
        except tk.TclError:
            # Only Windows has the zoomed state; non-Windows use geometry.
            pass

    def _on_window_configure(self, event):
        if event.widget is not self:
            return
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        # Reflow when resized or moved to another display, not on each pixel.
        self._resize_job = self.after(70, self._apply_responsive_layout)

    def _apply_responsive_layout(self):
        self._resize_job = None
        if not hasattr(self, 'footer_left'):
            return
        from responsive_layout import choose_layout
        width = self.winfo_width()
        mode = choose_layout(width)
        if mode == self._last_layout:
            return
        self._last_layout = mode
        narrow = mode != 'wide'
        if narrow:
            self.header_subtitle.pack_forget()
        else:
            self.header_subtitle.pack(side='left', padx=(18, 0))
        # Reflow footer rather than silently clipping buttons. Keep controls
        # independently visible when users resize the window.
        self.footer_left.grid_forget()
        self.footer_right.grid_forget()
        for col in (0, 1):
            self.footer.columnconfigure(col, weight=0)
        if mode == 'wide':
            self.footer.columnconfigure(0, weight=1)
            self.footer_left.grid(row=0, column=0, sticky='w')
            self.footer_right.grid(row=0, column=1, sticky='e')
        elif mode == 'medium':
            self.footer.columnconfigure(0, weight=1)
            self.footer_left.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 5))
            self.footer_right.grid(row=1, column=0, columnspan=2, sticky='e')
        else:
            self.footer.columnconfigure(0, weight=1)
            self.footer_left.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 4))
            self.footer_right.grid(row=1, column=0, columnspan=2, sticky='e')
        # Shorter captions are used only for narrow widths; full functionality
        # is not hidden or removed.
        short = mode in ('narrow', 'extra_narrow')
        labels = ('예제', '불러오기', '저장', '색상', '홈페이지') if short else (
            '예제 불러오기', '설정 불러오기', '설정 저장', '색상 설정', '공식 홈페이지')
        for btn in self.footer_aux_buttons:
            btn.grid_forget()
        for i, (btn, label) in enumerate(zip(self.footer_aux_buttons, labels)):
            btn.configure(text=label)
            if mode == 'extra_narrow':
                row, col = divmod(i, 3)
            else:
                row, col = 0, i
            btn.grid(row=row, column=col, sticky='ew', padx=(0, 6), pady=(0, 4))

    def _set_icon(self):
        icon_file = RESOURCES / 'assets' / 'icon.png'
        if icon_file.exists():
            try:
                self._icon_img = tk.PhotoImage(file=str(icon_file))
                self.iconphoto(True, self._icon_img)
            except tk.TclError:
                pass

    @staticmethod
    def _read_theme_preferences():
        if PREFS.is_file():
            try:
                saved = json.loads(PREFS.read_text(encoding='utf-8')).get('theme')
                if saved is not None:
                    resolved = resolve_theme(saved)
                    return {name: resolved[name] for name in DEFAULT_THEME}
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                pass
        return DEFAULT_THEME.copy()

    @staticmethod
    def _activate_palette(colors):
        """Change runtime colors so newly opened dialogs inherit the active theme."""
        global BG, SURFACE, SURFACE2, ENTRY, FG, MUTED, ACCENT, EDGE, HOVER, SELECT
        global STATUS_DOT_ON, STATUS_DOT_OFF, STATUS_DOT_IDLE
        pal = resolve_theme(colors)
        BG = SURFACE = SURFACE2 = ENTRY = pal['background']
        FG, MUTED, ACCENT = pal['foreground'], pal['muted'], pal['accent']
        EDGE, HOVER, SELECT = pal['edge'], pal['hover'], pal['select']
        STATUS_DOT_ON, STATUS_DOT_OFF, STATUS_DOT_IDLE = pal['dot_on'], BG, ACCENT
        return pal

    def _save_theme_preferences(self):
        """Persist appearance even while analysis form contains incomplete inputs."""
        try:
            existing = json.loads(PREFS.read_text(encoding='utf-8')) if PREFS.exists() else {}
            if not isinstance(existing, dict):
                existing = {}
            existing['theme'] = self.theme_choice.copy()
            PREFS.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
        except (OSError, ValueError, TypeError):
            # Theme still applies for this session if the home folder is read-only.
            pass

    def set_theme(self, colors):
        """Apply color changes to all visible widgets without restarting a run."""
        resolved = resolve_theme(colors)
        new_colors = {name: resolved[name] for name in DEFAULT_THEME}
        old = {
            'foreground': FG, 'background': BG, 'accent': ACCENT,
            'muted': MUTED, 'edge': EDGE, 'hover': HOVER, 'select': SELECT,
            'dot_on': STATUS_DOT_ON,
        }
        self.theme_choice = new_colors
        self._activate_palette(new_colors)
        self.configure(bg=BG)
        self.style_widgets()
        self._recolor_native(self, old)
        self._save_theme_preferences()

    def _recolor_native(self, widget, previous):
        """ttk widgets follow styles; explicitly drawn Tk widgets need updating."""
        map_colors = {
            previous['foreground'].lower(): FG,
            previous['muted'].lower(): MUTED,
            previous['accent'].lower(): ACCENT,
            previous['background'].lower(): BG,
            previous['edge'].lower(): EDGE,
            previous['dot_on'].lower(): STATUS_DOT_ON,
        }
        # Handle viewers specially so their rendered tree lines get redrawn.
        if isinstance(widget, TreeViewer):
            widget.update_theme(resolve_theme(self.theme_choice))
            return
        if isinstance(widget, TickCheckbutton):
            widget.set_theme(BG, FG, MUTED, EDGE)
            return
        if isinstance(widget, tk.Toplevel) or isinstance(widget, tk.Frame):
            if not isinstance(widget, ttk.Widget):
                widget.configure(bg=EDGE if getattr(widget, '_theme_border', False) else BG)
        elif isinstance(widget, tk.Label):
            if not getattr(widget, '_theme_swatch', False):
                previous_fg = str(widget.cget('fg')).lower()
                foreground = map_colors.get(previous_fg, FG)
                widget.configure(bg=BG, fg=foreground)
        elif isinstance(widget, tk.Listbox):
            widget.configure(bg=BG, fg=FG, selectbackground=SELECT, selectforeground=FG)
        elif isinstance(widget, tk.Text):
            widget.configure(bg=BG, fg=FG, insertbackground=FG,
                             selectbackground=SELECT, selectforeground=FG)
            if widget is getattr(self, 'log_text', None):
                widget.tag_configure('system', foreground=ACCENT)
                widget.tag_configure('warn', foreground=MUTED)
                widget.tag_configure('error', foreground=FG)
        elif isinstance(widget, tk.Canvas):
            widget.configure(bg=BG)
        for child in widget.winfo_children():
            self._recolor_native(child, previous)

    def open_theme_dialog(self):
        if self.theme_dialog is not None and self.theme_dialog.winfo_exists():
            self.theme_dialog.lift()
            self.theme_dialog.focus_set()
            return
        dialog = tk.Toplevel(self)
        self.theme_dialog = dialog
        dialog.title('색상 설정')
        dialog.geometry('510x360')
        dialog.minsize(455, 340)
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        panel_border = tk.Frame(dialog, bg=EDGE, padx=1, pady=1)
        panel_border._theme_border = True
        panel_border.grid(row=0, column=0, sticky='nsew')
        panel = ttk.Frame(panel_border, padding=20)
        panel.pack(fill='both', expand=True)
        panel.columnconfigure(2, weight=1)
        ttk.Label(panel, text='GUI 색상 설정', font=('Segoe UI Semibold', 17)).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 8))
        ttk.Label(panel, text='색상표 또는 HEX 코드로 선택하면 화면에 바로 반영됩니다.', style='Muted.TLabel').grid(row=1, column=0, columnspan=4, sticky='w', pady=(0, 16))
        labels = {'foreground': '글자색', 'background': '배경색', 'accent': '강조색'}
        values = {key: tk.StringVar(dialog, value=self.theme_choice[key]) for key in labels}
        swatches = {}
        pending = [None]

        def render_swatches():
            for key, sample in swatches.items():
                try:
                    sample.configure(bg=normalize_hex(values[key].get()))
                except ValueError:
                    pass

        def apply_values(show_error=False):
            try:
                choice = {key: normalize_hex(var.get()) for key, var in values.items()}
                self.set_theme(choice)
                render_swatches()
                return True
            except (ValueError, TypeError, KeyError) as exc:
                if show_error:
                    messagebox.showerror('색상 입력 오류', str(exc), parent=dialog)
                return False

        def on_edit(*_):
            render_swatches()
            if pending[0] is not None:
                dialog.after_cancel(pending[0])
            # Defer until text edit is complete, and avoid applying partial hex values.
            pending[0] = dialog.after_idle(lambda: apply_values())

        def pick_color(key):
            current = values[key].get()
            try:
                current = normalize_hex(current)
            except ValueError:
                current = self.theme_choice[key]
            picked = colorchooser.askcolor(color=current, title=labels[key], parent=dialog)[1]
            if picked:
                values[key].set(normalize_hex(picked))
                apply_values()

        for row, (key, caption) in enumerate(labels.items(), start=2):
            ttk.Label(panel, text=caption).grid(row=row, column=0, sticky='w', pady=8, padx=(0, 14))
            sample = tk.Label(panel, text=' ', width=4, bg=self.theme_choice[key], relief='solid', bd=1)
            sample._theme_swatch = True
            sample.grid(row=row, column=1, sticky='w', padx=(0, 12))
            swatches[key] = sample
            ttk.Entry(panel, textvariable=values[key], width=13).grid(row=row, column=2, sticky='ew', pady=8)
            ttk.Button(panel, text='색상 선택', command=lambda k=key: pick_color(k)).grid(row=row, column=3, padx=(10, 0), pady=8)
        for var in values.values():
            var.trace_add('write', on_edit)

        bar = ttk.Frame(panel)
        bar.grid(row=5, column=0, columnspan=4, sticky='ew', pady=(22, 0))
        ttk.Button(bar, text='기본색 복원', command=lambda: [values[k].set(v) for k, v in DEFAULT_THEME.items()]).pack(side='left')
        ttk.Button(bar, text='닫기', command=dialog.destroy).pack(side='right', padx=(8, 0))
        ttk.Button(bar, text='적용', style='Accent.TButton', command=lambda: apply_values(True)).pack(side='right')
        dialog.bind('<Return>', lambda _e: apply_values(True))
        dialog.bind('<Escape>', lambda _e: dialog.destroy())
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)

    def style_widgets(self):
        s = ttk.Style(self)
        try: s.theme_use('clam')
        except tk.TclError: pass
        # Tk uses system listboxes for ttk combobox popups on some platforms.
        self.option_add('*TCombobox*Listbox.background', BG)
        self.option_add('*TCombobox*Listbox.foreground', FG)
        self.option_add('*TCombobox*Listbox.selectBackground', SELECT)
        self.option_add('*TCombobox*Listbox.selectForeground', FG)
        self.option_add('*Text.selectBackground', SELECT)
        self.option_add('*Text.selectForeground', FG)
        s.configure('.', font=FONT, background=BG, foreground=FG)
        s.configure('TFrame', background=BG)
        s.configure('Card.TFrame', background=SURFACE)
        s.configure('TLabel', background=BG, foreground=FG)
        s.configure('Muted.TLabel', background=BG, foreground=MUTED)
        s.configure('Heading.TLabel', background=SURFACE, foreground=FG, font=('Segoe UI Semibold', 12))
        s.configure('Card.TLabel', background=SURFACE, foreground=FG)
        s.configure('CardMuted.TLabel', background=SURFACE, foreground=MUTED)
        s.configure('TLabelframe', background=SURFACE, bordercolor=EDGE, borderwidth=1, relief='solid')
        s.configure('TLabelframe.Label', background=SURFACE, foreground=FG, font=('Segoe UI Semibold', 12))
        s.configure('TEntry', foreground=FG, fieldbackground=ENTRY, insertcolor=FG,
                    bordercolor=EDGE, lightcolor=EDGE, darkcolor=EDGE, padding=(9, 7),
                    selectbackground=SELECT, selectforeground=FG)
        s.map('TEntry', fieldbackground=[('disabled', BG), ('readonly', BG)],
              foreground=[('disabled', FG), ('readonly', FG)])
        s.configure('TCombobox', fieldbackground=ENTRY, foreground=FG, background=SURFACE2,
                    arrowcolor=FG, padding=(6, 6), bordercolor=EDGE, selectbackground=SELECT,
                    selectforeground=FG)
        s.map('TCombobox', fieldbackground=[('readonly', ENTRY), ('disabled', ENTRY)],
              foreground=[('readonly', FG), ('disabled', FG)],
              selectbackground=[('readonly', SELECT)],
              selectforeground=[('readonly', FG)],
              background=[('active', HOVER), ('readonly', BG)],
              arrowcolor=[('active', FG), ('disabled', FG)])
        s.configure('TButton', padding=(12, 8), background=BG, foreground=FG,
                    bordercolor=EDGE, font=('Segoe UI Semibold', 11))
        s.map('TButton', background=[('pressed', HOVER), ('active', HOVER), ('disabled', BG)],
              foreground=[('active', FG), ('disabled', FG)])
        s.configure('Accent.TButton', background=BG, foreground=FG, bordercolor=FG,
                    padding=(18, 10), font=('Segoe UI Semibold', 12))
        s.map('Accent.TButton', background=[('pressed', HOVER), ('active', HOVER), ('disabled', BG)],
              foreground=[('active', FG), ('disabled', FG)])
        s.configure('Danger.TButton', background=BG, foreground=FG, bordercolor=FG)
        s.map('Danger.TButton', background=[('pressed', HOVER), ('active', HOVER)])
        s.configure('TCheckbutton', background=BG, foreground=FG, padding=(0, 3))
        s.map('TCheckbutton', background=[('active', BG), ('disabled', BG)],
              foreground=[('active', FG), ('disabled', FG)])
        s.configure('TRadiobutton', background=BG, foreground=FG, padding=(0, 3))
        s.map('TRadiobutton', background=[('active', BG), ('disabled', BG)],
              foreground=[('active', FG), ('disabled', FG)])
        s.configure('TNotebook', background=BG, borderwidth=0)
        s.configure('TNotebook.Tab', padding=(18, 12), background=BG, foreground=FG)
        s.map('TNotebook.Tab', background=[('selected', HOVER), ('active', HOVER)],
              foreground=[('selected', FG), ('active', FG)])
        s.configure('Treeview', background=ENTRY, fieldbackground=ENTRY, foreground=FG,
                    rowheight=34, bordercolor=EDGE)
        s.configure('Treeview.Heading', background=BG, foreground=FG,
                    font=('Segoe UI Semibold', 11))
        s.map('Treeview', background=[('selected', SELECT)], foreground=[('selected', FG)])
        s.configure('TScrollbar', background=BG, troughcolor=BG, bordercolor=EDGE,
                    arrowcolor=FG, lightcolor=BG, darkcolor=BG)
        s.map('TScrollbar', background=[('active', HOVER), ('pressed', SELECT)])
        s.configure('TScale', background=BG, troughcolor=HOVER)

    def tick_checkbutton(self, parent, **options):
        return TickCheckbutton(parent, background=BG, foreground=FG, muted=MUTED,
                               outline=EDGE, font=FONT, **options)

    def _cancel_status_blink(self):
        job = getattr(self, 'status_blink_job', None)
        if job is not None:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        self.status_blink_job = None

    def _set_status_dot(self, color):
        if self.status_dot_label is not None:
            self.status_dot_label.configure(fg=color)

    def _blink_status_dot(self):
        if not self.is_running:
            self.status_blink_job = None
            self._set_status_dot(STATUS_DOT_IDLE)
            return
        self._set_status_dot(STATUS_DOT_ON if self._status_dot_phase else STATUS_DOT_OFF)
        self._status_dot_phase = not self._status_dot_phase
        self.status_blink_job = self.after(600, self._blink_status_dot)

    def _start_status_blink(self):
        self._cancel_status_blink()
        self._status_dot_phase = True
        self._blink_status_dot()

    def _stop_status_blink(self, color=STATUS_DOT_IDLE):
        self._cancel_status_blink()
        self._set_status_dot(color)

    def ui_vars(self):
        defaults = AnalysisConfig().to_dict()
        for key, val in defaults.items():
            if isinstance(val, bool): self.vars[key] = tk.BooleanVar(value=val)
            else: self.vars[key] = tk.StringVar(value=str(val))
        self.backend = tk.StringVar(value='Windows')
        self.binary = tk.StringVar(value='')
        self.distro = tk.StringVar(value='')
        self.status = tk.StringVar(value='준비됨')
        self.run_summary = tk.StringVar(value='분석을 시작하면 여기에 진행 정보가 표시됩니다.')
        self.version_label = tk.StringVar(value='IQ-TREE 2 실행 파일을 선택하십시오.')

    def build_ui(self):
        header = tk.Frame(self, bg=BG)
        self.header = header
        header.pack(side='top', fill='x', padx=18, pady=(8, 4))
        # Right status first so it never gets clipped by the title/subtitle.
        sbox = tk.Frame(header, bg=SURFACE, padx=8, pady=4)
        sbox.pack(side='right', padx=(10, 0))
        self.status_dot_label = tk.Label(sbox, text='●', font=('Segoe UI', 14), fg=STATUS_DOT_IDLE, bg=SURFACE)
        self.status_dot_label.pack(side='left', padx=(0, 8))
        tk.Label(sbox, textvariable=self.status, font=('Segoe UI Semibold', 11), fg=FG, bg=SURFACE).pack(side='left')
        titlebox = tk.Frame(header, bg=BG)
        titlebox.pack(side='left')
        tk.Label(titlebox, text='IQ-TREE', font=('Segoe UI Semibold', 24), fg=FG, bg=BG).pack(side='left')
        tk.Label(titlebox, text=' 2 ', font=('Segoe UI Semibold', 24), fg=ACCENT, bg=BG).pack(side='left')
        tk.Label(titlebox, text='GUI', font=('Segoe UI', 20), fg=MUTED, bg=BG).pack(side='left')
        self.header_subtitle = ttk.Label(header, text='ML PHYLOGENY WORKSPACE  ·  Windows / WSL', style='Muted.TLabel')
        # The footer MUST be created and packed before the notebook. The
        # notebook gets remaining height and is the only shrinking element.
        self.build_footer()
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(side='top', fill='both', expand=True, padx=18, pady=(0, 5))
        self.settings_scroll = ScrollableFrame(self.notebook)
        self.notebook.add(self.settings_scroll, text='  분석 설정  ')
        self.log_frame = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(self.log_frame, text='  실행 로그  ')
        self.results_frame = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(self.results_frame, text='  결과 파일  ')
        self.build_setup(self.settings_scroll.inner)
        self.build_log_tab()
        self.build_results_tab()

    def section(self, parent, title):
        box = ttk.Labelframe(parent, text='  ' + title + '  ', padding=(18, 14, 18, 15))
        box.pack(fill='x', pady=(0, 16))
        box.columnconfigure(1, weight=1)
        return box

    def field(self, container, row, label, name, browse=None, note=None):
        ttk.Label(container, text=label, style='Card.TLabel').grid(row=row, column=0, sticky='w', padx=(0, 18), pady=7)
        e = ttk.Entry(container, textvariable=self.vars[name])
        e.grid(row=row, column=1, sticky='ew', pady=7)
        if browse:
            ttk.Button(container, text='찾아보기', command=browse).grid(row=row, column=2, padx=(9, 0), pady=7)
        if note:
            ttk.Label(container, text=note, style='CardMuted.TLabel').grid(row=row+1, column=1, sticky='w')
        return e

    def build_setup(self, root):
        # Two-column canvas content; cards rearrange naturally when horizontal space narrows.
        inputbox = self.section(root, '01  Input & Output')
        self.field(inputbox, 0, 'Alignment', 'alignment', self.browse_alignment)
        self.field(inputbox, 1, 'Output folder', 'output_dir', self.browse_output)
        self.field(inputbox, 2, 'Analysis name', 'prefix')
        self.field(inputbox, 3, 'Partition file', 'partitions', self.browse_partitions)
        ttk.Label(inputbox, text='Partition scheme', style='Card.TLabel').grid(row=4, column=0, sticky='w', pady=7)
        pcombo = ttk.Combobox(inputbox, textvariable=self.vars['partition_scheme'], state='readonly', width=36, values=['proportional', 'equal', 'unlinked'])
        pcombo.grid(row=4, column=1, sticky='w', pady=7)
        ttk.Label(inputbox, text='proportional = -p  |  equal = -q  |  unlinked = -Q', style='CardMuted.TLabel').grid(row=5, column=1, sticky='w', pady=(0, 5))

        engine = self.section(root, '02  IQ-TREE 2 Engine')
        erow = ttk.Frame(engine, style='Card.TFrame')
        erow.grid(row=0, column=0, columnspan=3, sticky='ew', pady=4)
        ttk.Label(erow, text='실행 환경', style='Card.TLabel').pack(side='left', padx=(0, 20))
        ttk.Radiobutton(erow, text='Windows 실행 파일', variable=self.backend, value='Windows', command=self.on_mode_change).pack(side='left', padx=(0, 25))
        ttk.Radiobutton(erow, text='WSL2 (Ubuntu 등)', variable=self.backend, value='WSL', command=self.on_mode_change).pack(side='left')
        ttk.Label(engine, text='Binary / command', style='Card.TLabel').grid(row=1, column=0, sticky='w', padx=(0, 18), pady=7)
        self.binary_entry = ttk.Entry(engine, textvariable=self.binary)
        self.binary_entry.grid(row=1, column=1, sticky='ew', pady=7)
        self.binary_browse_btn = ttk.Button(engine, text='찾아보기', command=self.browse_binary)
        self.binary_browse_btn.grid(row=1, column=2, padx=(9, 0), pady=7)
        ttk.Label(engine, text='WSL distro', style='Card.TLabel').grid(row=2, column=0, sticky='w', pady=7)
        self.distro_combo = ttk.Combobox(engine, textvariable=self.distro, values=wsl_distributions())
        self.distro_combo.grid(row=2, column=1, sticky='ew', pady=7)
        ttk.Button(engine, text='자동 탐색', command=self.auto_detect).grid(row=2, column=2, padx=(9, 0), pady=7)
        ttk.Label(engine, textvariable=self.version_label, style='CardMuted.TLabel', wraplength=880).grid(row=3, column=0, columnspan=3, sticky='w', pady=(5, 4))

        model = self.section(root, '03  Evolutionary Model')
        modes = [
            ('ModelFinder + ML tree  (MFP)', 'MFP'),
            ('ModelFinder only  (MF)', 'MF'),
            ('Fixed model', 'CUSTOM'),
        ]
        for i, (label, value) in enumerate(modes):
            ttk.Radiobutton(model, text=label, variable=self.vars['model_mode'], value=value, command=self.on_model_change).grid(row=i, column=0, columnspan=3, sticky='w', pady=3)
        ttk.Label(model, text='Fixed model', style='Card.TLabel').grid(row=3, column=0, sticky='w', pady=(12, 5), padx=(0, 18))
        self.custom_model_entry = ttk.Entry(model, textvariable=self.vars['fixed_model'])
        self.custom_model_entry.grid(row=3, column=1, sticky='ew', pady=(12, 5))
        ttk.Label(model, text='예: GTR+F+I+G4, HKY+G4', style='CardMuted.TLabel').grid(row=3, column=2, sticky='w', padx=(12, 0), pady=(12, 5))
        self.merge_check = self.tick_checkbutton(model, text='ModelFinder에서 partition 병합 후보도 탐색  (+MERGE)', variable=self.vars['merge_partitions'])
        self.merge_check.grid(row=4, column=0, columnspan=3, sticky='w', pady=(6, 9))
        ttk.Label(model, text='Sequence type', style='Card.TLabel').grid(row=5, column=0, sticky='w')
        self.seq_combo = ttk.Combobox(model, textvariable=self.vars['seq_type'], values=['AUTO', 'DNA', 'AA', 'CODON', 'CODON5', 'BIN', 'MORPH'], state='readonly', width=17)
        self.seq_combo.grid(row=5, column=1, sticky='w')
        ttk.Label(model, text='CODON5 = 무척추동물 미토콘드리아 유전암호', style='CardMuted.TLabel').grid(row=6, column=1, sticky='w', pady=(5, 0))

        support = self.section(root, '04  Branch Support')
        ttk.Label(support, text='Bootstrap', style='Card.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 18), pady=5)
        r = ttk.Frame(support, style='Card.TFrame')
        r.grid(row=0, column=1, columnspan=2, sticky='w')
        for value, title in [('UFBoot', 'Ultrafast  (-B)'), ('Standard', 'Standard  (-b)'), ('None', '없음')]:
            ttk.Radiobutton(r, text=title, variable=self.vars['support_mode'], value=value, command=self.on_boot_change).pack(side='left', padx=(0, 16))
        ttk.Label(support, text='Replicates', style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=8)
        self.bootstrap_entry = ttk.Entry(support, textvariable=self.vars['bootstrap_reps'], width=13)
        self.bootstrap_entry.grid(row=1, column=1, sticky='w', pady=8)
        self.bnni_check = self.tick_checkbutton(support, text='BNNI 보정 적용  (--bnni)', variable=self.vars['bnni'])
        self.bnni_check.grid(row=1, column=2, sticky='w', pady=8)
        self.alrt_check = self.tick_checkbutton(support, text='SH-aLRT  (--alrt)', variable=self.vars['alrt'])
        self.alrt_check.grid(row=2, column=0, sticky='w', pady=8)
        ttk.Entry(support, textvariable=self.vars['alrt_reps'], width=13).grid(row=2, column=1, sticky='w', pady=8)
        ttk.Label(support, text='UFBoot 기본 1000회  •  SH-aLRT 기본 1000회  •  BNNI는 필요할 때만 활성화', style='CardMuted.TLabel').grid(row=3, column=0, columnspan=3, sticky='w', pady=(4, 0))

        adv = self.section(root, '05  Performance & Advanced')
        ttk.Label(adv, text='CPU threads', style='Card.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 18), pady=6)
        ttk.Combobox(adv, textvariable=self.vars['threads'], values=['AUTO', '1', '2', '4', '8', '12', '16', '24', '32'], width=15).grid(row=0, column=1, sticky='w', pady=6)
        ttk.Label(adv, text='Random seed', style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=6)
        ttk.Entry(adv, textvariable=self.vars['seed'], width=17).grid(row=1, column=1, sticky='w', pady=6)
        ttk.Label(adv, text='Outgroup taxa', style='Card.TLabel').grid(row=2, column=0, sticky='w', padx=(0, 18), pady=7)
        self.outgroup_entry = ttk.Entry(adv, textvariable=self.vars['outgroup'])
        self.outgroup_entry.grid(row=2, column=1, sticky='ew', pady=7)
        ttk.Button(adv, text='Alignment에서 선택', command=self.choose_outgroups).grid(row=2, column=2, sticky='w', padx=(9, 0), pady=7)
        ttk.Label(adv, text='선택한 분류군은 쉼표로 구분해 IQ-TREE -o 옵션에 전달됩니다.',
                  style='CardMuted.TLabel').grid(row=3, column=1, columnspan=2, sticky='w', pady=(0, 5))
        self.tick_checkbutton(adv, text='기존 결과 무시하고 새 분석 시작 (--redo)', variable=self.vars['redo']).grid(row=4, column=0, columnspan=3, sticky='w', pady=(7, 12))
        self.field(adv, 5, 'Extra options', 'extra')
        ttk.Label(adv, text='예: --safe --keep-ident  ·  추가 옵션은 고급 사용자용이며 shell을 거치지 않습니다.', style='CardMuted.TLabel').grid(row=6, column=1, columnspan=2, sticky='w', pady=(0, 5))

        preview = self.section(root, '06  Command Preview')
        wrap = ttk.Frame(preview, style='Card.TFrame')
        wrap.grid(row=0, column=0, columnspan=3, sticky='ew')
        wrap.columnconfigure(0, weight=1)
        self.preview = tk.Text(wrap, height=4, wrap='word', bg=ENTRY, fg=FG, insertbackground=FG, relief='flat', font=('Consolas', 11), padx=12, pady=12, state='disabled')
        self.preview.grid(row=0, column=0, sticky='ew')
        ttk.Button(wrap, text='명령어 복사', command=self.copy_command).grid(row=0, column=1, sticky='ns', padx=(10, 0))
        preview.columnconfigure(0, weight=1)
        ttk.Label(preview, text='참고: WSL 모드의 표시 명령은 경로 변환 전 예시이며, 실제 실행 명령은 실행 로그에 기록됩니다.', style='CardMuted.TLabel').grid(row=1, column=0, columnspan=3, sticky='w', pady=(8, 0))

    def build_log_tab(self):
        top = ttk.Frame(self.log_frame)
        top.pack(fill='x', pady=(0, 12))
        ttk.Label(top, text='Live analysis log', font=('Segoe UI Semibold', 17)).pack(side='left')
        ttk.Button(top, text='로그 복사', command=self.copy_log).pack(side='right', padx=4)
        ttk.Button(top, text='로그 저장', command=self.save_log).pack(side='right', padx=4)
        ttk.Label(self.log_frame, textvariable=self.run_summary, style='Muted.TLabel').pack(anchor='w', pady=(0, 12))
        frame = ttk.Frame(self.log_frame)
        frame.pack(fill='both', expand=True)
        self.log_text = tk.Text(frame, bg=BG, fg=FG, insertbackground=FG, font=('Consolas', 11), relief='flat', wrap='none', undo=False, padx=18, pady=16)
        v = ttk.Scrollbar(frame, orient='vertical', command=self.log_text.yview)
        h = ttk.Scrollbar(frame, orient='horizontal', command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=v.set, xscrollcommand=h.set)
        self.log_text.grid(row=0, column=0, sticky='nsew')
        v.grid(row=0, column=1, sticky='ns')
        h.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.log_text.tag_configure('system', foreground=ACCENT)
        self.log_text.tag_configure('error', foreground=FG)
        self.log_text.tag_configure('warn', foreground=MUTED)
        self.log_text.configure(state='disabled')

    def build_results_tab(self):
        bar = ttk.Frame(self.results_frame)
        bar.pack(fill='x', pady=(0, 14))
        ttk.Label(bar, text='Output files', font=('Segoe UI Semibold', 17)).pack(side='left')
        ttk.Button(bar, text='결과 폴더 열기', command=self.open_output).pack(side='right', padx=4)
        ttk.Button(bar, text='파일 목록 새로고침', command=self.refresh_results).pack(side='right', padx=4)
        ttk.Label(self.results_frame, text='파일을 더블클릭하여 열거나 .treefile을 선택하고 트리 미리보기를 실행하십시오.', style='Muted.TLabel').pack(anchor='w', pady=(0, 14))
        self.files_tree = ttk.Treeview(self.results_frame, columns=('name', 'size', 'description'), show='headings', selectmode='browse')
        for col, title, size in [('name', '파일', 370), ('size', '크기', 100), ('description', '설명', 340)]:
            self.files_tree.heading(col, text=title)
            self.files_tree.column(col, width=size, minwidth=80)
        self.files_tree.pack(fill='both', expand=True)
        self.files_tree.bind('<Double-1>', lambda e: self.open_selected_result())
        buttons = ttk.Frame(self.results_frame)
        buttons.pack(fill='x', pady=(15, 0))
        ttk.Button(buttons, text='선택 파일 열기', command=self.open_selected_result).pack(side='left', padx=(0, 10))
        ttk.Button(buttons, text='트리 미리보기 + SVG', command=self.preview_tree).pack(side='left', padx=(0, 10))
        ttk.Button(buttons, text='실행 보고서 열기', command=self.open_report).pack(side='left')
        self.result_summary = ttk.Label(self.results_frame, text='분석 후 결과가 자동으로 표시됩니다.', style='Muted.TLabel')
        self.result_summary.pack(anchor='w', pady=(18, 0))

    def build_footer(self):
        self.footer = ttk.Frame(self, padding=(18, 6, 18, 8))
        self.footer.pack(side='bottom', fill='x')
        self.footer_left = ttk.Frame(self.footer)
        self.footer_right = ttk.Frame(self.footer)
        aux = [
            ('예제 불러오기', self.load_example),
            ('설정 불러오기', self.import_config),
            ('설정 저장', self.export_config),
            ('색상 설정', self.open_theme_dialog),
            ('공식 홈페이지', lambda: webbrowser.open(DOCS)),
        ]
        self.footer_aux_buttons = []
        for name, command in aux:
            btn = ttk.Button(self.footer_left, text=name, command=command)
            self.footer_aux_buttons.append(btn)
        self.stop_btn = ttk.Button(self.footer_right, text='■ 중지', style='Danger.TButton', command=self.stop_run, state='disabled')
        self.stop_btn.pack(side='right', padx=(7, 0))
        self.start_btn = ttk.Button(self.footer_right, text='▶ 분석 실행', style='Accent.TButton', command=self.start_run)
        self.start_btn.pack(side='right')

    def load_example(self):
        file = RESOURCES / 'examples' / 'synthetic_demo_alignment.fasta'
        if not file.is_file():
            file = BASE / 'examples' / 'synthetic_demo_alignment.fasta'
        if not file.is_file():
            messagebox.showinfo('예제 없음', '예제 FASTA 파일을 찾지 못했습니다. ZIP 배포본에서만 포함되어 있을 수 있습니다.')
            return
        self.vars['outgroup'].set('')
        self.vars['alignment'].set(str(file))
        self.vars['output_dir'].set(str(Path.home() / 'IQTree2_GUI_Results'))
        self.vars['prefix'].set('synthetic_demo_ML')
        self.vars['partitions'].set('')
        self.status.set('예제 FASTA를 불러왔습니다')

    def watch_changes(self):
        keys = list(self.vars.values()) + [self.backend, self.binary, self.distro]
        for var in keys:
            var.trace_add('write', lambda *args: self.after_idle(self.refresh_preview))
        self.vars['alignment'].trace_add('write', lambda *args: self.after_idle(self._fill_defaults))

    def _fill_defaults(self):
        path = self.vars['alignment'].get()
        if not path or not Path(path).is_file(): return
        if not self.vars['output_dir'].get().strip():
            self.vars['output_dir'].set(str(Path(path).parent / 'iqtree_results'))
        if not self.vars['prefix'].get().strip():
            self.vars['prefix'].set(Path(path).stem + '_ML')

    def cfg(self):
        data = {}
        for key, var in self.vars.items():
            value = var.get()
            if key in ('bootstrap_reps', 'alrt_reps'):
                try: value = int(value)
                except (ValueError, TypeError):
                    raise ValueError(f'{key} 항목에는 정수를 입력하십시오.')
            data[key] = value
        return AnalysisConfig.from_dict(data)

    def set_config(self, cfg: AnalysisConfig):
        for key, value in cfg.to_dict().items():
            self.vars[key].set(str(value) if not isinstance(value, bool) else value)
        self.on_model_change()
        self.on_boot_change()

    def browse_alignment(self):
        result = filedialog.askopenfilename(title='정렬된 alignment 선택', filetypes=[('Sequence alignments', '*.fasta *.fas *.fa *.fna *.phy *.phylip *.nex *.nexus *.aln *.txt'), ('All files','*.*')])
        if result:
            if result != self.vars['alignment'].get():
                self.vars['outgroup'].set('')  # Prevent a stale outgroup from a different alignment.
            self.vars['alignment'].set(result)

    def choose_outgroups(self):
        alignment = self.vars['alignment'].get().strip()
        if not alignment or not Path(alignment).is_file():
            messagebox.showinfo('Outgroup 선택', '먼저 Alignment 파일을 불러오십시오.', parent=self)
            return
        try:
            taxa = read_alignment_taxa(alignment)
        except (ValueError, OSError) as ex:
            messagebox.showerror('Outgroup 읽기 오류', str(ex) + '\n\n이름을 직접 입력할 수도 있습니다.', parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title(f'Outgroup 선택  ·  {len(taxa)} taxa')
        dialog.geometry('620x650')
        dialog.minsize(440, 430)
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(dialog, text='Alignment 분류군에서 Outgroup 선택', bg=BG, fg=FG,
                 font=('Segoe UI Semibold', 15)).pack(anchor='w', padx=20, pady=(17, 5))
        tk.Label(dialog, text=f'{Path(alignment).name}  ·  {len(taxa)} taxa   |   클릭할 때마다 선택/해제됩니다.',
                 bg=BG, fg=MUTED, font=FONT, wraplength=570, justify='left').pack(anchor='w', padx=20, pady=(0, 14))
        query = tk.StringVar(master=dialog)
        search = ttk.Entry(dialog, textvariable=query)
        search.pack(fill='x', padx=20, pady=(0, 10))
        body = tk.Frame(dialog, bg=BG)
        body.pack(fill='both', expand=True, padx=20)
        listing = tk.Listbox(body, selectmode=tk.MULTIPLE, bg=BG, fg=FG,
                             selectbackground=SELECT, selectforeground=FG, relief='solid',
                             highlightthickness=0, borderwidth=1, font=FONT,
                             activestyle='none', exportselection=False)
        scrollbar = ttk.Scrollbar(body, command=listing.yview)
        listing.configure(yscrollcommand=scrollbar.set)
        listing.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        chosen = set(x.strip() for x in self.vars['outgroup'].get().split(',') if x.strip() and x.strip() in taxa)
        visible = list(taxa)
        count = tk.StringVar(master=dialog)
        def on_list_select(_=None):
            # Clicking any row toggles it, even when no Ctrl key is pressed.
            # Update only displayed taxa; hidden search results retain their selection.
            for i, taxon in enumerate(visible):
                if listing.selection_includes(i):
                    chosen.add(taxon)
                else:
                    chosen.discard(taxon)
            count.set(f'선택됨: {len(chosen)}개')
        def render(*_):
            nonlocal visible
            visible = [t for t in taxa if query.get().casefold() in t.casefold()]
            listing.delete(0, 'end')
            for i, taxon in enumerate(visible):
                listing.insert('end', taxon)
                if taxon in chosen:
                    listing.selection_set(i)
            count.set(f'선택됨: {len(chosen)}개  ·  표시 중: {len(visible)}개')
        listing.bind('<<ListboxSelect>>', on_list_select)
        query.trace_add('write', render)
        render()
        search.focus_set()
        foot = ttk.Frame(dialog, padding=(20, 14, 20, 18))
        foot.pack(fill='x')
        ttk.Label(foot, textvariable=count, style='Muted.TLabel').pack(side='left')
        ttk.Button(foot, text='선택 초기화', command=lambda: (chosen.clear(), render())).pack(side='left', padx=12)
        ttk.Button(foot, text='취소', command=dialog.destroy).pack(side='right', padx=(9, 0))
        def apply():
            self.vars['outgroup'].set(join_outgroups([x for x in taxa if x in chosen]))
            dialog.destroy()
        ttk.Button(foot, text='적용', style='Accent.TButton', command=apply).pack(side='right')
        dialog.bind('<Escape>', lambda _: dialog.destroy())

    def browse_output(self):
        folder = filedialog.askdirectory(title='결과 저장 폴더 선택')
        if folder: self.vars['output_dir'].set(folder)

    def browse_partitions(self):
        path = filedialog.askopenfilename(title='Partition file 선택', filetypes=[('Partition', '*.nex *.txt *.partition *.part'), ('All files', '*.*')])
        if path: self.vars['partitions'].set(path)

    def browse_binary(self):
        path = filedialog.askopenfilename(title='IQ-TREE 2 실행파일', filetypes=[('Executables','*.exe'),('All files','*.*')])
        if path: self.binary.set(path)

    def on_mode_change(self):
        is_wsl = self.backend.get() == 'WSL'
        self.binary_browse_btn.configure(state='disabled' if is_wsl else 'normal')
        self.distro_combo.configure(state='normal' if is_wsl else 'disabled')
        self.version_label.set('WSL의 iqtree2 명령어 또는 절대 경로를 입력하십시오.' if is_wsl else 'Windows용 iqtree2.exe 경로를 입력하거나 자동 탐색을 누르십시오.')
        self.refresh_preview()

    def auto_detect(self):
        if self.backend.get() == 'Windows':
            choices = available_windows_binaries()
            if choices:
                self.binary.set(choices[0])
                self.version_label.set('감지됨: ' + choices[0])
            else:
                messagebox.showinfo('자동 탐색', 'IQ-TREE 2 실행파일을 자동으로 찾지 못했습니다.\n공식 웹사이트에서 Windows 버전을 내려받은 뒤 iqtree2.exe를 선택하십시오.')
        else:
            distros = wsl_distributions()
            self.distro_combo.configure(values=distros)
            if distros and not self.distro.get():
                self.distro.set(distros[0])
            self.binary.set('iqtree2')
            self.version_label.set('WSL 배포판: ' + (self.distro.get() or '기본 배포판') + '  ·  iqtree2 (실행시 경로 확인)')

    def on_model_change(self):
        mode = self.vars['model_mode'].get()
        self.custom_model_entry.configure(state='normal' if mode == 'CUSTOM' else 'disabled')
        self.merge_check.configure(state='normal' if mode == 'MFP' else 'disabled')
        if mode == 'MF':
            self.vars['support_mode'].set('None')
            self.vars['alrt'].set(False)
            self.vars['bnni'].set(False)
        self.on_boot_change()

    def on_boot_change(self):
        mode = self.vars['support_mode'].get()
        self.bootstrap_entry.configure(state='disabled' if mode == 'None' else 'normal')
        self.bnni_check.configure(state='normal' if mode == 'UFBoot' else 'disabled')
        if mode != 'UFBoot' and self.vars['bnni'].get(): self.vars['bnni'].set(False)
        if mode == 'Standard' and self.vars['bootstrap_reps'].get() == '1000':
            self.vars['bootstrap_reps'].set('100')
        if mode == 'UFBoot' and self.vars['bootstrap_reps'].get() == '100':
            self.vars['bootstrap_reps'].set('1000')

    def _preview_args(self, cfg: AnalysisConfig):
        cfg.validate()
        mode = self.backend.get()
        binary = self.binary.get().strip()
        if mode == 'Windows':
            binary = binary or 'iqtree2.exe'
            cmd = [binary] + cfg.args()
        else:
            # WSL path display is illustrative. Exact WSL conversion happens at run time.
            cmd = ['wsl.exe', '-d', self.distro.get() or '<default>', '--', binary or 'iqtree2'] + cfg.args()
        return command_string(cmd)

    def refresh_preview(self):
        if not hasattr(self, 'preview'): return
        try:
            text = self._preview_args(self.cfg())
        except Exception as e:
            text = '설정 입력 중: ' + str(e)
        self.preview.configure(state='normal')
        self.preview.delete('1.0', 'end')
        self.preview.insert('1.0', text)
        self.preview.configure(state='disabled')

    def copy_command(self):
        text = self.preview.get('1.0', 'end').strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.set('명령어를 복사했습니다')

    def add_log(self, message, tag=None):
        self.log_text.configure(state='normal')
        self.log_text.insert('end', message + ('' if message.endswith('\n') else '\n'), tag or '')
        self.log_text.see('end')
        self.log_text.configure(state='disabled')

    def copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.log_text.get('1.0', 'end'))
        self.status.set('로그를 복사했습니다')

    def save_log(self):
        out = filedialog.asksaveasfilename(initialfile='iqtree_gui_log.txt', defaultextension='.txt', filetypes=[('Text file','*.txt')])
        if out:
            Path(out).write_text(self.log_text.get('1.0', 'end'), encoding='utf-8')

    def import_config(self):
        file = filedialog.askopenfilename(filetypes=[('IQ-TREE GUI preset', '*.json'), ('All files','*.*')])
        if not file: return
        try:
            data = json.loads(Path(file).read_text(encoding='utf-8'))
            self.set_config(AnalysisConfig.from_dict(data.get('analysis', data)))
            self.backend.set(data.get('backend', self.backend.get()))
            self.binary.set(data.get('binary', self.binary.get()))
            self.distro.set(data.get('distro', self.distro.get()))
            self.on_mode_change()
            if 'theme' in data:
                self.set_theme(data['theme'])
            self.status.set('설정을 불러왔습니다')
        except Exception as e: messagebox.showerror('설정 오류', str(e))

    def export_config(self):
        out = filedialog.asksaveasfilename(initialfile='iqtree_profile.json', defaultextension='.json', filetypes=[('JSON', '*.json')])
        if not out: return
        try:
            self.write_config(Path(out))
            self.status.set('설정을 저장했습니다')
        except Exception as e: messagebox.showerror('저장 오류', str(e))

    def write_config(self, path: Path):
        data = {'app_version': APP_VERSION, 'backend': self.backend.get(), 'binary': self.binary.get(), 'distro': self.distro.get(), 'analysis': self.cfg().to_dict(), 'theme': self.theme_choice.copy()}
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    def load_settings(self):
        if PREFS.is_file():
            try:
                data = json.loads(PREFS.read_text(encoding='utf-8'))
                self.set_config(AnalysisConfig.from_dict(data.get('analysis', {})))
                self.backend.set(data.get('backend', 'Windows'))
                self.binary.set(data.get('binary', ''))
                self.distro.set(data.get('distro', ''))
            except (ValueError, OSError, TypeError):
                pass
        if not self.binary.get() and self.backend.get() == 'Windows':
            choices = available_windows_binaries()
            if choices: self.binary.set(choices[0])

    def persist_settings(self):
        try: self.write_config(PREFS)
        except (OSError, ValueError, TypeError): pass

    def _run_worker(self, command, mode, distro):
        self.events.put(('system', '실행 명령: ' + command_string(command)))
        self.events.put(('system', '--------------------------------------------'))
        output_lines = []
        returncode = -1
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    bufsize=1, encoding='utf-8', errors='replace', creationflags=flags)
            self.process = proc
            if self.stop_requested and mode != 'WSL':
                self._terminate_process()
            assert proc.stdout is not None
            for line in proc.stdout:
                if line.startswith('__IQTREE_GUI_PID__='):
                    try:
                        self.wsl_pid = int(line.split('=', 1)[1].strip())
                        if self.stop_requested:
                            stop_wsl_pid(distro, self.wsl_pid)
                    except (ValueError, OSError, subprocess.TimeoutExpired): pass
                    continue
                output_lines.append(line)
                self.events.put(('text', line))
            returncode = proc.wait()
        except Exception as e:
            self.events.put(('error', f'프로세스 실행 오류: {e}'))
        finally:
            try:
                if self.last_log_file:
                    Path(self.last_log_file).write_text(''.join(output_lines), encoding='utf-8')
            except OSError: pass
            self.events.put(('done', returncode))

    def start_run(self):
        if self.is_running: return
        try:
            cfg = self.cfg()
            cfg.validate()
            mode = self.backend.get()
            command, display = build_command(cfg, mode, self.binary.get(), self.distro.get())
            outdir = Path(cfg.output_dir).resolve()
            prefix_path = outdir / cfg.prefix
            found = [str(prefix_path) + suff for suff in ('.treefile', '.iqtree', '.ckp.gz', '.log') if Path(str(prefix_path) + suff).exists()]
            if found and not messagebox.askyesno('기존 분석 발견', '이 이름으로 저장된 이전 분석 파일이 있습니다.\n\n' + '\n'.join(Path(f).name for f in found) + '\n\n계속 진행하시겠습니까? (--redo를 선택하지 않으면 IQ-TREE의 checkpoint 재개 규칙이 적용됩니다.)'):
                return
            outdir.mkdir(parents=True, exist_ok=True)
            self.persist_settings()
            self.write_config(outdir / (cfg.prefix + '.gui_config.json'))
            (outdir / (cfg.prefix + '.gui_command.txt')).write_text(display + '\n', encoding='utf-8')
        except Exception as e:
            messagebox.showerror('실행 설정 오류', str(e))
            return
        self.last_prefix = str(prefix_path)
        self.last_log_file = str(prefix_path) + '.gui_session.log'
        self.is_running = True
        self.stop_requested = False
        self.wsl_pid = None
        self.process = None
        self.start_time = time.monotonic()
        self.backend_command = command
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')
        self.files_tree.delete(*self.files_tree.get_children())
        self.start_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self.status.set('분석 실행 중')
        self._start_status_blink()
        self.run_summary.set(f'{cfg.prefix}  •  {mode}  •  {cfg.model_mode}  •  started')
        self.notebook.select(self.log_frame)
        self.worker = threading.Thread(target=self._run_worker, args=(command, mode, self.distro.get()), daemon=True)
        self.worker.start()

    def stop_run(self):
        if not self.is_running: return
        if not messagebox.askyesno('분석 중지', '진행 중인 분석을 종료하시겠습니까?\n중단된 checkpoint는 저장되어 있을 수 있습니다.'):
            return
        self.stop_requested = True
        self.status.set('중지 요청 중')
        self._stop_status_blink(STATUS_DOT_WARN)
        self.stop_btn.configure(state='disabled')
        self.add_log('[GUI] 분석 중지를 요청했습니다.', 'warn')
        if self.backend.get() == 'WSL':
            if self.wsl_pid:
                pid = self.wsl_pid
                distro = self.distro.get()
                threading.Thread(target=self._stop_wsl_background, args=(distro, pid), daemon=True).start()
            # Otherwise, the reader kills the Linux PID as soon as the launch marker arrives.
        else:
            self._terminate_process()

    def _stop_wsl_background(self, distro, pid):
        try:
            stop_wsl_pid(distro, pid)
        except Exception as ex:
            self.events.put(('warn', f'WSL 프로세스 종료 신호 오류: {ex}'))
        # Allow the Linux-side process to stop first; avoid killing wsl.exe prematurely.
        time.sleep(3)
        self._terminate_process()

    def _terminate_process(self):
        proc = self.process
        if proc and proc.poll() is None:
            try: proc.terminate()
            except OSError: pass

    def poll_events(self):
        try:
            for _ in range(500):
                kind, val = self.events.get_nowait()
                if kind == 'text':
                    if 'ERROR' in val.upper() or 'FATAL' in val.upper(): tag = 'error'
                    elif 'WARNING' in val.upper(): tag = 'warn'
                    else: tag = None
                    self.add_log(val, tag)
                elif kind == 'system': self.add_log('[GUI] ' + val, 'system')
                elif kind == 'error': self.add_log('[GUI] ' + val, 'error')
                elif kind == 'warn': self.add_log('[GUI] ' + val, 'warn')
                elif kind == 'done': self.finish_run(val)
        except queue.Empty:
            pass
        self.after(120, self.poll_events)

    def finish_run(self, code):
        elapsed = time.monotonic() - self.start_time
        self.is_running = False
        self.stop_btn.configure(state='disabled')
        self.start_btn.configure(state='normal')
        if self.stop_requested:
            state = '사용자가 중지함'
            tag = 'warn'
        elif code == 0:
            state = '분석 완료'
            tag = 'system'
        else:
            state = f'실패 (종료 코드 {code})'
            tag = 'error'
        self.status.set(state)
        if self.stop_requested:
            self._stop_status_blink(STATUS_DOT_WARN)
        elif code == 0:
            self._stop_status_blink(STATUS_DOT_IDLE)
        else:
            self._stop_status_blink(STATUS_DOT_ERROR)
        self.run_summary.set(f'{state}  •  {elapsed:.1f}초 소요  •  {Path(self.last_prefix).name}')
        self.add_log(f'[GUI] {state} — 경과 시간 {elapsed:.1f}초', tag)
        self.refresh_results()
        if code == 0 and not self.stop_requested:
            self.notebook.select(self.results_frame)
        self.process = None
        self.wsl_pid = None

    def refresh_results(self):
        self.files_tree.delete(*self.files_tree.get_children())
        prefix = self.last_prefix
        if not prefix:
            try: prefix = str(Path(self.vars['output_dir'].get()) / self.vars['prefix'].get())
            except Exception: return
        base = Path(prefix)
        if not base.parent.is_dir(): return
        filetypes = {
            '.treefile': 'Maximum-likelihood tree (Newick)',
            '.contree': 'Consensus tree (Newick)',
            '.iqtree': 'Analysis report / model information',
            '.log': 'IQ-TREE process log',
            '.ufboot': 'UFBoot tree replicates',
            '.boottrees': 'Standard bootstrap replicates',
            '.ckp.gz': 'Checkpoint for resuming a run',
            '.mldist': 'Pairwise ML distances',
            '.bionj': 'BIONJ starting tree',
            '.gui_config.json': 'GUI parameters (JSON)',
            '.gui_command.txt': 'Reproducible command line',
            '.gui_session.log': 'Captured GUI session log',
        }
        matched = sorted((p for p in base.parent.iterdir() if p.is_file() and p.name.startswith(base.name + '.')),
                         key=lambda p: (0 if p.name.endswith(('.treefile', '.contree', '.iqtree')) else 1, p.name))
        for i, f in enumerate(matched):
            suffix = f.name[len(base.name):]
            kind = next((d for ext, d in filetypes.items() if suffix.endswith(ext)), 'Additional IQ-TREE output')
            size = f'{f.stat().st_size / 1024:.1f} KB' if f.stat().st_size < 1024**2 else f'{f.stat().st_size / 1024**2:.1f} MB'
            self.files_tree.insert('', 'end', iid=str(i), values=(f.name, size, kind), tags=(str(f),))
        self.result_summary.configure(text=f'{len(matched)}개 파일  •  {base.parent}')

    def _selected_result_path(self):
        selected = self.files_tree.selection()
        if not selected: return None
        tags = self.files_tree.item(selected[0], 'tags')
        return tags[0] if tags else None

    def open_selected_result(self):
        path = self._selected_result_path()
        if not path:
            messagebox.showinfo('결과 파일', '파일을 먼저 선택하십시오.')
            return
        try: open_local(path)
        except Exception as e: messagebox.showerror('파일 열기 오류', str(e))

    def preview_tree(self):
        path = self._selected_result_path()
        if not path or not path.lower().endswith(('.treefile', '.contree', '.bionj')):
            if self.last_prefix and Path(self.last_prefix + '.treefile').is_file():
                path = self.last_prefix + '.treefile'
            else:
                path = filedialog.askopenfilename(title='Newick tree 선택', filetypes=[('Newick trees','*.treefile *.contree *.tre *.nwk *.newick'), ('All files','*.*')])
        if not path: return
        try: TreeViewer(self, path)
        except Exception as e: messagebox.showerror('Newick 오류', str(e))

    def open_report(self):
        path = self.last_prefix + '.iqtree'
        if Path(path).is_file():
            try: open_local(path)
            except Exception as e: messagebox.showerror('오류', str(e))
        else: messagebox.showinfo('보고서', '.iqtree 보고서 파일이 아직 없습니다.')

    def open_output(self):
        folder = self.vars['output_dir'].get()
        if folder and Path(folder).is_dir():
            try: open_local(folder)
            except Exception as e: messagebox.showerror('오류', str(e))
        else: messagebox.showinfo('결과 폴더', '저장 폴더가 아직 존재하지 않습니다.')

    def exit_app(self):
        if self.is_running:
            if not messagebox.askyesno('실행 중', '분석이 실행 중입니다. 종료하면 작업 중단이 완전하지 않을 수 있습니다.\n창을 닫으시겠습니까?'):
                return
            self.stop_requested = True
            if self.backend.get() == 'WSL' and self.wsl_pid:
                try: stop_wsl_pid(self.distro.get(), self.wsl_pid)
                except Exception: pass
            self._terminate_process()
        self._stop_status_blink(STATUS_DOT_IDLE)
        self.persist_settings()
        self.destroy()


if __name__ == '__main__':
    enable_high_dpi()
    app = IQTreeGUI()
    app.mainloop()
