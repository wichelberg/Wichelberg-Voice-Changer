"""Ana pencere.

  Basit görünüm:   Ana ekran (durum, Başlat, ses seçimi, cihazlar) + Ses Kütüphanesi
  Gelişmiş görünüm: + solda DSP ses ayarları, Ses stüdyosu sekmesi, ölçümler, AI ayarları

Soldaki ayarlar canlıda ve stüdyoda aynı anda geçerlidir; canlıdayken slider
oynatınca değişiklik anında Discord'a giden sese yansır.
"""

import ctypes
import tkinter as tk
from types import SimpleNamespace
from tkinter import ttk

import sounddevice as sd

from .. import __version__, paths
from .. import settings as config
from ..dsp import VoiceSettings
from ..engine import AudioEngine
from . import theme
from .library_panel import LibraryPanel
from .live_panel import LivePanel
from .studio_panel import StudioPanel
from .voice_panel import VoicePanel
from .widgets import ScrollFrame

SAVE_DELAY_MS = 500
SIMPLE, ADVANCED = "simple", "advanced"
SIZES = {SIMPLE: ((560, 560), (660, 880)), ADVANCED: ((1060, 620), (1220, 900))}  # (en az, ilk açılış)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Wichelberg Voice Changer")   # başlatıcı pencereyi bu başlıkla bulur (launcher/kurulum.py)
        icon = paths.ROOT / "wichelberg.ico"           # sadece release'te var
        if icon.is_file():
            try:
                root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass

        config.ensure_builtin_presets()
        self.config = config.load_config()
        self._save_job = None
        theme.apply(root, self.config["ui"]["theme"])
        settings = config.settings_from_config(self.config)
        self.engine = AudioEngine(settings)

        root.columnconfigure(1, weight=1)
        root.rowconfigure(1, weight=1)
        self._build_header()

        self._left = ScrollFrame(root, padding=(12, 0, 4, 12), fit_width=True)
        self._left.grid(row=1, column=0, sticky="ns")
        self.voice_panel = VoicePanel(self._left.body, settings, self.config["preset"],
                                      on_change=self._settings_changed)
        self.voice_panel.grid(sticky="nsew")

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=1, column=1, sticky="nsew", padx=(8, 12), pady=(0, 12))
        self.live = LivePanel(self.notebook, self.engine, self.config, on_config_change=self._schedule_save,
                              presets=self.voice_panel, open_library=self.open_library,
                              busy_reason=self._live_busy_reason)
        hooks = SimpleNamespace(is_live=lambda: self.engine.running,
                                release_voice=self.live.ai_controls.release_voice,
                                unload_ai=self._unload_ai,
                                voices_changed=self.live.ai_controls.reload_voices,
                                benchmark_applied=self._benchmark_applied)
        self.library = LibraryPanel(self.notebook, self.config, self._schedule_save, hooks)
        self.studio = StudioPanel(self.notebook, get_settings=lambda: self.voice_panel.settings,
                                  set_setting=self.voice_panel.set_value,
                                  is_live=lambda: self.engine.running,
                                  get_ai_options=lambda: self.live.ai_controls.ai_options())
        self.notebook.add(self.live, text="  Ana ekran  ")
        self.notebook.add(self.library, text="  Ses Kütüphanesi  ")
        self.notebook.add(self.studio, text="  Ses stüdyosu  ")

        self._set_view(self.config["ui"]["view"], first=True)
        theme.fix_entry_fonts(root)
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.after(300, self.live.start_if_autostart)

    # ----------------------------------------------------------------- başlık
    def _build_header(self) -> None:
        bar = ttk.Frame(self.root, padding=(16, 12, 12, 10))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, text="Wichelberg Voice Changer", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(bar, text=f"v{__version__}", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=8)
        self._advanced_var = tk.BooleanVar(value=self.config["ui"]["view"] == ADVANCED)
        ttk.Checkbutton(bar, text="Gelişmiş görünüm", variable=self._advanced_var, style="Switch.TCheckbutton",
                        command=lambda: self._set_view(ADVANCED if self._advanced_var.get() else SIMPLE)).grid(
            row=0, column=2, sticky="e", padx=(0, 10))
        self._theme_button = ttk.Button(bar, command=self._toggle_theme)
        self._theme_button.grid(row=0, column=3, sticky="e")
        self._update_theme_button()

    def _update_theme_button(self) -> None:
        self._theme_button.config(text="☀ Açık tema" if theme.is_dark() else "☾ Koyu tema")

    def _toggle_theme(self) -> None:
        choice = theme.LIGHT if theme.is_dark() else theme.DARK
        self.config["ui"]["theme"] = choice
        theme.apply(self.root, choice)
        for panel in (self._left, self.live, self.library, self.studio):
            panel.restyle()
        self._update_theme_button()
        self.library.refresh()
        self._schedule_save()

    def _set_view(self, view: str, first: bool = False) -> None:
        advanced = view == ADVANCED
        self.config["ui"]["view"] = ADVANCED if advanced else SIMPLE
        if advanced:
            self._left.grid()
            self.notebook.add(self.studio)
        else:
            self._left.grid_remove()
            if self.notebook.select() == str(self.studio):
                self.notebook.select(self.live)
            self.notebook.hide(self.studio)
        self.live.set_advanced(advanced)
        (min_w, min_h), (w, h) = SIZES[ADVANCED if advanced else SIMPLE]
        self.root.minsize(min_w, min_h)
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight() - 90  # görev çubuğu
        self.root.update_idletasks()
        if first:  # ekrana sığdır ve ortala
            w, h = min(w, screen_w), min(h, screen_h)
            self.root.geometry(f"{w}x{h}+{(screen_w - w) // 2}+{max(0, (screen_h - h) // 2)}")
        elif self.root.winfo_width() < w:
            self.root.geometry(f"{min(w, screen_w)}x{max(self.root.winfo_height(), min_h)}")
        if not first:
            self._schedule_save()

    # ---------------------------------------------------------------- bağlantı
    def open_library(self) -> None:
        self.notebook.select(self.library)

    def _live_busy_reason(self):
        if self.library.benchmark_running:
            return "Hız testi sürüyor. Bitince (veya Ses Kütüphanesi'nden durdurunca) başlatabilirsin."
        return None

    def _unload_ai(self) -> None:
        self.live.ai_controls.save_speaker_f0()
        self.engine.set_ai(None)

    def _benchmark_applied(self) -> None:
        self.live.ai_controls.ensure_ai_if_selected()

    def _settings_changed(self, settings: VoiceSettings, final: bool) -> None:
        self.engine.update(settings)  # canlıdaysa anında yansır
        self.config["settings"] = settings.to_dict()
        self.config["preset"] = self.voice_panel.preset_name
        self._schedule_save()
        if final and hasattr(self, "studio"):
            self.studio.on_settings_committed()

    def _schedule_save(self) -> None:
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(SAVE_DELAY_MS, self._save)

    def _save(self) -> None:
        self._save_job = None
        config.save_config(self.config)

    def _close(self) -> None:
        self.live.shutdown()  # önce ses: CABLE'a giden akış kapanır → sessizlik
        self.library.stop_benchmark()
        sd.stop()
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save()
        self.root.destroy()


def _enable_dpi_awareness() -> None:
    """Yüksek DPI ekranlarda bulanık olmayan arayüz."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    try:  # görev çubuğunda Python simgesi yerine programın kendi simgesi
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Wichelberg.VoiceChanger")
    except (AttributeError, OSError):
        pass


def _make_root() -> tk.Tk:
    """Sürükle-bırak destekli pencere; tkinterdnd2 yoksa düz tkinter (D14)."""
    try:
        from tkinterdnd2 import TkinterDnD

        return TkinterDnD.Tk()
    except Exception:  # noqa: BLE001
        return tk.Tk()


def main() -> None:
    _enable_dpi_awareness()
    root = _make_root()
    app = None
    try:
        app = App(root)
        root.mainloop()
    finally:
        if app is not None:
            app.engine.stop()  # beklenmedik çıkışta da CABLE'a ses gitmesin
