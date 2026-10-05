"""config.json ve preset dosyalarını okuma/yazma.

config.json bozulursa program çökmez: dosya .bak olarak saklanır ve
varsayılanlarla devam edilir. Yazma işlemi atomiktir (önce .tmp, sonra
yerine koyma); yazma sırasında kapanırsa eski dosya bozulmaz.
"""

import copy
import json
import os
import re
from pathlib import Path

from . import paths
from .dsp.params import BUILTIN_PRESETS, VoiceSettings, is_outdated_builtin, migrate_settings

DEFAULT_CONFIG = {
    "version": 1,
    "settings": VoiceSettings().to_dict(),
    "preset": "Varsayılan kadın",
    "audio": {                      # cihazlar isimle saklanır (numaralar değişebilir)
        "input_device": None,
        "output_device": None,      # CABLE Input (VB-Audio Virtual Cable)
        "monitor_device": None,     # kulaklık
        "monitor_enabled": False,
        "low_latency": True,        # mikrofon + CABLE için WASAPI özel mod
        "autostart": False,         # program açılınca canlıyı başlat
    },
    "hotkeys": {"toggle": "ctrl+f7"},
    "ui": {
        "theme": "system",          # system | light | dark
        "view": "simple",           # simple (Basit) | advanced (Gelişmiş: DSP ayarları, stüdyo, ölçümler)
    },
    "ai": {
        # GPU: "GPU hızlandırma (deneysel)", varsayılan kapalı (docs/DECISIONS.md D9)
        "runtime": {"accel": "cpu", "cpu_threads": 0, "gpu_device_id": None},
        "pitch_method": "fcpe",     # fcpe (MIT, varsayılan) | rmvpe (isteğe bağlı)
        "stream": {"block_ms": 250, "context_ms": 1000},
        "mode": "dsp",              # dönüştürme modu: "ai" | "dsp" (AI, hız testi + kurulu ses gerektirir)
        "active_voice": None,
        "per_voice": {},            # ses id → {"correction_st", "index_rate", "protect"}
        "speaker_f0_hz": None,      # konuşanın son ölçülen medyan F0'ı (otomatik perdeye başlangıç)
        "benchmark": None,          # python -m voicechanger.tools.benchmark sonucu
    },
}


def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _merge(defaults: dict, loaded: dict) -> dict:
    merged = copy.deepcopy(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# ------------------------------------------------------------------ config
def load_config() -> dict:
    paths.ensure_dirs()
    if not paths.CONFIG_FILE.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        loaded = _read_json(paths.CONFIG_FILE)
    except (OSError, ValueError):
        os.replace(paths.CONFIG_FILE, paths.CONFIG_FILE.with_suffix(".json.bak"))
        return copy.deepcopy(DEFAULT_CONFIG)
    config = _merge(DEFAULT_CONFIG, loaded)
    if isinstance(loaded.get("settings"), dict):
        # Ses ayarlarını varsayılanlarla doldurma; eksikler (yeni eklenen
        # ayarlar) settings_from_config() içinde seçili preset'ten gelir.
        config["settings"] = loaded["settings"]
    return config


def save_config(config: dict) -> None:
    paths.ensure_dirs()
    _write_json(paths.CONFIG_FILE, config)


def settings_from_config(config: dict) -> VoiceSettings:
    """Son ayarlar; eski sürümden kalan eksik alanlar seçili preset'ten tamamlanır.

    Son ayarlar değiştirilmemiş eski bir hazır preset'in aynısıysa güncel
    preset kullanılır.
    """
    name = config.get("preset") or ""
    try:
        base = load_preset(name) if name else None
    except (OSError, ValueError, KeyError):
        base = None
    if base is not None and is_outdated_builtin(name, config["settings"]):
        return base
    return VoiceSettings.from_dict(migrate_settings(config["settings"]), base=base)


# ----------------------------------------------------------------- presetler
def _preset_file(name: str) -> Path:
    safe = re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "preset"
    return paths.PRESETS_DIR / f"{safe}.json"


def ensure_builtin_presets() -> None:
    """Hazır presetleri oluştur; eski sürümde kaydedilmiş presetleri güncelle.

    Kullanıcının değiştirdiği değerler korunur; yalnızca dosyada hiç olmayan
    (sonradan eklenmiş) ayarlar doldurulur ve migrate_settings uygulanır.
    """
    paths.ensure_dirs()
    for name, builtin in BUILTIN_PRESETS.items():
        file = _preset_file(name)
        try:
            stored = _read_json(file)["settings"]
        except (OSError, ValueError, KeyError):
            save_preset(name, builtin)
            continue
        if is_outdated_builtin(name, stored):
            save_preset(name, builtin)
        elif set(builtin.to_dict()) - set(stored):
            save_preset(name, VoiceSettings.from_dict(migrate_settings(stored), base=builtin))

    for file in paths.PRESETS_DIR.glob("*.json"):  # kullanıcı presetleri
        try:
            data = _read_json(file)
            stored = data["settings"]
        except (OSError, ValueError, KeyError):
            continue
        migrated = migrate_settings(stored)
        if migrated != stored:
            save_preset(data.get("name", file.stem), VoiceSettings.from_dict(migrated))


def list_presets() -> list[str]:
    names = []
    for file in sorted(paths.PRESETS_DIR.glob("*.json")):
        try:
            names.append(_read_json(file).get("name", file.stem))
        except (OSError, ValueError):
            continue
    return names


def load_preset(name: str) -> VoiceSettings:
    return VoiceSettings.from_dict(migrate_settings(_read_json(_preset_file(name))["settings"]))


def save_preset(name: str, settings: VoiceSettings) -> None:
    _write_json(_preset_file(name), {"name": name, "settings": settings.to_dict()})


def delete_preset(name: str) -> None:
    _preset_file(name).unlink(missing_ok=True)
