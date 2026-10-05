"""Projedeki tüm klasör ve dosya yolları tek yerde.

    data/recordings/   mikrofondan alınan test kayıtları
    data/outputs/      dönüştürülmüş sesler (kayıt adıyla eşleşir)
    config/config.json son ayarlar, cihazlar, kısayollar
    config/presets/    kayıtlı ses presetleri
    models/shared/     tüm seslerin ortak modelleri (içerik kodlayıcı, perde)
    models/voices/<id> ses paketleri (voice.json, model.onnx, model.index, preview.wav)
"""

from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RECORDINGS_DIR = DATA_DIR / "recordings"
OUTPUTS_DIR = DATA_DIR / "outputs"
CONFIG_DIR = ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "config.json"
PRESETS_DIR = CONFIG_DIR / "presets"
MODELS_DIR = ROOT / "models"
SHARED_MODELS_DIR = MODELS_DIR / "shared"
VOICES_DIR = MODELS_DIR / "voices"


def ensure_dirs() -> None:
    for folder in (RECORDINGS_DIR, OUTPUTS_DIR, PRESETS_DIR, SHARED_MODELS_DIR, VOICES_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def new_recording_path() -> Path:
    return RECORDINGS_DIR / f"kayit_{datetime.now():%Y%m%d_%H%M%S}.wav"


def list_recordings() -> list[Path]:
    """En yeni kayıt başta olacak şekilde."""
    return sorted(RECORDINGS_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)


def output_path(recording: Path, kind: str) -> Path:
    """Örn. data/outputs/kayit_20261004_211500_psola.wav"""
    return OUTPUTS_DIR / f"{recording.stem}_{kind}.wav"
