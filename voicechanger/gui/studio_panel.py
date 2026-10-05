"""Ses stüdyosu sekmesi: kayıt al, ayarları dosya üzerinde dene, A/B dinle.

Ağır işler (kayıt, dönüştürme) arka plan iş parçacığında çalışır; sonuçlar
bir kuyruk üzerinden ana (tkinter) iş parçacığına aktarılır. tkinter
widget'larına yalnızca ana iş parçacığından dokunulur.
"""

import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import sounddevice as sd

from .. import paths, recorder, render, wavio
from . import theme

RECORD_SECONDS = 10
COUNTDOWN_SECONDS = 3


class StudioPanel(ttk.Frame):
    def __init__(self, master, get_settings, set_setting, is_live=lambda: False, get_ai_options=lambda: None):
        super().__init__(master, padding=12)
        self._get_settings = get_settings
        self._get_ai_options = get_ai_options
        self._set_setting = set_setting
        self._is_live = is_live
        self._jobs: queue.Queue = queue.Queue()
        self._busy = False
        self._pending_preview = False
        self._suggested_gate: float | None = None
        self._recordings: list = []
        self.columnconfigure(0, weight=1)

        self._build_recording_section()
        self._build_convert_section()
        self._build_listen_section()
        self._build_log_section()

        self._refresh_recordings()
        self._poll_jobs()

    # ----------------------------------------------------------------- arayüz
    def restyle(self) -> None:
        theme.style_text(self._log_text)

    def _build_recording_section(self) -> None:
        box = ttk.LabelFrame(self, text="1. Kayıt", padding=10)
        box.grid(sticky="ew")
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Kayıt").grid(row=0, column=0, sticky="w")
        self._recording_box = ttk.Combobox(box, state="readonly")
        self._recording_box.grid(row=0, column=1, sticky="ew", padx=6)
        self._recording_box.bind("<<ComboboxSelected>>", lambda _e: self._show_recording_levels())
        ttk.Button(box, text="Klasörü aç", command=lambda: os.startfile(paths.DATA_DIR)).grid(row=0, column=2)

        self._record_button = ttk.Button(box, text=f"● Yeni kayıt ({RECORD_SECONDS} sn)",
                                         command=self._start_recording)
        self._record_button.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._countdown = ttk.Label(box, font=("Segoe UI", 14, "bold"))
        self._countdown.grid(row=1, column=1, columnspan=2, sticky="e", pady=(8, 0))

        self._levels = ttk.Label(box, style="Muted.TLabel")
        self._levels.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._gate_button = ttk.Button(box, text="Kapı eşiğini bu kayda göre ayarla",
                                       command=self._apply_suggested_gate, state="disabled")
        self._gate_button.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _build_convert_section(self) -> None:
        box = ttk.LabelFrame(self, text="2. Dönüştür", padding=10)
        box.grid(sticky="ew", pady=(10, 0))
        method_row = ttk.Frame(box)
        method_row.grid(sticky="w", pady=(0, 4))
        ttk.Label(method_row, text="Yöntem").pack(side="left")
        self._method = tk.StringVar(value="dsp")
        ttk.Radiobutton(method_row, text="DSP (soldaki ayarlar)", value="dsp",
                        variable=self._method).pack(side="left", padx=6)
        ttk.Radiobutton(method_row, text="AI (ana ekranda seçili ses)", value="ai",
                        variable=self._method).pack(side="left")
        self._auto_preview = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="Slider bırakılınca otomatik dönüştür ve çal",
                        variable=self._auto_preview).grid(sticky="w")
        self._with_world = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="WORLD karşılaştırması da üret (yavaş, sadece bu butonla)",
                        variable=self._with_world).grid(sticky="w")
        self._convert_button = ttk.Button(box, text="Dönüştür ve dinle",
                                          command=lambda: self._convert(self._with_world.get()))
        self._convert_button.grid(sticky="w", pady=(6, 0))

    def _build_listen_section(self) -> None:
        box = ttk.LabelFrame(self, text="3. Dinle", padding=10)
        box.grid(sticky="ew", pady=(10, 0))
        ttk.Button(box, text="▶ Orijinal", command=lambda: self._play("original")).pack(side="left")
        ttk.Button(box, text="▶ Dönüştürülmüş", command=lambda: self._play("psola")).pack(side="left", padx=6)
        ttk.Button(box, text="▶ AI", command=lambda: self._play("ai")).pack(side="left")
        ttk.Button(box, text="▶ WORLD", command=lambda: self._play("world")).pack(side="left", padx=6)
        ttk.Button(box, text="■ Durdur", command=sd.stop).pack(side="left", padx=6)

    def _build_log_section(self) -> None:
        box = ttk.LabelFrame(self, text="Sonuçlar", padding=10)
        box.grid(sticky="nsew", pady=(10, 0))
        self.rowconfigure(box.grid_info()["row"], weight=1)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self._log_text = tk.Text(box, height=10, width=60, wrap="word", state="disabled",
                                 font=("Consolas", 9), relief="flat")
        theme.style_text(self._log_text)
        self._log_text.grid(sticky="nsew")

    # ------------------------------------------------------- iş parçacıkları
    def _poll_jobs(self) -> None:
        while True:
            try:
                callback = self._jobs.get_nowait()
            except queue.Empty:
                break
            callback()
        self.after(50, self._poll_jobs)

    def _run_in_background(self, work, on_done) -> None:
        """work() arka planda çalışır; on_done(sonuç | hata) ana iş parçacığında."""
        def runner():
            try:
                result = work()
            except Exception as exc:  # arayüz çökmesin, hatayı göster
                result = exc
            self._jobs.put(lambda: on_done(result))
        threading.Thread(target=runner, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._record_button.config(state=state)
        self._convert_button.config(state=state)

    # ----------------------------------------------------------------- kayıt
    def _refresh_recordings(self, select=None) -> None:
        self._recordings = paths.list_recordings()
        self._recording_box.config(values=[p.name for p in self._recordings])
        if select is not None:
            self._recording_box.set(select.name)
        elif self._recordings and not self._recording_box.get():
            self._recording_box.set(self._recordings[0].name)
        self._show_recording_levels()

    def _selected_recording(self):
        name = self._recording_box.get()
        return next((p for p in self._recordings if p.name == name), None)

    def _blocked_by_live(self) -> bool:
        """Canlıdayken stüdyo işleri Discord'a giden seste takılmaya yol açabilir."""
        if self._is_live():
            self._log("Canlı mod açıkken stüdyo kullanılamaz (Discord'a giden ses takılabilir). "
                      "Önce ana ekrandan durdur. Ayarlar canlıda zaten anında duyulur.")
            return True
        return False

    def _start_recording(self) -> None:
        if self._blocked_by_live():
            return
        sd.stop()
        self._set_busy(True)
        self._tick_countdown(COUNTDOWN_SECONDS)

    def _tick_countdown(self, remaining: int) -> None:
        if remaining > 0:
            self._countdown.config(text=f"Kayıt {remaining} sn sonra…", foreground=theme.color("muted"))
            self.after(1000, self._tick_countdown, remaining - 1)
            return
        self._record_started = time.monotonic()
        self._tick_recording()
        self._run_in_background(lambda: recorder.record(RECORD_SECONDS), self._recording_done)

    def _tick_recording(self) -> None:
        if not self._busy:
            return
        left = RECORD_SECONDS - (time.monotonic() - self._record_started)
        if left > 0:
            self._countdown.config(text=f"● KAYIT — konuş ({left:.0f})", foreground=theme.color("error"))
            self.after(200, self._tick_recording)

    def _recording_done(self, result) -> None:
        self._set_busy(False)
        self._countdown.config(text="")
        if isinstance(result, Exception):
            self._log(f"Kayıt başarısız: {result}")
            return
        path = paths.new_recording_path()
        wavio.save(str(path), result)
        self._log(f"Kaydedildi: {path.relative_to(paths.ROOT)}")
        self._refresh_recordings(select=path)

    def _show_recording_levels(self) -> None:
        recording = self._selected_recording()
        if recording is None:
            self._levels.config(text="Henüz kayıt yok. 'Yeni kayıt' ile başla.")
            self._gate_button.config(state="disabled")
            return
        x = wavio.load_mono(str(recording))
        report = recorder.analyze_levels(x)
        self._suggested_gate = recorder.suggest_gate_threshold(x)
        text = (f"Tepe {report.peak_db:.1f} dBFS · arka gürültü {report.noise_floor_db:.1f} dBFS · "
                f"konuşma {report.speech_db:.1f} dBFS · önerilen kapı {self._suggested_gate:.0f} dBFS")
        for warning in report.warnings:
            text += f"\n⚠ {warning}"
        self._levels.config(text=text)
        self._gate_button.config(state="normal")

    def _apply_suggested_gate(self) -> None:
        if self._suggested_gate is not None:
            self._set_setting("gate_threshold_db", self._suggested_gate)

    # ------------------------------------------------------------ dönüştürme
    def on_settings_committed(self) -> None:
        """Slider bırakıldığında çağrılır."""
        if self._is_live():
            return  # canlıda ayar zaten anında duyuluyor
        if self._auto_preview.get() and self._selected_recording() is not None:
            self._convert(with_world=False)

    def _convert(self, with_world: bool) -> None:
        if self._blocked_by_live():
            return
        recording = self._selected_recording()
        if recording is None:
            self._log("Önce bir kayıt al.")
            return
        if self._busy:
            self._pending_preview = True  # bitince en güncel ayarlarla tekrar
            return
        settings = self._get_settings()
        if self._method.get() == "ai":
            options = self._get_ai_options()
            if options is None:
                self._log("Kurulu AI sesi yok. Şimdilik DSP yöntemini kullan.")
                return
            sd.stop()
            self._set_busy(True)
            self._log("AI ile dönüştürülüyor (ilk seferde model yüklenir, birkaç saniye)…")
            self._run_in_background(lambda: render.convert_recording_ai(recording, settings, *options),
                                    lambda result: self._convert_ai_done(recording, result))
            return
        sd.stop()
        self._set_busy(True)
        self._run_in_background(lambda: render.convert_recording(recording, settings, with_world),
                                lambda result: self._convert_done(recording, result))

    def _convert_ai_done(self, recording, result) -> None:
        self._set_busy(False)
        if isinstance(result, Exception):
            self._log(f"AI dönüştürme başarısız: {result}")
            return
        self._log(f"{recording.name}: AI · sesin {result.input_f0_hz:.0f} Hz → çıkış {result.output_f0_hz:.0f} Hz "
                  f"(kaydırma {result.shift_st:+.1f} st)\n   {result.stats.describe()}")
        if self._pending_preview:
            self._pending_preview = False
            self._convert(with_world=False)
            return
        self._play("ai")

    def _convert_done(self, recording, result) -> None:
        self._set_busy(False)
        if isinstance(result, Exception):
            self._log(f"Dönüştürme başarısız: {result}")
            return
        self._log(f"{recording.name}: perde {result.input_f0_hz:.0f} Hz → {result.output_f0_hz:.0f} Hz\n"
                  f"   {result.psola_stats.describe()}"
                  + (f"\n   {result.world_stats.describe()}" if result.world_stats else ""))
        if self._pending_preview:
            self._pending_preview = False
            self._convert(with_world=False)
            return
        self._play("psola")

    # ------------------------------------------------------------------ dinle
    def _play(self, kind: str) -> None:
        recording = self._selected_recording()
        if recording is None:
            return
        path = recording if kind == "original" else paths.output_path(recording, kind)
        if not path.exists():
            hint = {"world": " (WORLD kutusu işaretli).", "ai": " (Yöntem: AI)."}.get(kind, ".")
            self._log(f"{path.name} yok. Önce dönüştür{hint}")
            return
        sd.stop()
        sd.play(wavio.load_mono(str(path)), wavio.SAMPLE_RATE)

    def _log(self, message: str) -> None:
        self._log_text.config(state="normal")
        self._log_text.insert("end", f"[{datetime.now():%H:%M:%S}] {message}\n")
        self._log_text.see("end")
        self._log_text.config(state="disabled")
