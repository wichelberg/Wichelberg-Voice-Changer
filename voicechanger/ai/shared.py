"""Tüm seslerin ortak kullandığı modeller (models/shared/). Tek kopya; ses paketleri bunları taşımaz.

Dosyalar repoya girmez. Kurulum (başlatıcı) ve Ses Kütüphanesi bunları `url`'den (public Hugging Face, D50) indirir ve sha256 ile doğrular.
Nasıl üretildikleri: training/export_onnx.py (kaynak checkpoint ve lisans aşağıda).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import paths


@dataclass(frozen=True)
class SharedModel:
    name: str
    file: str
    sha256: str
    size_bytes: int
    url: str          # GitHub Releases (repo henüz yok: boş) — bkz. DECISIONS.md
    license: str
    source: str

    @property
    def path(self) -> Path:
        return paths.SHARED_MODELS_DIR / self.file


SHARED_MODELS: dict[str, SharedModel] = {
    "contentvec": SharedModel(
        name="contentvec", file="contentvec.onnx",
        sha256="41b51e0ffbb70ff45ed313e8d751f5996ee5e34eb2e308e66c58783124e12d10",
        size_bytes=377687460, url="",
        license="MIT",
        source="ContentVec (auspicious3000/contentvec), HF: lengyue233/content-vec-best; "
               "RVC v2 hubert_base ile aynı ağırlıklar",
    ),
    "rmvpe": SharedModel(
        name="rmvpe", file="rmvpe.onnx",
        sha256="8ca13c4310a7f245f2d5a55e6035e305dfe2827d5c2951e62451f5890d758ca2",
        size_bytes=366160506, url="",
        license="Kod Apache-2.0 (Dream-High/RMVPE); ağırlık: lj1995/VoiceConversionWebUI (MIT + 'yalnızca araştırma' notu)",
        source="HF: lj1995/VoiceConversionWebUI rmvpe.pt",
    ),
    "fcpe": SharedModel(
        name="fcpe", file="fcpe.onnx",
        sha256="d184325f15260c9321730b2e2d04101ce2b8416094e1c4625675c57335836aeb",
        size_bytes=47803546, url="",
        license="MIT",
        source="torchfcpe 0.0.4 (CNChTu/FCPE) içindeki fcpe_c_v001.pt",
    ),
}


class SharedModelError(Exception):
    pass


def shared_path(name: str) -> Path:
    model = SHARED_MODELS[name]
    if not model.path.is_file():
        raise SharedModelError(f"Ortak model eksik: {model.file}. Ses Kütüphanesi → \"Ortak modelleri indir\".")
    return model.path


def missing() -> list[SharedModel]:
    return [m for m in SHARED_MODELS.values() if not m.path.is_file()]


def verify(name: str) -> bool:
    from .voices import sha256_file

    model = SHARED_MODELS[name]
    return model.path.is_file() and (not model.sha256 or sha256_file(model.path) == model.sha256)
