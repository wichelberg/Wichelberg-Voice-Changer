"""Ana ekrandaki "Ses" kartı: mod (AI / DSP / normal ses), ses veya preset seçimi, GPU, AI ayarları ve durumu.

Kurallar (docs/DECISIONS.md D21, D30):
  - AI modu sadece hız testinin izin verdiği makinelerde seçilebilir; değilse nedeni yazılır.
  - "GPU hızlandırma (deneysel)" sadece CPU ile eşitlik testini geçen bir GPU varsa görünür.
  - Model yüklenirken ve AI geç kalınca Discord'a sessizlik gider (motor bunu garanti eder).
Basit görünümde sadece mod + ses/preset + uyarı görünür; GPU, sliderlar ve ölçümler Gelişmiş görünümde.
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from .. import engine as audio
from ..ai import live, policy, shared
from ..ai.base import ConvertParams
from ..ai.runtime import CPU, GPU
from ..ai.voices import scan_voices
from . import theme

GPU_STATS_EVERY_S = 1.0
OFF = "off"


class AiControls(ttk.LabelFrame):
    def __init__(self, master, engine: audio.AudioEngine, config: dict, on_config_change,
                 presets=None, open_library=lambda: None):
        """presets: DSP presetlerini yöneten VoicePanel (list_presets / preset_name / select_preset)."""
        super().__init__(master, text="Ses", padding=12)
        self.engine = engine
        self.config = config
        self.ai_cfg = config["ai"]
        self._on_config_change = on_config_change
        self._presets = presets
        self._open_library = open_library
        self._voices = []
        self._gpu_stats = None
        self._gpu_sample = None
        self._gpu_sampled_at = 0.0
        self._advanced = False
        self.columnconfigure(1, weight=1)
        self._build()
        self._load_voices()
        self.refresh_availability()
        start_mode = self.ai_cfg.get("mode", audio.DSP)
        if start_mode == audio.AI and not self._availability.allowed:
            start_mode = audio.DSP
        self._select_mode(start_mode, save=False)

    # ----------------------------------------------------------------- arayüz
    def _build(self) -> None:
        modes = ttk.Frame(self)
        modes.grid(row=0, column=0, columnspan=3, sticky="w")
        self._mode = tk.StringVar()
        self._ai_radio = ttk.Radiobutton(modes, text="AI", value=audio.AI, variable=self._mode,
                                         command=self._mode_clicked)
        self._ai_radio.pack(side="left")
        ttk.Radiobutton(modes, text="DSP (hafif)", value=audio.DSP, variable=self._mode,
                        command=self._mode_clicked).pack(side="left", padx=14)
        ttk.Radiobutton(modes, text="Normal ses", value=OFF, variable=self._mode,
                        command=self._mode_clicked).pack(side="left")

        self._choice_label = ttk.Label(self, text="Ses")
        self._choice_label.grid(row=1, column=0, sticky="w", pady=(10, 0))
        self._voice_box = ttk.Combobox(self, state="readonly")
        self._voice_box.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(10, 0))
        self._voice_box.bind("<<ComboboxSelected>>", lambda _e: self._voice_changed())
        self._preset_box = ttk.Combobox(self, state="readonly")
        self._preset_box.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(10, 0))
        self._preset_box.bind("<<ComboboxSelected>>", lambda _e: self._preset_chosen())
        self._off_label = ttk.Label(self, text="Dönüştürme kapalı: Discord'a normal sesin gider.",
                                    style="Muted.TLabel")
        self._off_label.grid(row=1, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(10, 0))

        notice = ttk.Frame(self)
        notice.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        notice.columnconfigure(0, weight=1)
        self._notice = ttk.Label(notice, wraplength=460, justify="left")
        self._notice.grid(row=0, column=0, sticky="w")
        self._notice_button = ttk.Button(notice, text="Ses Kütüphanesi", command=self._open_library)
        self._notice_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        # ---- Gelişmiş
        self._advanced_rows = ttk.Frame(self)
        self._advanced_rows.grid(row=3, column=0, columnspan=3, sticky="ew")
        adv = self._advanced_rows
        adv.columnconfigure(1, weight=1)
        self._gpu_on = tk.BooleanVar(value=self.ai_cfg["runtime"].get("accel") == GPU)
        self._gpu_check = ttk.Checkbutton(adv, text="GPU hızlandırma (deneysel)", variable=self._gpu_on,
                                          command=self._gpu_changed, style="Switch.TCheckbutton")
        self._gpu_check.grid(row=0, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self._correction = tk.DoubleVar()
        self._index_rate = tk.DoubleVar()
        self._correction_label = ttk.Label(adv, width=9, anchor="e")
        self._index_label = ttk.Label(adv, width=9, anchor="e")
        ttk.Label(adv, text="Perde düzeltme").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Scale(adv, from_=-6.0, to=6.0, variable=self._correction,
                  command=lambda _v: self._params_changed()).grid(row=1, column=1, sticky="ew", padx=8,
                                                                   pady=(6, 0))
        self._correction_label.grid(row=1, column=2, sticky="e", pady=(6, 0))
        ttk.Label(adv, text="Tını sadakati (index)").grid(row=2, column=0, sticky="w")
        self._index_scale = ttk.Scale(adv, from_=0.0, to=1.0, variable=self._index_rate,
                                      command=lambda _v: self._params_changed())
        self._index_scale.grid(row=2, column=1, sticky="ew", padx=8)
        self._index_label.grid(row=2, column=2, sticky="e")

        self._status = ttk.Label(adv, wraplength=560, justify="left")
        self._status.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._pitch = ttk.Label(adv, wraplength=560, justify="left", style="Muted.TLabel")
        self._pitch.grid(row=4, column=0, columnspan=3, sticky="w")

    def set_advanced(self, advanced: bool) -> None:
        self._advanced = advanced
        if advanced:
            self._advanced_rows.grid()
        else:
            self._advanced_rows.grid_remove()

    # ----------------------------------------------------------------- sesler
    def _load_voices(self) -> None:
        self._voices = [e.voice for e in scan_voices() if e.voice is not None]
        self._voice_box.config(values=[v.display_name for v in self._voices])
        active = self.ai_cfg.get("active_voice")
        voice = next((v for v in self._voices if v.id == active), self._voices[0] if self._voices else None)
        if voice is not None:
            self._voice_box.set(voice.display_name)
            self.ai_cfg["active_voice"] = voice.id
        else:
            self._voice_box.set("")
        self._load_voice_params()

    def reload_voices(self) -> None:
        """Ses Kütüphanesi'nde ses eklendi/silindi."""
        self._load_voices()
        self.refresh_availability()
        if self._mode.get() == audio.AI and not self._availability.allowed:
            self._select_mode(audio.DSP, save=True)
        self._show_choice()

    def release_voice(self, voice_id: str) -> None:
        """Ses silinmeden/değiştirilmeden önce: yüklüyse bırak (o sırada sessizlik gider), DSP'ye geç."""
        ai = self.engine.ai
        if ai is not None and ai.voice.id == voice_id:
            if self.engine.mode == audio.AI:
                self.engine.set_mode(audio.DSP)
                self.ai_cfg["mode"] = audio.DSP
                if self.engine.enabled:
                    self._mode.set(audio.DSP)
                    self._show_choice()
            self.save_speaker_f0()
            self.engine.set_ai(None)

    def current_voice(self):
        name = self._voice_box.get()
        return next((v for v in self._voices if v.display_name == name), None)

    def _load_voice_params(self) -> None:
        voice = self.current_voice()
        if voice is None:
            return
        per = live.voice_settings(self.ai_cfg, voice)
        self._correction.set(per["correction_st"])
        self._index_rate.set(per["index_rate"])
        self._index_scale.state(["!disabled"] if voice.index_path else ["disabled"])
        self._update_param_labels()

    def ai_options(self):
        """Stüdyo için: (ses, perde düzeltme, ConvertParams, perde yöntemi) veya ses yoksa None."""
        voice = self.current_voice()
        if voice is None:
            return None
        per = live.voice_settings(self.ai_cfg, voice)
        return (voice, per["correction_st"], ConvertParams(index_rate=per["index_rate"], protect=per["protect"]),
                self.ai_cfg.get("pitch_method", "fcpe"))

    # --------------------------------------------------------------- presetler
    def _show_choice(self) -> None:
        mode = self._mode.get()
        for widget in (self._voice_box, self._preset_box, self._off_label):
            widget.grid_remove()
        if mode == audio.AI:
            self._choice_label.config(text="AI sesi")
            self._voice_box.grid()
        elif mode == audio.DSP and self._presets is not None:
            self._choice_label.config(text="Preset")
            self._preset_box.config(values=self._presets.list_presets())
            self._preset_box.grid()
        else:
            self._choice_label.config(text="")
            self._off_label.grid()

    def _preset_chosen(self) -> None:
        if self._presets is not None:
            self._presets.select_preset(self._preset_box.get())

    # ----------------------------------------------------------------- olaylar
    def refresh_availability(self) -> None:
        self._availability = policy.availability(self.ai_cfg)
        if self._availability.gpu_choices:
            self._gpu_check.grid()
        else:  # eşitlik testini geçen GPU yok: seçenek gizli ve kapalı (D21)
            self._gpu_check.grid_remove()
            if self.ai_cfg["runtime"].get("accel") == GPU:
                self.ai_cfg["runtime"]["accel"] = CPU
                self._gpu_on.set(False)
                self._on_config_change()
        self._notice_action = None
        pitch = self.ai_cfg.get("pitch_method", "fcpe")
        missing_shared = [m.file for m in shared.missing() if m.name in ("contentvec", pitch)]
        if not self._voices:
            self._availability.allowed = False
            self._availability.reason = ("Henüz AI sesi yok. Sana gönderilen ses dosyasını (.zip) Ses "
                                         "Kütüphanesi'nden ekle. O zamana kadar DSP modu çalışır.")
            self._notice_action = "Ses Kütüphanesi"
        elif missing_shared:
            self._availability.allowed = False
            self._availability.reason = (f"AI için ortak modeller eksik ({', '.join(missing_shared)}). "
                                         "Ses Kütüphanesi'nden indir.")
            self._notice_action = "Ses Kütüphanesi"
        elif not policy.benchmark(self.ai_cfg):
            self._notice_action = "Hız testi"
        self._ai_radio.state(["!disabled"] if self._availability.allowed else ["disabled"])
        if self._notice_action:
            self._notice_button.config(text=self._notice_action)
            self._notice_button.grid()
        else:
            self._notice_button.grid_remove()

    def _mode_clicked(self) -> None:
        self._select_mode(self._mode.get(), save=True)

    def _select_mode(self, mode: str, save: bool) -> None:
        if mode == OFF:
            self.engine.set_enabled(False)
        else:
            if mode == audio.AI and not self._availability.allowed:
                mode = audio.DSP
            if mode == audio.AI:
                self._ensure_ai()
            self.engine.set_mode(mode)
            self.engine.set_enabled(True)
            self.ai_cfg["mode"] = mode
            if save:
                self._on_config_change()
        self._mode.set(mode)
        self._show_choice()

    def _ensure_ai(self, rebuild: bool = False) -> None:
        """AI dönüştürücüyü kur (arka planda yüklenir; o sırada sessizlik gider)."""
        voice = self.current_voice()
        if voice is None:
            return
        current = self.engine.ai
        if current is not None and not rebuild and current.voice.id == voice.id:
            return
        if current is not None:
            self.save_speaker_f0()
        ai = live.from_settings(self.ai_cfg, voice)
        self.engine.set_ai(ai)
        ai.start()

    def ensure_ai_if_selected(self) -> None:
        """Hız testinden sonra: AI modu seçiliyse modeli yeniden yükle."""
        self.refresh_availability()
        if self.engine.mode == audio.AI and self._availability.allowed:
            self._ensure_ai(rebuild=True)

    def _voice_changed(self) -> None:
        voice = self.current_voice()
        if voice is None:
            return
        self.ai_cfg["active_voice"] = voice.id
        self._load_voice_params()
        self._on_config_change()
        if self.engine.ai is not None:
            self._ensure_ai(rebuild=True)

    def _gpu_changed(self) -> None:
        runtime = self.ai_cfg["runtime"]
        if self._gpu_on.get():
            choice = self._availability.gpu_choices[0]
            runtime.update(accel=GPU, gpu_device_id=choice["device_id"])
        else:
            runtime["accel"] = CPU
        self.ai_cfg["stream"]["block_ms"] = policy.block_ms_for(self.ai_cfg, runtime["accel"])
        self._on_config_change()
        self.refresh_availability()
        if self.engine.ai is not None:
            if self._availability.allowed:
                self._ensure_ai(rebuild=True)
            else:
                self.engine.set_ai(None)
                if self.engine.mode == audio.AI:
                    self._select_mode(audio.DSP, save=True)

    def _params_changed(self) -> None:
        voice = self.current_voice()
        if voice is None:
            return
        correction = round(self._correction.get() * 2) / 2
        index_rate = round(self._index_rate.get(), 2)
        per = self.ai_cfg.setdefault("per_voice", {}).setdefault(voice.id, {})
        per.update(correction_st=correction, index_rate=index_rate)
        per.setdefault("protect", 0.33)
        ai = self.engine.ai
        if ai is not None and ai.voice.id == voice.id:
            ai.correction_st = correction
            ai.params = ConvertParams(index_rate=index_rate, protect=per["protect"])
        self._update_param_labels()
        self._on_config_change()

    def _update_param_labels(self) -> None:
        self._correction_label.config(text=f"{round(self._correction.get() * 2) / 2:+.1f} st")
        self._index_label.config(text=f"%{self._index_rate.get() * 100:.0f}"
                                 if self._index_scale.instate(["!disabled"]) else "index yok")

    def save_speaker_f0(self) -> None:
        ai = self.engine.ai
        if ai is not None and ai.speaker_f0 is not None:
            self.ai_cfg["speaker_f0_hz"] = round(ai.speaker_f0, 1)
            self._on_config_change()

    def shutdown(self) -> None:
        self.save_speaker_f0()
        self.engine.set_ai(None)

    # ----------------------------------------------------------------- durum
    def poll(self, stats: audio.EngineStats) -> None:
        """Ana ekranın ölçüm döngüsünden çağrılır."""
        if not stats.enabled:
            if self._mode.get() != OFF:
                self._mode.set(OFF)
                self._show_choice()
        elif self._mode.get() == OFF:
            self._mode.set(stats.mode)
            self._show_choice()
        if self._presets is not None and self._preset_box.winfo_ismapped():
            name = self._presets.preset_name
            if name and self._preset_box.get() != name:
                self._preset_box.set(name)
        allowed = self._availability
        show_notice = not allowed.allowed or self._advanced
        self._notice.config(text=(("" if allowed.allowed else "⚠ ") + allowed.reason) if show_notice else "",
                            foreground=theme.color("muted" if allowed.allowed else "warn"))
        ai = stats.ai
        if stats.mode != audio.AI or ai is None:
            self._status.config(text="")
            self._pitch.config(text="")
            return
        if ai.state == live.LOADING:
            self._status.config(text=f"● {ai.voice}: model yükleniyor… (bu sırada Discord'a sessizlik gider)",
                                foreground=theme.color("warn"))
        elif ai.state == live.ERROR:
            self._status.config(text=f"⚠ {ai.message} — Discord'a sessizlik gidiyor. DSP moduna geçebilirsin.",
                                foreground=theme.color("error"))
        else:
            text = (f"● {ai.voice} · {ai.provider} · parça {ai.block_ms} ms · işlem {ai.proc_ms:.0f} ms "
                    f"(%95 {ai.proc_p95_ms:.0f}) · AI gecikmesi ≈ {ai.latency_ms:.0f} ms")
            gpu = self._gpu_usage(ai.provider)
            if gpu:
                text += f"\n   {gpu}"
            warn = []
            if ai.late:
                warn.append(f"geç kalan parça {ai.late} (o anlarda sessizlik gitti)")
            if ai.dropped:
                warn.append(f"atlanan parça {ai.dropped}")
            if ai.errors:
                warn.append(f"hata {ai.errors}: {ai.message}")
            if warn:
                text += "\n   ⚠ " + " · ".join(warn)
            self._status.config(text=text, foreground=theme.color("warn" if warn else "ok"))
        speaker = f"{ai.speaker_f0_hz:.0f} Hz" if ai.speaker_f0_hz else "ölçülüyor…"
        self._pitch.config(text=f"Perde: sesin {speaker} → hedef {ai.target_f0_hz:.0f} Hz · kaydırma "
                                f"{ai.applied_shift_st:+.1f} st (otomatik {ai.auto_shift_st:+.1f}, "
                                f"düzeltme {ai.correction_st:+.1f})")

    def _gpu_usage(self, provider: str) -> str:
        if not provider.startswith("GPU"):
            return ""
        now = time.monotonic()
        if now - self._gpu_sampled_at >= GPU_STATS_EVERY_S:
            self._gpu_sampled_at = now
            try:
                if self._gpu_stats is None:
                    from ..ai.gpustats import GpuStats

                    self._gpu_stats = GpuStats()
                self._gpu_sample = self._gpu_stats.sample()
            except OSError:
                self._gpu_sample = None
        sample = self._gpu_sample
        if sample is None:
            return ""
        return (f"GPU: bu program %{sample.process_util_pct:.0f}, toplam %{sample.total_util_pct:.0f} · "
                f"VRAM: bu program {sample.process_vram_mb / 1024:.2f} GB")
