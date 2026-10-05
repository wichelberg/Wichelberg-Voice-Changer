"""Arayüz teması: sv-ttk (Windows 11 görünümü, açık/koyu) + durum renkleri tek yerde.

config.json → ui.theme: "system" (Windows'un uygulama temasını izler) | "light" | "dark".
sv-ttk yüklenemezse program çökmez, Windows'un varsayılan ttk temasıyla açılır.
"""

from __future__ import annotations

import ctypes
import tkinter as tk
from tkinter import ttk

SYSTEM, LIGHT, DARK = "system", "light", "dark"

PALETTES = {
    LIGHT: {"ok": "#0f7b0f", "warn": "#9d5d00", "error": "#c42b1c", "muted": "#5f5f5f", "text": "#1c1c1c",
            "card": "#f9f9f9", "log_bg": "#f3f3f3", "accent": "#005fb8"},
    DARK: {"ok": "#6ccb5f", "warn": "#fce100", "error": "#ff99a4", "muted": "#a0a0a0", "text": "#ffffff",
           "card": "#2b2b2b", "log_bg": "#202020", "accent": "#60cdff"},
}

_current = LIGHT


def colors() -> dict:
    return PALETTES[_current]


def color(name: str) -> str:
    return PALETTES[_current][name]


def is_dark() -> bool:
    return _current == DARK


def system_theme() -> str:
    """Windows ayarı: Kişiselleştirme → Renkler → Varsayılan uygulama modu."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return LIGHT if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else DARK
    except OSError:
        return LIGHT


def resolve(choice: str) -> str:
    return system_theme() if choice not in (LIGHT, DARK) else choice


def apply(root: tk.Tk, choice: str) -> str:
    """Temayı uygula; uygulanan gerçek tema (light/dark) döner."""
    global _current
    _current = resolve(choice)
    try:
        import sv_ttk

        sv_ttk.set_theme(_current, root)
        # sv-ttk renkleri <<ThemeChanged>> olayıyla ayarlıyor; Tk 8.6.12'de bu olay kök pencereye gelmiyor
        # (arka planlar gri kalıyordu). Aynı işlemi doğrudan çağır.
        root.tk.call("configure_colors")
    except Exception:  # noqa: BLE001 — tema yoksa varsayılan ttk ile devam
        pass
    _styles(root)
    fix_entry_fonts(root)
    _title_bar(root, _current == DARK)
    return _current


def fix_entry_fonts(widget) -> None:
    """sv-ttk'nin giriş kutusu yazı tipini (aynı olay sorunu nedeniyle) elle uygula."""
    if widget.winfo_class() in ("TEntry", "TCombobox", "TSpinbox"):
        try:
            widget.tk.call("config_entry_font", widget)
        except tk.TclError:
            pass
    for child in widget.winfo_children():
        fix_entry_fonts(child)


def _styles(root: tk.Tk) -> None:
    c = colors()
    style = ttk.Style(root)
    style.configure("Muted.TLabel", foreground=c["muted"])
    style.configure("Warn.TLabel", foreground=c["warn"])
    style.configure("Error.TLabel", foreground=c["error"])
    style.configure("Ok.TLabel", foreground=c["ok"])
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 15))
    style.configure("Section.TLabel", font=("Segoe UI Semibold", 11))
    style.configure("Status.TLabel", font=("Segoe UI Semibold", 13))
    style.configure("Big.Accent.TButton", font=("Segoe UI Semibold", 12), padding=(18, 8))
    style.configure("Big.TButton", font=("Segoe UI", 11), padding=(14, 8))


def _title_bar(root: tk.Tk, dark: bool) -> None:
    """Windows 10/11 başlık çubuğunu temaya uydur (desteklenmiyorsa sessizce geç)."""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (yeni / eski Windows 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                break
    except (AttributeError, OSError):
        pass


def style_text(widget: tk.Text) -> None:
    """tk.Text ttk teması almaz: renkleri elle ver."""
    c = colors()
    widget.config(background=c["log_bg"], foreground=c["text"], insertbackground=c["text"],
                  highlightthickness=0, borderwidth=0)
