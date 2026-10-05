"""Sol panel: preset seçimi, perde modu ve ses ayar sliderları.

Sliderlar dsp/params.py içindeki SLIDERS listesinden otomatik üretilir;
yeni bir ayar eklemek için oraya bir satır eklemek yeterli. Her slider tek
satırdır; açıklaması fareyle üzerine gelince panelin altında görünür.
"""

import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, simpledialog, ttk

from .. import settings as config
from ..dsp.params import (BUILTIN_PRESETS, CHILDLIKE_FORMANT, CHILDLIKE_TARGET_HZ,
                          PITCH_MODE_SEMITONES, PITCH_MODE_TARGET, SLIDERS, TOGGLES,
                          VoiceSettings)

MODIFIED_MARK = " *"
HINT_PLACEHOLDER = "Bir ayarın üzerine gel; ne işe yaradığı burada görünür."


class VoicePanel(ttk.LabelFrame):
    def __init__(self, master, settings: VoiceSettings, preset_name: str, on_change):
        """on_change(settings, final): final=True slider bırakıldığında."""
        super().__init__(master, text="Ses ayarları", padding=10)
        self.settings = settings
        self._remember_preset(preset_name)
        self._on_change = on_change
        self._specs = {spec.field: spec for spec in SLIDERS}
        self._vars: dict[str, tk.DoubleVar] = {}
        self._value_labels: dict[str, ttk.Label] = {}
        self._rows: dict[str, ttk.Frame] = {}
        self._loading = False
        self.columnconfigure(0, weight=1)

        self._toggle_vars: dict[str, tk.BooleanVar] = {}
        self._build_preset_row()
        group = None
        for spec in SLIDERS:
            if spec.group != group:
                if group is not None:
                    self._build_toggles(group)
                group = spec.group
                self._build_group_header(group)
                if group == "Perde":
                    self._build_mode_row()
            self._build_slider(spec)
        self._build_toggles(group)

        self._warning = ttk.Label(self, style="Warn.TLabel", wraplength=420)
        self._warning.grid(sticky="w", pady=(6, 0))
        self._hint = ttk.Label(self, text=HINT_PLACEHOLDER, style="Muted.TLabel", wraplength=420,
                               justify="left")
        self._hint.grid(sticky="ew", pady=(6, 0))
        ttk.Button(self, text="Varsayılana dön", command=self._reset_defaults).grid(sticky="w", pady=(8, 0))

        self._show_settings(settings)

    # ----------------------------------------------------------------- arayüz
    def _build_preset_row(self) -> None:
        row = ttk.Frame(self)
        row.grid(sticky="ew", pady=(0, 4))
        ttk.Label(row, text="Preset").pack(side="left")
        self._preset_box = ttk.Combobox(row, state="readonly", width=22, values=config.list_presets())
        self._preset_box.pack(side="left", padx=6)
        self._preset_box.bind("<<ComboboxSelected>>", lambda _e: self._load_preset())
        ttk.Button(row, text="Kaydet…", width=8, command=self._save_preset).pack(side="left")
        ttk.Button(row, text="Sil", width=4, command=self._delete_preset).pack(side="left", padx=(4, 0))

    def _build_group_header(self, title: str) -> None:
        header = ttk.Frame(self)
        header.grid(sticky="ew", pady=(10, 2))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text=title, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, padx=(0, 6))
        ttk.Separator(header).grid(row=0, column=1, sticky="ew")

    def _build_mode_row(self) -> None:
        row = ttk.Frame(self)
        row.grid(sticky="w", pady=(0, 2))
        ttk.Label(row, text="Mod", width=19).pack(side="left")
        self._mode = tk.StringVar()
        for text, value in (("Sabit kaydırma", PITCH_MODE_SEMITONES), ("Hedef perde", PITCH_MODE_TARGET)):
            ttk.Radiobutton(row, text=text, value=value, variable=self._mode,
                            command=self._mode_changed).pack(side="left", padx=(0, 8))

    def _build_slider(self, spec) -> None:
        row = ttk.Frame(self)
        row.grid(sticky="ew", pady=1)
        row.columnconfigure(1, weight=1)
        label = ttk.Label(row, text=spec.label, width=19)
        label.grid(row=0, column=0, sticky="w")

        var = tk.DoubleVar()
        scale = ttk.Scale(row, from_=spec.minimum, to=spec.maximum, variable=var, length=200,
                          command=lambda _v, f=spec.field: self._slider_moved(f))
        scale.grid(row=0, column=1, sticky="ew", padx=4)
        scale.bind("<ButtonRelease-1>", lambda _e: self._commit())
        scale.bind("<KeyRelease>", lambda _e: self._commit())

        value_label = ttk.Label(row, width=13, anchor="e")
        value_label.grid(row=0, column=2, sticky="e")

        for widget in (row, label, scale, value_label):
            widget.bind("<Enter>", lambda _e, s=spec: self._show_hint(s), add="+")

        self._vars[spec.field] = var
        self._value_labels[spec.field] = value_label
        self._rows[spec.field] = row

    def _build_toggles(self, group: str) -> None:
        for spec in (t for t in TOGGLES if t.group == group):
            var = tk.BooleanVar()
            box = ttk.Checkbutton(self, text=spec.label, variable=var,
                                  command=lambda f=spec.field: self._toggle_changed(f))
            box.grid(sticky="w", pady=(2, 0))
            box.bind("<Enter>", lambda _e, s=spec: self._show_hint(s), add="+")
            self._toggle_vars[spec.field] = var

    def _toggle_changed(self, field: str) -> None:
        if not self._loading:
            self._apply(replace(self.settings, **{field: self._toggle_vars[field].get()}), final=True)

    def _show_hint(self, spec) -> None:
        self._hint.config(text=f"{spec.label}: {spec.hint}" if spec.hint else spec.label)

    # --------------------------------------------------------------- olaylar
    def _slider_moved(self, field: str) -> None:
        if self._loading:
            return
        spec = self._specs[field]
        value = round(round(self._vars[field].get() / spec.step) * spec.step, 4)
        self._value_labels[field].config(text=spec.format(value))
        if value != getattr(self.settings, field):
            self._apply(replace(self.settings, **{field: value}), final=False)

    def _mode_changed(self) -> None:
        self._apply(replace(self.settings, pitch_mode=self._mode.get()), final=True)
        self._refresh_mode_rows()

    def _commit(self) -> None:
        self._on_change(self.settings, final=True)

    def set_value(self, field: str, value: float) -> None:
        """Dışarıdan bir ayarı değiştir (ör. önerilen kapı eşiği)."""
        new = replace(self.settings, **{field: value})
        self._show_settings(new)
        self._apply(new, final=True)

    def _apply(self, settings: VoiceSettings, final: bool) -> None:
        self.settings = settings
        self._refresh_warning()
        self._refresh_preset_mark()
        self._on_change(settings, final)

    # --------------------------------------------------------------- presetler
    def _load_preset(self) -> None:
        name = self._preset_box.get()
        self._remember_preset(name)
        settings = self._preset_settings
        if settings is None:
            messagebox.showerror("Preset", f"'{name}' yüklenemedi.")
            return
        self._show_settings(settings)
        self._apply(settings, final=True)

    def list_presets(self) -> list[str]:
        return config.list_presets()

    def select_preset(self, name: str) -> None:
        """Ana ekrandaki preset seçiminden (Basit görünüm)."""
        self._preset_box.config(values=config.list_presets())
        self._preset_box.set(name)
        self._load_preset()

    def _save_preset(self) -> None:
        name = simpledialog.askstring("Preset kaydet", "Preset adı:", parent=self,
                                      initialvalue=self.preset_name)
        if not name or not name.strip():
            return
        name = name.strip()
        config.save_preset(name, self.settings)
        self._remember_preset(name)
        self._preset_box.config(values=config.list_presets())
        self._refresh_preset_mark()
        self._on_change(self.settings, final=False)

    def _delete_preset(self) -> None:
        name = self.preset_name
        if not name:
            return
        if name in BUILTIN_PRESETS:
            messagebox.showinfo("Preset", "Hazır presetler silinemez (üzerine kaydedebilirsin).")
            return
        if messagebox.askyesno("Preset sil", f"'{name}' silinsin mi?"):
            config.delete_preset(name)
            self._remember_preset("")
            self._preset_box.config(values=config.list_presets())
            self._preset_box.set("")

    def _reset_defaults(self) -> None:
        self._preset_box.set("Varsayılan kadın")
        self._load_preset()

    # -------------------------------------------------------------- görünüm
    def _show_settings(self, settings: VoiceSettings) -> None:
        """Widget'ları ayarlara eşitle (olay tetiklemeden)."""
        self._loading = True
        try:
            self._mode.set(settings.pitch_mode)
            for field, var in self._vars.items():
                value = getattr(settings, field)
                var.set(value)
                self._value_labels[field].config(text=self._specs[field].format(value))
            for field, var in self._toggle_vars.items():
                var.set(bool(getattr(settings, field)))
        finally:
            self._loading = False
        self.settings = settings
        self._refresh_mode_rows()
        self._refresh_warning()
        self._refresh_preset_mark()

    def _refresh_mode_rows(self) -> None:
        target = self._mode.get() == PITCH_MODE_TARGET
        self._rows["target_f0_hz" if target else "pitch_semitones"].grid()
        self._rows["pitch_semitones" if target else "target_f0_hz"].grid_remove()

    def _refresh_warning(self) -> None:
        s = self.settings
        childlike = s.formant_ratio > CHILDLIKE_FORMANT or (
            s.pitch_mode == PITCH_MODE_TARGET and s.target_f0_hz > CHILDLIKE_TARGET_HZ)
        self._warning.config(text="⚠ Bu değerlerde ses çocuksu/anime tınısına kayabilir." if childlike else "")

    def _remember_preset(self, name: str) -> None:
        """Seçili preset'in kayıtlı halini sakla ("değiştirildi *" işareti için)."""
        self.preset_name = name
        try:
            self._preset_settings = config.load_preset(name) if name else None
        except (OSError, ValueError, KeyError):
            self._preset_settings = None

    def _refresh_preset_mark(self) -> None:
        if not self.preset_name:
            return
        modified = self._preset_settings != self.settings
        self._preset_box.set(self.preset_name + (MODIFIED_MARK if modified else ""))
