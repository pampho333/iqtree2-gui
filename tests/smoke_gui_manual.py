from pathlib import Path
import json
import tempfile
import tkinter as tk
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import IQTreeGUI
from tree_viewer import TreeViewer

app = IQTreeGUI()
app.update()
assert app.theme_choice['background'] == '#000000'
app.set_theme({'foreground': '#E0D98A', 'background': '#161820', 'accent': '#8BCFDD'})
app.update()
assert app.cget('bg') == '#161820'
assert app.log_text.cget('fg') == '#E0D98A'
assert app.settings_scroll.canvas.cget('bg') == '#161820'
assert app.status_dot_label.cget('bg') == '#161820'
assert tk.ttk.Style(app).lookup('TLabel', 'foreground') == '#E0D98A'
# Ensure the settings dialog can be created while the GUI is running.
app.open_theme_dialog()
app.update()
assert app.theme_dialog.winfo_exists()
def entries(widget):
    from tkinter import ttk
    found = [widget] if isinstance(widget, ttk.Entry) else []
    for child in widget.winfo_children():
        found += entries(child)
    return found
color_entry = entries(app.theme_dialog)[0]
color_entry.delete(0, 'end')
color_entry.insert(0, 'AABBCC')
app.update()
assert app.theme_choice['foreground'] == '#AABBCC', app.theme_choice
color_entry.delete(0, 'end')
color_entry.insert(0, 'not-a-color')
app.update()
assert app.theme_choice['foreground'] == '#AABBCC'
# Restore choice to continue checking other controls.
color_entry.delete(0, 'end')
color_entry.insert(0, '#E0D98A')
app.update()
app.theme_dialog.destroy()
app.load_example()
app.update()
assert app.vars['alignment'].get().endswith('.fasta')
with tempfile.TemporaryDirectory() as tmp:
    app.write_config(Path(tmp)/'preset.json')
    saved = json.loads((Path(tmp)/'preset.json').read_text())
    assert saved['theme']['foreground'] == '#E0D98A'
viewer = TreeViewer(app, Path(__file__).resolve().parent.parent / 'examples' / 'demo_only.treefile')
viewer.update()
assert viewer.canvas.cget('bg') == '#161820'
app.set_theme({'foreground': '#FFFFFF', 'background': '#202020', 'accent': '#FFAA00'})
app.update()
assert viewer.canvas.cget('bg') == '#202020'
assert viewer.palette['accent'] == '#FFAA00'
assert viewer.length_tick.normal_fg == '#FFFFFF'
app.is_running = True
app._start_status_blink()
app.update()
assert app.status_dot_label.cget('fg') != '#202020'
app.after(650, app.quit)
app.mainloop()
assert app.status_dot_label.cget('fg') == '#202020', app.status_dot_label.cget('fg')
app.is_running = False
app._stop_status_blink()
viewer.destroy()
app.exit_app()
app2 = IQTreeGUI()
assert app2.theme_choice['foreground'] == '#FFFFFF'
app2.exit_app()
print('GUI theme, dialog, Newick viewer, blinking dot, persistence: PASS')
