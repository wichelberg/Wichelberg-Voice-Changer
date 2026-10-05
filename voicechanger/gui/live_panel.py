"""Ana ekran: mikrofon → dönüştürülmüş ses (AI veya DSP) → CABLE Input (Discord/FiveM).

Cihazlar isimle hatırlanır (Windows cihaz numaralarını değiştirebilir).
Ctrl+F7 (değiştirilebilir) dönüştürmeyi açar/kapatır; kapalıyken normal
sesin gider. Programı kapatan bir kısayol bilinçli olarak yoktur.
Basit görünüm: durum + Başlat + ses seçimi + cihazlar + seviye. Gelişmiş: ölçümler, kısayol, düşük gecikme.
"""

import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import sounddevice as sd

from .. import engine as audio
from .. import hotkeys
from . import theme
from .ai_controls import AiControls
from .widgets import ScrollFrame

POLL_MS = 250
VBCABLE_URL = "https://vb-audio.com/Cable/"
VBCABLE_STEPS = (
    "1. Açılan sayfadan \"VBCABLE_Driver_Pack\" zip'ini indir ve bir klasöre çıkar.\n"
    "2. VBCABLE_Setup_x64.exe → sağ tık → \"Yönetici olarak çalıştır\" → \"Install Driver\".\n"
    "3. Bilgisayarı yeniden başlat.\n"
    "4. Programı aç: çıkış otomatik olarak \"CABLE Input\" seçilir.\n\n"
    "Windows'un varsayılan hoparlörünü CABLE Input YAPMA; yoksa bilgisayarın tüm sesi Discord'a gider."
)


