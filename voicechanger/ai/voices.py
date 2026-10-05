"""Ses paketleri: models/voices/<id>/voice.json (+ model.onnx, model.index, preview.wav).

Kurallar (docs/DECISIONS.md D11):
- `license` veya `source` boşsa ses yüklenmez.
- `files` içindeki her dosyanın sha256'sı tutmalı; `id` klasör adıyla aynı olmalı.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import paths

SCHEMA_VERSION = 1
MODEL_TYPES = {"rvc_v2"}          # ileride: "meanvc2" vb. (D10)
EMBEDDERS = {"contentvec_768"}
ID_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
MODEL_FILE = "model.onnx"
INDEX_FILE = "model.index"
PREVIEW_FILE = "preview.wav"

REQUIRED_TEXT = ("id", "display_name", "version", "author", "license", "source")


class VoiceError(Exception):
    """Ses paketi geçersiz; mesaj kullanıcıya gösterilir (Türkçe)."""


@dataclass
class VoiceFile:
    name: str
    sha256: str


@dataclass
class Voice:
    folder: Path
    id: str
    display_name: str
    version: str
    author: str
    description: str
    model_type: str
    embedder: str
    sample_rate: int
    target_f0_median: float
    default_index_rate: float
    license: str
    source: str
    consent_note: str
    files: list[VoiceFile] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    @property
    def model_path(self) -> Path:
        return self.folder / MODEL_FILE

    @property
    def index_path(self) -> Path | None:
        path = self.folder / INDEX_FILE
        return path if path.is_file() and any(f.name == INDEX_FILE for f in self.files) else None

    @property
    def preview_path(self) -> Path | None:
        path = self.folder / PREVIEW_FILE
        return path if path.is_file() else None

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version, "id": self.id, "display_name": self.display_name,
            "version": self.version, "author": self.author, "description": self.description,
            "model_type": self.model_type, "embedder": self.embedder, "sample_rate": self.sample_rate,
            "target_f0_median": self.target_f0_median, "default_index_rate": self.default_index_rate,
            "license": self.license, "source": self.source, "consent_note": self.consent_note,
            "files": [{"name": f.name, "sha256": f.sha256} for f in self.files],
        }


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def parse_manifest(data: dict, folder: Path) -> Voice:
    """voice.json içeriğini doğrula. Dosyalara bakmaz (bkz. verify_files)."""
    if not isinstance(data, dict):
        raise VoiceError("voice.json bir nesne olmalı")
    schema = data.get("schema_version", SCHEMA_VERSION)
    if schema != SCHEMA_VERSION:
        raise VoiceError(f"Desteklenmeyen voice.json sürümü: {schema} (beklenen {SCHEMA_VERSION})")
    for key in REQUIRED_TEXT:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            if key in ("license", "source"):
                raise VoiceError(f"'{key}' alanı boş: lisansı ve kaynağı belli olmayan ses yüklenmez")
            raise VoiceError(f"'{key}' alanı eksik veya boş")
    voice_id = data["id"].strip()
    if not ID_PATTERN.match(voice_id):
        raise VoiceError(f"Geçersiz id '{voice_id}': sadece a-z, 0-9 ve _ kullanılabilir")
    if folder.name != voice_id:
        raise VoiceError(f"Klasör adı ({folder.name}) id ile ({voice_id}) aynı olmalı")
    model_type = data.get("model_type", "rvc_v2")
    if model_type not in MODEL_TYPES:
        raise VoiceError(f"Desteklenmeyen model türü: {model_type}")
    embedder = data.get("embedder", "contentvec_768")
    if embedder not in EMBEDDERS:
        raise VoiceError(f"Desteklenmeyen içerik kodlayıcı: {embedder}")
    try:
        sample_rate = int(data["sample_rate"])
        target_f0 = float(data["target_f0_median"])
        index_rate = float(data.get("default_index_rate", 0.5))
    except (KeyError, TypeError, ValueError) as exc:
        raise VoiceError(f"Sayısal alan eksik veya hatalı: {exc}") from None
    if sample_rate not in (32000, 40000, 48000):
        raise VoiceError(f"Desteklenmeyen örnekleme hızı: {sample_rate}")
    if not 60.0 <= target_f0 <= 600.0:
        raise VoiceError(f"target_f0_median makul aralıkta değil: {target_f0} Hz")
    if not 0.0 <= index_rate <= 1.0:
        raise VoiceError("default_index_rate 0 ile 1 arasında olmalı")
    files = []
    for item in data.get("files") or []:
        try:
            name, digest = str(item["name"]), str(item["sha256"]).lower()
        except (KeyError, TypeError):
            raise VoiceError("files listesindeki her öğe {name, sha256} olmalı") from None
        if "/" in name or "\\" in name or name.startswith("."):
            raise VoiceError(f"Geçersiz dosya adı: {name}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise VoiceError(f"{name} için sha256 geçersiz")
        files.append(VoiceFile(name, digest))
    if not any(f.name == MODEL_FILE for f in files):
        raise VoiceError(f"files listesinde {MODEL_FILE} yok")
    return Voice(folder=folder, id=voice_id, display_name=data["display_name"].strip(),
                 version=data["version"].strip(), author=data["author"].strip(),
                 description=str(data.get("description", "")).strip(), model_type=model_type, embedder=embedder,
                 sample_rate=sample_rate, target_f0_median=target_f0, default_index_rate=index_rate,
                 license=data["license"].strip(), source=data["source"].strip(),
                 consent_note=str(data.get("consent_note", "")).strip(), files=files, schema_version=schema)


def verify_files(voice: Voice) -> None:
    for item in voice.files:
        path = voice.folder / item.name
        if not path.is_file():
            raise VoiceError(f"Dosya eksik: {item.name}")
        if sha256_file(path) != item.sha256:
            raise VoiceError(f"{item.name} bozuk veya değiştirilmiş (sha256 tutmuyor)")


def load_voice(folder: Path, check_files: bool = True) -> Voice:
    manifest = folder / "voice.json"
    if not manifest.is_file():
        raise VoiceError("voice.json bulunamadı")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VoiceError(f"voice.json okunamadı: {exc}") from None
    voice = parse_manifest(data, folder)
    if check_files:
        verify_files(voice)
    return voice


@dataclass
class VoiceEntry:
    """Kütüphane listesi için: yüklenebilen ses veya neden yüklenemediği."""
    folder: Path
    voice: Voice | None
    error: str | None


def scan_voices(root: Path | None = None, check_files: bool = False) -> list[VoiceEntry]:
    """models/voices altındaki paketler. sha256 kontrolü (yavaş) varsayılan olarak yükleme anına bırakılır."""
    root = root or paths.VOICES_DIR
    entries = []
    if not root.is_dir():
        return entries
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        try:
            entries.append(VoiceEntry(folder, load_voice(folder, check_files), None))
        except VoiceError as exc:
            entries.append(VoiceEntry(folder, None, str(exc)))
    return entries


def write_manifest(voice: Voice) -> None:
    (voice.folder / "voice.json").write_text(json.dumps(voice.to_dict(), ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
