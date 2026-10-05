"""Ortak arayüz parçaları."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollFrame(ttk.Frame):
    """Dikey kaydırılabilir alan: içerik `self.body` içine konur. Küçük ekranlarda (laptop, %150 ölçek)
    sekmeler pencereye sığmazsa kaydırma çubuğu çıkar; sığarsa gizlenir."""

    def __init__(self, master, padding=0, fit_width: bool = False, **kwargs):
        """fit_width: genişlik içeriğe göre (sol panel); değilse pencereyle büyür."""
        super().__init__(master, **kwargs)
        self._fit_width = fit_width
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._bar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._bar.grid(row=0, column=1, sticky="ns")
        self._canvas.configure(yscrollcommand=self._bar.set)
        self.body = ttk.Frame(self._canvas, padding=padding)
        self._window = self._canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _e: self._update())
        self._canvas.bind("<Configure>", lambda _e: self._update())
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.restyle()

    def restyle(self) -> None:
        """Tema değişince tuvalin arka planını ttk arka planına eşitle."""
        background = ttk.Style(self).lookup("TFrame", "background") or "#fafafa"
        self._canvas.configure(background=background)

    def _update(self) -> None:
        if self._fit_width and int(self._canvas.cget("width")) != self.body.winfo_reqwidth():
            self._canvas.configure(width=self.body.winfo_reqwidth())
        width = self._canvas.winfo_width()
        self._canvas.itemconfigure(self._window, width=width)
        needed = self.body.winfo_reqheight()
        self._canvas.configure(scrollregion=(0, 0, width, needed))
        if needed > self._canvas.winfo_height() + 1:
            self._bar.grid()
        else:
            self._bar.grid_remove()
            self._canvas.yview_moveto(0)

    def _wheel(self, event) -> None:
        if not self._bar.winfo_ismapped():
            return
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None and widget is not self:
            if isinstance(widget, (ttk.Combobox, tk.Text)):
                return  # açık listeler / metin kutusu kendi kaydırsın
            widget = widget.master
        if widget is self:
            self._canvas.yview_scroll(int(-event.delta / 120), "units")