class LivePanel(ScrollFrame):
    def __init__(self, master, engine: audio.AudioEngine, config: dict, on_config_change,
                 presets=None, open_library=lambda: None, busy_reason=lambda: None):
        """busy_reason(): canlı şu an başlatılamıyorsa nedeni (ör. hız testi sürüyor), yoksa None."""
        super().__init__(master, padding=(16, 14, 16, 14))
        self.engine = engine
        self.config = config
        self._on_config_change = on_config_change
        self._busy_reason = busy_reason
        self._hotkey = hotkeys.GlobalHotkey()
        self._advanced_widgets: list = []
        body = self.body
        body.columnconfigure(0, weight=1)

        self._build_hero(body)
        self.ai_controls = AiControls(body, engine, config, on_config_change, presets=presets,
                                      open_library=open_library)
        self.ai_controls.grid(sticky="ew", pady=(12, 0))
        self._build_cable_card(body)
        self._build_devices(body)
        self._build_meters(body)
        self._build_extras(body)
        self._build_help(body)

        self._load_device_lists()
        self._apply_hotkey(self.config["hotkeys"]["toggle"], show_errors=False)
        self._poll()

    # ----------------------------------------------------------------- arayüz
    def _advanced(self, widget, **grid):
        """Sadece Gelişmiş görünümde görünen öğe."""
        widget.grid(**grid)
        self._advanced_widgets.append(widget)
        return widget

    def set_advanced(self, advanced: bool) -> None:
        for widget in self._advanced_widgets:
            if advanced:
                widget.grid()
            else:
                widget.grid_remove()
        self.ai_controls.set_advanced(advanced)

    def _build_hero(self, body) -> None:
        card = ttk.Frame(body, style="Card.TFrame", padding=16)
        card.grid(sticky="ew")
        card.columnconfigure(2, weight=1)
        self._status = ttk.Label(card, style="Status.TLabel", wraplength=560, justify="left")
        self._status.grid(row=0, column=0, columnspan=3, sticky="w")
        self._substatus = ttk.Label(card, style="Muted.TLabel", wraplength=560, justify="left")
        self._substatus.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))
        self._start_button = ttk.Button(card, text="▶  Başlat", width=12, style="Big.Accent.TButton",
                                        command=self._start_stop)
        self._start_button.grid(row=2, column=0, sticky="w")
        self._toggle_button = ttk.Button(card, style="Big.TButton", command=self._toggle)
        self._toggle_button.grid(row=2, column=1, sticky="w", padx=(10, 0))

    def _build_cable_card(self, body) -> None:
        self._cable_card = ttk.LabelFrame(body, text="VB-Cable gerekli", padding=12)
        self._cable_card.grid(sticky="ew", pady=(12, 0))
        self._cable_card.columnconfigure(0, weight=1)
        ttk.Label(self._cable_card, style="Warn.TLabel", wraplength=540, justify="left",
                  text="Sesin Discord'a ve FiveM'e gitmesi için ücretsiz VB-Cable sürücüsü gerekiyor. "
                       "Kurulana kadar sadece \"Kendimi duy\" ile kulaklıkta deneme yapabilirsin.").grid(
            row=0, column=0, columnspan=3, sticky="w")
        buttons = ttk.Frame(self._cable_card)
        buttons.grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Button(buttons, text="VB-Cable'ı indir", style="Accent.TButton",
                   command=lambda: webbrowser.open(VBCABLE_URL)).pack(side="left")
        ttk.Button(buttons, text="Nasıl kurulur?",
                   command=lambda: messagebox.showinfo("VB-Cable kurulumu", VBCABLE_STEPS)).pack(side="left",
                                                                                                padx=8)
        ttk.Button(buttons, text="Tekrar kontrol et", command=self._refresh_devices).pack(side="left")

    def _build_devices(self, body) -> None:
        box = ttk.LabelFrame(body, text="Cihazlar", padding=12)
        box.grid(sticky="ew", pady=(12, 0))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Mikrofon").grid(row=0, column=0, sticky="w")
        self._input_box = ttk.Combobox(box, state="readonly")
        self._input_box.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(box, text="Discord'a çıkış").grid(row=1, column=0, sticky="w")
        self._output_box = ttk.Combobox(box, state="readonly")
        self._output_box.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=2)

        self._monitor_on = tk.BooleanVar(value=self.config["audio"]["monitor_enabled"])
        ttk.Checkbutton(box, text="Kendimi duy", variable=self._monitor_on,
                        command=self._monitor_changed).grid(row=2, column=0, sticky="w")
        self._monitor_box = ttk.Combobox(box, state="readonly")
        self._monitor_box.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=2)

        for combo in (self._input_box, self._output_box):
            combo.bind("<<ComboboxSelected>>", lambda _e: self._devices_changed(restart=True))
        self._monitor_box.bind("<<ComboboxSelected>>", lambda _e: self._monitor_changed())

        self._low_latency = tk.BooleanVar(value=self.config["audio"]["low_latency"])
        self._advanced(ttk.Checkbutton(box, text="Düşük gecikme modu (çıkış CABLE iken mikrofonu özel kullan)",
                                       variable=self._low_latency,
                                       command=lambda: self._devices_changed(restart=True)),
                       row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._advanced(ttk.Button(box, text="Cihazları yenile", command=self._refresh_devices),
                       row=4, column=0, sticky="w", pady=(8, 0))
        self._device_warning = ttk.Label(box, style="Warn.TLabel", wraplength=540, justify="left")
        self._device_warning.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _build_meters(self, body) -> None:
        box = ttk.LabelFrame(body, text="Seviye", padding=12)
        box.grid(sticky="ew", pady=(12, 0))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Mikrofon").grid(row=0, column=0, sticky="w")
        self._level = ttk.Progressbar(box, maximum=60, length=260)
        self._level.grid(row=0, column=1, sticky="ew", padx=8)
        self._gate_label = ttk.Label(box, width=10)
        self._gate_label.grid(row=0, column=2, sticky="e")

        ttk.Label(box, text="Discord'a giden").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._out_level = ttk.Progressbar(box, maximum=60, length=260)
        self._out_level.grid(row=1, column=1, sticky="ew", padx=8, pady=(4, 0))
        self._gain_label = ttk.Label(box, width=16, style="Muted.TLabel")
        self._advanced(self._gain_label, row=1, column=2, sticky="e", pady=(4, 0))

        self._latency_label = self._advanced(ttk.Label(box, style="Muted.TLabel"),
                                             row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self._cpu_label = self._advanced(ttk.Label(box, style="Muted.TLabel"),
                                         row=3, column=0, columnspan=3, sticky="w")
        self._health_label = self._advanced(ttk.Label(box, wraplength=560, justify="left"),
                                            row=4, column=0, columnspan=3, sticky="w")

    def _build_extras(self, body) -> None:
        box = self._advanced(ttk.LabelFrame(body, text="Kısayol ve başlangıç", padding=12),
                             sticky="ew", pady=(12, 0))
        hotkey_row = ttk.Frame(box)
        hotkey_row.grid(row=0, column=0, sticky="w")
        ttk.Label(hotkey_row, text="Aç/kapa kısayolu").pack(side="left")
        self._hotkey_var = tk.StringVar(value=self.config["hotkeys"]["toggle"])
        ttk.Entry(hotkey_row, textvariable=self._hotkey_var, width=14).pack(side="left", padx=8)
        ttk.Button(hotkey_row, text="Uygula",
                   command=lambda: self._apply_hotkey(self._hotkey_var.get())).pack(side="left")
        ttk.Label(hotkey_row, text="örn. ctrl+f7, alt+shift+v", style="Muted.TLabel").pack(side="left", padx=8)

        self._autostart = tk.BooleanVar(value=self.config["audio"]["autostart"])
        ttk.Checkbutton(box, text="Program açılınca otomatik başlat", variable=self._autostart,
                        command=self._autostart_changed, style="Switch.TCheckbutton").grid(
            row=1, column=0, sticky="w", pady=(8, 0))

    def _build_help(self, body) -> None:
        box = ttk.LabelFrame(body, text="Discord / FiveM ayarı", padding=12)
        box.grid(sticky="ew", pady=(12, 0))
        text = ("Discord → Kullanıcı Ayarları → Ses ve Görüntü → Giriş Aygıtı: "
                "\"CABLE Output (VB-Audio Virtual Cable)\". Aynı sayfada Gürültü Azaltma'yı "
                "kapat (Krisp sesi bozar), Yankı Engelleme'yi kapat.\n"
                "FiveM → Ayarlar → Ses → Mikrofon: \"CABLE Output\".")
        ttk.Label(box, text=text, wraplength=560, justify="left", style="Muted.TLabel").grid(sticky="w")

    # --------------------------------------------------------------- cihazlar
    def _load_device_lists(self) -> None:
        inputs, outputs = audio.list_devices("input"), audio.list_devices("output")
        audio_cfg = self.config["audio"]
        self._input_box.config(values=inputs)
        self._output_box.config(values=outputs)
        self._monitor_box.config(values=outputs)
        self._input_box.set(_pick(audio_cfg["input_device"], inputs, audio.default_device("input")))
        self._output_box.set(_pick(audio_cfg["output_device"], outputs, audio.find_cable_output()))
        self._monitor_box.set(_pick(audio_cfg["monitor_device"], outputs, audio.default_device("output")))
        self._devices_changed(restart=False)

    def _refresh_devices(self) -> None:
        if self.engine.running:
            messagebox.showinfo("Cihazlar", "Cihaz listesini yenilemek için önce canlıyı durdur.")
            return
        sd.stop()
        audio.refresh_devices()
        self._load_device_lists()

    def _devices_changed(self, restart: bool) -> None:
        audio_cfg = self.config["audio"]
        audio_cfg["input_device"] = self._input_box.get() or None
        audio_cfg["output_device"] = self._output_box.get() or None
        audio_cfg["monitor_device"] = self._monitor_box.get() or None
        audio_cfg["low_latency"] = self._low_latency.get()
        self._on_config_change()
        self._refresh_warnings()
        if restart and self.engine.running:
            self._start()

    def _monitor_changed(self) -> None:
        self.config["audio"]["monitor_enabled"] = self._monitor_on.get()
        self._devices_changed(restart=False)
        if self.engine.running:
            try:
                self.engine.set_monitor(self._monitor_name())
            except (audio.EngineError, sd.PortAudioError) as exc:
                messagebox.showerror("Kulaklık", str(exc))

    def _monitor_name(self) -> str | None:
        if not self._monitor_on.get():
            return None
        return self._monitor_box.get() or None

    def _refresh_warnings(self) -> None:
        output = self._output_box.get()
        monitor = self._monitor_box.get()
        lines = []
        cable_missing = audio.find_cable_output() is None
        if cable_missing:
            self._cable_card.grid()
        else:
            self._cable_card.grid_remove()
            if output and not audio.is_cable(output):
                lines.append("Discord'a gitmesi için çıkış \"CABLE Input\" olmalı.")
        if self._monitor_on.get() and monitor and "speaker" in monitor.lower():
            lines.append("Hoparlörden dinlersen mikrofon sesi geri alır (çınlama). Kulaklık kullan.")
        self._device_warning.config(text="\n".join(lines))
        if lines:
            self._device_warning.grid()
        else:
            self._device_warning.grid_remove()

    # ---------------------------------------------------------------- kontrol
    def _start_stop(self) -> None:
        if self.engine.running:
            self.engine.stop()
        else:
            self._start()

    def _start(self) -> None:
        busy = self._busy_reason()
        if busy:
            messagebox.showinfo("Başlat", busy)
            return
        mic, output = self._input_box.get(), self._output_box.get()
        if not mic or not output:
            messagebox.showwarning("Başlat", "Önce mikrofonu ve çıkış cihazını seç.")
            return
        sd.stop()  # stüdyoda / kütüphanede çalan bir ses varsa durdur
        try:
            self.engine.start(mic, output, self._monitor_name(), low_latency=self._low_latency.get())
        except audio.EngineError as exc:
            messagebox.showerror("Başlat", str(exc))

    def start_if_autostart(self) -> None:
        if self.config["audio"]["autostart"] and not self.engine.running:
            self._start()

    def _toggle(self) -> None:
        self.engine.toggle()

    def _apply_hotkey(self, spec: str, show_errors: bool = True) -> None:
        spec = spec.strip().lower()
        if not hotkeys.is_valid(spec):
            if show_errors:
                messagebox.showerror("Kısayol", f"Geçersiz kısayol: {spec}\nÖrnek: ctrl+f7")
            return
        # pynput iş parçacığından çağrılır; toggle yalnızca bir bayrak değiştirir
        self._hotkey.set(spec, self.engine.toggle)
        self.config["hotkeys"]["toggle"] = spec
        self._hotkey_var.set(spec)
        self._on_config_change()

    def _autostart_changed(self) -> None:
        self.config["audio"]["autostart"] = self._autostart.get()
        self._on_config_change()

    def shutdown(self) -> None:
        self._hotkey.stop()
        self.engine.stop()          # önce ses akışı: CABLE'a giden ses kesilir
        self.ai_controls.shutdown()

    # ----------------------------------------------------------------- ölçüm
    def _poll(self) -> None:
        stats = self.engine.stats()
        c = theme.colors()
        hotkey = self.config["hotkeys"]["toggle"].upper()
        self._start_button.config(text="■  Durdur" if stats.running else "▶  Başlat")
        self._toggle_button.config(text=f"Dönüştürmeyi {'kapat' if stats.enabled else 'aç'} ({hotkey})")
        if not stats.running:
            status, color = "● Durduruldu", c["muted"]
            sub = "Discord'a ses gitmiyor. Başlat'a bas."
        elif not stats.to_cable:
            status, color = "● TEST", c["warn"]
            sub = "Ses sadece seçili cihaza gidiyor, Discord'a GİTMİYOR."
        elif stats.enabled and stats.mode == audio.AI and (stats.ai is None or stats.ai.state != "hazır"):
            status, color = "● CANLI — AI hazırlanıyor", c["warn"]
            sub = "Bu sırada Discord'a SESSİZLİK gidiyor."
        elif stats.enabled:
            status, color = "● CANLI", c["ok"]
            kind = "AI" if stats.mode == audio.AI else "DSP"
            sub = f"Discord'a {kind} ile dönüştürülmüş ses gidiyor. Kapatmak için {hotkey}."
        else:
            status, color = "● CANLI — NORMAL SES", c["warn"]
            sub = f"Discord'a gerçek sesin gidiyor. Dönüştürmeyi açmak için {hotkey}."
        self._status.config(text=status, foreground=color)
        self._substatus.config(text=sub)

        if stats.running:
            self._level["value"] = max(0.0, stats.input_db + 60.0)
            self._gate_label.config(text="konuşuyor" if stats.gate_open else "sessiz",
                                    foreground=c["ok"] if stats.gate_open else c["muted"])
            self._out_level["value"] = max(0.0, stats.output_db + 60.0)
            self._gain_label.config(text=f"oto. kazanç {stats.auto_gain_db:+.0f} dB")
            parts = " · ".join(f"{k} {v:.0f}" for k, v in stats.latency_parts.items())
            self._latency_label.config(text=f"Gecikme ≈ {stats.latency_ms:.0f} ms  ({parts})  + VB-Cable")
            self._cpu_label.config(text=f"CPU: program %{stats.cpu_pct:.1f} · ses kartı döngüsü yükü "
                                        f"%{stats.dsp_load_pct:.1f} (10 ms bütçenin)")
            mode = (f"mikrofon {'özel' if stats.exclusive_input else 'paylaşımlı'}, "
                    f"çıkış {'özel' if stats.exclusive_output else 'paylaşımlı'} mod")
            health = f"Takılma: {stats.underruns} · {mode}"
            if stats.error:
                health += f"\n⚠ İşleme hatası (o anlarda sessizlik gönderildi): {stats.error}"
            self._health_label.config(text=health, foreground=c["error"] if stats.error else c["muted"])
        else:
            self._level["value"] = 0
            self._out_level["value"] = 0
            self._gate_label.config(text="")
            self._gain_label.config(text="")
            for label in (self._latency_label, self._cpu_label, self._health_label):
                label.config(text="")
        self.ai_controls.poll(stats)
        self.after(POLL_MS, self._poll)


def _pick(saved: str | None, options: list[str], fallback: str | None) -> str:
    """Kayıtlı cihaz hâlâ varsa onu, yoksa önerileni seç."""
    if saved in options:
        return saved
    if fallback in options:
        return fallback
    return ""
