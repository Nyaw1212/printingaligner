import json
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "layout.json"
DPI = 75
PAGE_W, PAGE_H = 8.5 * DPI, 11 * DPI

class App:
    def __init__(self, root):
        self.root = root
        root.title("Printing Aligner v1.0")
        root.geometry("1050x900")
        self.bg_path = None
        self.bg_image = None
        self.photo = None
        self.fields = []
        self.active = None
        self.drag = None
        self.build()
        self.load()

    def build(self):
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        for label, command in [("Load Background", self.background), ("Add Text", self.add_field), ("Save Layout", self.save), ("Print PDF", self.export_pdf), ("Update & Restart", self.update)]:
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
        ttk.Entry(side, textvariable=self.font).pack()
        ttk.Button(side, text="Apply", command=self.apply).pack(fill="x", pady=8)
        ttk.Button(side, text="Delete Field", command=self.delete).pack(fill="x")
        ttk.Label(side, text="Drag text to position.\nPDF excludes background.\nCoordinates start top-left.").pack(pady=16)
        self.canvas.bind("<Button-1>", self.select)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))
        self.render()

    def background(self):
        p = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
        if p:
            self.bg_path = p
            self.render()

    def add_field(self):
        f = {"text": "Employee Name", "x": 30.0, "y": 25.0, "size": 12}
        self.fields.append(f)
        self.active = len(self.fields) - 1
        self.sync()
        self.render()

    def sync(self):
        if self.active is None: return
        f = self.fields[self.active]
        self.value.set(f["text"])
        self.x.set(str(round(f["x"], 2)))
        self.y.set(str(round(f["y"], 2)))
        self.font.set(str(f["size"]))

    def apply(self):
        if self.active is None: return
        try:
            f = self.fields[self.active]
            f.update(text=self.value.get(), x=float(self.x.get()), y=float(self.y.get()), size=int(self.font.get()))
            self.render()
        except ValueError:
            messagebox.showerror("Invalid value", "Use numeric coordinates and font size.")

    def delete(self):
        if self.active is not None:
            self.fields.pop(self.active)
            self.active = None
            self.render()

    def render(self):
        c = self.canvas
        c.delete("all")
        self.offset_x, self.offset_y = 45, 25
        x, y = self.offset_x, self.offset_y
        c.create_rectangle(x, y, x + PAGE_W, y + PAGE_H, fill="white", outline="#222")
        self.photo = None
        if self.bg_path and Path(self.bg_path).exists():
            try:
                im = Image.open(self.bg_path).convert("RGB").resize((round(PAGE_W), round(PAGE_H)))
                self.photo = ImageTk.PhotoImage(im)
                c.create_image(x, y, image=self.photo, anchor="nw")
            except Exception as exc:
                messagebox.showwarning("Background", str(exc))
        for i, f in enumerate(self.fields):
            px = x + f["x"] / 25.4 * DPI
            py = y + f["y"] / 25.4 * DPI
            c.create_text(px, py, text=f["text"], anchor="nw", fill="#005ac8" if i == self.active else "#111",
                          font=("Arial", max(1, round(f["size"] * DPI / 72))), tags=(f"field_{i}", "field"))

    def select(self, event):
        items = self.canvas.find_overlapping(event.x-3, event.y-3, event.x+3, event.y+3)
        for item in reversed(items):
            for tag in self.canvas.gettags(item):
                if tag.startswith("field_"):
                    self.active = int(tag.split("_")[1])
                    self.drag = (event.x, event.y)
                    self.sync()
                    self.render()
                    return
        self.active = None
        self.render()

    def move(self, event):
        if self.active is None or self.drag is None: return
        dx, dy = event.x-self.drag[0], event.y-self.drag[1]
        self.fields[self.active]["x"] += dx / DPI * 25.4
        self.fields[self.active]["y"] += dy / DPI * 25.4
        self.drag = (event.x, event.y)
        self.sync()
        self.render()

    def save(self):
        CONFIG.write_text(json.dumps({"background": self.bg_path, "fields": self.fields}, indent=2), encoding="utf-8")
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
        from reportlab.lib.pagesizes import letter
        p = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not p: return
        pdf = pdfcanvas.Canvas(p, pagesize=letter)
        for f in self.fields:
            pdf.setFont("Helvetica", f["size"])
            pdf.drawString(f["x"]/25.4*72, 792-f["y"]/25.4*72-f["size"], f["text"])
        pdf.save()
        messagebox.showinfo("Ready", "Text-only Letter PDF created. Print at Actual Size / 100%.")

    def update(self):
        if not messagebox.askyesno("Update & Restart", "Pull latest code from GitHub and restart?"): return
        script = ROOT / "update_and_restart.py"
        subprocess.Popen([sys.executable, str(script), str(os.getpid())], cwd=ROOT)
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
