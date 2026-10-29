import json
import shutil
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser, font as tkfont
from pathlib import Path
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "layout.json"
CACHE_DIR = ROOT / ".cache"
CACHE_BG = CACHE_DIR / "background.png"
DPI = 75
PAGE_W, PAGE_H = 11 * DPI, 8.5 * DPI

class App:
    def __init__(self, root):
        self.root = root
        root.title("Printing Aligner v1.0")
        root.geometry("1200x800")
        try:
            root.state("zoomed")
        except tk.TclError:
            pass
        self.bg_path = None
        self.bg_image = None
        self.photo = None
        self.fields = []
        self.active = None
        self.drag = None
        self.undo_stack = []
        self.redo_stack = []
        self.drag_snapshot = None
        self.scale = DPI
        self.font_families = ["Arial Bold", "Bahnschrift SemiBold", "Arial Black", "Stencil", "Agency FB Bold", "Bahnschrift Light"]
        self.syncing = False
        self.build()
        self.load()
        root.protocol("WM_DELETE_WINDOW", self.close)
        for key, dx, dy in (("Up", 0, -1), ("Down", 0, 1), ("Left", -1, 0), ("Right", 1, 0)):
            root.bind_all("<" + key + ">", lambda e, x=dx, y=dy: self.nudge(e, x, y))
            root.bind_all("<Shift-" + key + ">", lambda e, x=dx, y=dy: self.nudge(e, x, y, fast=True))
        root.bind_all("<Control-z>", self.undo)
        root.bind_all("<Control-y>", self.redo)
        root.bind_all("<Control-Shift-Z>", self.redo)
        root.bind_all("<Control-Shift-z>", self.redo)

    def snapshot(self):
        return json.dumps({"fields": self.fields, "background": self.bg_path, "active": self.active}, sort_keys=True)

    def remember(self, before):
        if before != self.snapshot():
            self.undo_stack.append(before)
            self.undo_stack = self.undo_stack[-100:]
            self.redo_stack.clear()
            self.autosave()

    def restore(self, state):
        data = json.loads(state)
        self.fields = data["fields"]
        self.bg_path = data["background"]
        self.active = data["active"]
        if self.active is not None and self.active < len(self.fields):
            self.sync()
        else:
            self.active = None
            self.syncing = True
            self.value.set("")
            self.syncing = False
        self.drag = None
        self.autosave()
        self.render()

    def undo(self, event=None):
        if self.undo_stack:
            self.redo_stack.append(self.snapshot())
            self.restore(self.undo_stack.pop())
        return "break"

    def redo(self, event=None):
        if self.redo_stack:
            self.undo_stack.append(self.snapshot())
            self.restore(self.redo_stack.pop())
        return "break"

    def nudge(self, event, dx, dy, fast=False):
        # Preserve normal caret and selection movement in editable widgets.
        if isinstance(event.widget, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, ttk.Spinbox, tk.Spinbox)):
            return None
        if self.active is None or not (0 <= self.active < len(self.fields)):
            return None
        before = self.snapshot()
        step = 1.0 if fast else 0.1
        field = self.fields[self.active]
        field["x"] = round(field["x"] + dx * step, 3)
        field["y"] = round(field["y"] + dy * step, 3)
        self.remember(before)
        self.sync()
        self.render()
        return "break"

    def end_drag(self, event=None):
        if self.drag_snapshot is not None:
            self.remember(self.drag_snapshot)
            self.drag_snapshot = None
        self.drag = None

    def build(self):
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        for label, command in [("Load Background", self.background), ("Remove BG", self.remove_background), ("Add Text", self.add_field), ("Save Layout", self.save), ("Undo", self.undo), ("Redo", self.redo), ("Print PDF", self.export_pdf), ("Update & Restart", self.update)]:
            ttk.Button(bar, text=label, command=command).pack(side="left", padx=3)
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg="#777", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        side = ttk.Frame(body, padding=12)
        side.pack(side="right", fill="y")
        ttk.Label(side, text="Selected Text").pack(anchor="w")
        self.value = tk.StringVar()
        ttk.Entry(side, textvariable=self.value, width=27).pack(pady=6)
        ttk.Label(side, text="X (mm)").pack(anchor="w")
        self.x = tk.StringVar()
        ttk.Entry(side, textvariable=self.x).pack()
        ttk.Label(side, text="Y (mm)").pack(anchor="w")
        self.y = tk.StringVar()
        ttk.Entry(side, textvariable=self.y).pack()
        ttk.Label(side, text="Font size (pt)").pack(anchor="w")
        self.font = tk.StringVar(value="12")
        ttk.Combobox(side, textvariable=self.font, values=["8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "32"], width=24).pack()
        ttk.Label(side, text="Font type").pack(anchor="w")
        self.family = tk.StringVar(value="Arial Bold")
        ttk.Combobox(side, textvariable=self.family, values=self.font_families, width=24, state="readonly").pack()
        ttk.Label(side, text="Character spacing (pt)").pack(anchor="w")
        self.spacing = tk.StringVar(value="0")
        ttk.Spinbox(side, from_=-10, to=30, increment=0.25, textvariable=self.spacing, width=24).pack()
        ttk.Label(side, text="Font color").pack(anchor="w")
        self.color = tk.StringVar(value="#000000")
        color_row = ttk.Frame(side)
        color_row.pack(fill="x")
        ttk.Entry(color_row, textvariable=self.color, width=16).pack(side="left")
        ttk.Button(color_row, text="Choose...", command=self.choose_color).pack(side="left", padx=3)
        ttk.Button(side, text="Delete Field", command=self.delete).pack(fill="x")
        ttk.Label(side, text="Drag text to position.\nPDF excludes background.\nCoordinates start top-left.").pack(pady=16)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self.canvas.bind("<Button-1>", self.select)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", self.end_drag)
        for variable in (self.value, self.x, self.y, self.font, self.family, self.spacing, self.color):
            variable.trace_add("write", self.live_apply)
        self.render()

    def live_apply(self, *_):
        if self.syncing or self.active is None:
            return
        try:
            x, y = float(self.x.get()), float(self.y.get())
            size, spacing = int(self.font.get()), float(self.spacing.get())
            color = self.color.get()
            self.root.winfo_rgb(color)
            if size <= 0:
                return
        except (ValueError, tk.TclError):
            return
        before = self.snapshot()
        self.fields[self.active].update(text=self.value.get(), x=x, y=y, size=size,
            family=self.family.get(), color=color, spacing=spacing)
        self.remember(before)
        self.render()

    def choose_color(self):
        result = colorchooser.askcolor(color=self.color.get(), parent=self.root)
        if result[1]:
            self.color.set(result[1])

    def background(self):
        p = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
        if p:
            before = self.snapshot()
            CACHE_DIR.mkdir(exist_ok=True)
            try:
                with Image.open(p) as image:
                    image.convert("RGB").save(CACHE_BG)
                self.bg_path = str(CACHE_BG)
            except Exception as exc:
                messagebox.showerror("Background error", str(exc))
                return
            self.remember(before)
            self.render()

    def remove_background(self):
        if self.bg_path:
            before = self.snapshot()
            self.bg_path = None
            self.remember(before)
            self.render()

    def autosave(self):
        try:
            CONFIG.write_text(json.dumps({"background": self.bg_path, "fields": self.fields}, indent=2), encoding="utf-8")
        except OSError:
            pass

    def close(self):
        self.autosave()
        self.root.destroy()

    def add_field(self):
        before = self.snapshot()
        f = {"text": "Employee Name", "x": 30.0, "y": 25.0, "size": 12, "family": "Arial Bold", "color": "#000000", "spacing": 0.0}
        self.fields.append(f)
        self.remember(before)
        self.active = len(self.fields) - 1
        self.sync()
        self.render()

    def sync(self):
        if self.active is None: return
        f = self.fields[self.active]
        self.syncing = True
        self.value.set(f["text"])
        self.x.set(str(round(f["x"], 2)))
        self.y.set(str(round(f["y"], 2)))
        self.font.set(str(f["size"]))
        self.family.set(f.get("family", "Arial"))
        self.color.set(f.get("color", "#000000"))
        self.spacing.set(str(f.get("spacing", 0)))
        self.syncing = False

    def apply(self):
        if self.active is None: return
        try:
            before = self.snapshot()
            f = self.fields[self.active]
            f.update(text=self.value.get(), x=float(self.x.get()), y=float(self.y.get()), size=int(self.font.get()), family=self.family.get(), color=self.color.get(), spacing=float(self.spacing.get()))
            self.remember(before)
            self.render()
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid value", "Check coordinates, font size, color and spacing.")

    def delete(self):
        if self.active is not None:
            before = self.snapshot()
            self.fields.pop(self.active)
            self.remember(before)
            self.active = None
            self.render()

    def render(self):
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 200)
        self.scale = min((w - 70) / 11, (h - 70) / 8.5)
        pw, ph = 11 * self.scale, 8.5 * self.scale
        self.offset_x, self.offset_y = (w - pw) / 2, (h - ph) / 2
        x, y = self.offset_x, self.offset_y
        c.create_rectangle(x, y, x + pw, y + ph, fill="white", outline="#222")
        self.photo = None
        if self.bg_path and Path(self.bg_path).exists():
            try:
                im = Image.open(self.bg_path).convert("RGB").resize((round(pw), round(ph)))
                self.photo = ImageTk.PhotoImage(im)
                c.create_image(x, y, image=self.photo, anchor="nw")
            except Exception as exc:
                messagebox.showwarning("Background", str(exc))
        for i, f in enumerate(self.fields):
            px = x + f["x"] / 25.4 * self.scale
            py = y + f["y"] / 25.4 * self.scale
            family = f.get("family", "Arial Bold")
            bold = family.endswith(" Bold") or family == "Arial Black" or family == "Bahnschrift SemiBold"
            base_family = family.replace(" Bold", "").replace(" SemiBold", "").replace(" Light", "")
            font_obj = tkfont.Font(family=base_family, weight="bold" if bold else "normal",
                                   size=-max(1, round(f["size"] * self.scale / 72)))
            tracking = float(f.get("spacing", 0)) * self.scale / 72
            color = f.get("color", "#000000")
            cursor = px
            for ch in f["text"]:
                c.create_text(cursor, py, text=ch, anchor="nw", fill=color, font=font_obj,
                              tags=(f"field_{i}", "field"))
                cursor += font_obj.measure(ch) + tracking

    def select(self, event):
        items = self.canvas.find_overlapping(event.x-3, event.y-3, event.x+3, event.y+3)
        for item in reversed(items):
            for tag in self.canvas.gettags(item):
                if tag.startswith("field_"):
                    self.active = int(tag.split("_")[1])
                    self.drag = (event.x, event.y)
                    self.drag_snapshot = self.snapshot()
                    self.sync()
                    self.render()
                    return
        self.active = None
        self.render()

    def move(self, event):
        if self.active is None or self.drag is None: return
        dx, dy = event.x-self.drag[0], event.y-self.drag[1]
        self.fields[self.active]["x"] += dx / self.scale * 25.4
        self.fields[self.active]["y"] += dy / self.scale * 25.4
        self.drag = (event.x, event.y)
        self.sync()
        self.render()

    def save(self):
        self.autosave()
        messagebox.showinfo("Saved", "Layout saved locally.")

    def load(self):
        if CONFIG.exists():
            try:
                data = json.loads(CONFIG.read_text(encoding="utf-8"))
                self.bg_path = data.get("background")
                self.fields = data.get("fields", [])
            except Exception:
                pass
        self.render()

    def export_pdf(self):
        from reportlab.pdfgen import canvas as pdfcanvas
        from reportlab.lib.pagesizes import landscape, letter
        p = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not p: return
        pdf = pdfcanvas.Canvas(p, pagesize=landscape(letter))
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from pathlib import Path
        font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        registered = {}
        for f in self.fields:
            family = f.get("family", "Arial Bold")
            if family not in registered:
                candidate = None
                for name in [family.replace(" ", "") + ".ttf", family.replace(" ", "") .lower() + ".ttf"]:
                    if (font_dir / name).exists():
                        candidate = font_dir / name
                        break
                if candidate is None:
                    aliases = {"Arial Bold": "arialbd.ttf", "Bahnschrift SemiBold": "bahnschrift.ttf", "Bahnschrift Light": "bahnschrift.ttf", "Arial Black": "ariblk.ttf", "Stencil": "STENCIL.TTF", "Agency FB Bold": "AGENCYB.TTF", "Arial": "arial.ttf", "Times New Roman": "times.ttf", "Calibri": "calibri.ttf", "Consolas": "consola.ttf", "Verdana": "verdana.ttf", "Tahoma": "tahoma.ttf", "Georgia": "georgia.ttf"}
                    pfont = font_dir / aliases.get(family, "")
                    if pfont.is_file(): candidate = pfont
                if candidate:
                    try:
                        key = "font_" + str(len(registered))
                        pdfmetrics.registerFont(TTFont(key, str(candidate)))
                        registered[family] = key
                    except Exception:
                        registered[family] = "Helvetica"
                else:
                    registered[family] = "Helvetica"
            pdf.setFont(registered[family], f["size"])
            try:
                pdf.setFillColor(f.get("color", "#000000"))
            except ValueError:
                pdf.setFillColor("#000000")
            obj = pdf.beginText(f["x"]/25.4*72, 612-f["y"]/25.4*72-f["size"])
            obj.setFont(registered[family], f["size"])
            obj.setCharSpace(float(f.get("spacing", 0)))
            obj.textOut(f["text"])
            pdf.drawText(obj)
        pdf.save()
        messagebox.showinfo("Ready", "Text-only Letter PDF created. Print at Actual Size / 100%.")

    def update(self):
        if not messagebox.askyesno("Update & Restart", "Pull latest code from GitHub and restart?"): return
        script = ROOT / "update_and_restart.py"
        self.autosave()
        subprocess.Popen([sys.executable, str(script), str(os.getpid())], cwd=ROOT)
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
