"""Ses Kütüphanesi: ses paketini (zip veya klasör) içe aktar, sil (docs/DECISIONS.md D11, D49).

Sesler kullanıcıya özelden gönderilir; program indirmez. İçe aktarma:
  1. zip içinde voice.json bulunur (kökte veya tek bir klasörün içinde, ör. `yasli_kadin/voice.json`),
  2. sadece o klasördeki dosyalar geçici bir klasöre çıkarılır (`..`/mutlak yol içeren zip reddedilir),
  3. voice.json doğrulanır (license/source boşsa reddedilir) ve her dosyanın sha256'sı kontrol edilir,
  4. her şey tutarsa tek adımda models/voices/<id> olarak yerine konur. Yarım/bozuk paket asla yerinde kalmaz.
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .. import paths
from .voices import Voice, VoiceError, load_voice, parse_manifest

STAGING = ".ice_aktarma"     # models/voices/.ice_aktarma/<id> (noktalı klasörleri scan_voices atlar)
TRASH = ".silinecek"
MAX_UNPACKED_BYTES = 2 * 2**30


@dataclass
class ImportPreview:
    """İçe aktarmadan önce kullanıcıya gösterilecek bilgiler."""
    voice: Voice                 # voice.json'dan (dosyalar henüz doğrulanmadı)
    existing: Voice | None       # aynı id ile kurulu ses (varsa: güncelleme / değiştirme)
    size_bytes: int


def _voices_root() -> Path:
    paths.VOICES_DIR.mkdir(parents=True, exist_ok=True)
    return paths.VOICES_DIR


def _existing(voice_id: str) -> Voice | None:
    folder = _voices_root() / voice_id
    if not folder.is_dir():
        return None
    try:
        return load_voice(folder, check_files=False)
    except VoiceError:
        return None


def _safe_member(name: str) -> PurePosixPath:
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]):
        raise VoiceError(f"Zip güvenli değil (geçersiz yol: {name})")
    return p


def _zip_layout(z: zipfile.ZipFile) -> tuple[zipfile.ZipInfo, list[zipfile.ZipInfo]]:
    """voice.json ve onunla aynı klasördeki dosyalar."""
    infos = [i for i in z.infolist() if not i.is_dir()]
    manifests = [i for i in infos if _safe_member(i.filename).name == "voice.json"]
    manifests = [i for i in manifests if len(_safe_member(i.filename).parts) <= 2]
    if len(manifests) != 1:
        raise VoiceError("Zip'te tek bir voice.json bulunmalı (kökte veya tek bir klasörün içinde). "
                         "Bu bir ses paketi değil gibi görünüyor.")
    base = _safe_member(manifests[0].filename).parent
    members = [i for i in infos if _safe_member(i.filename).parent == base]
    if sum(i.file_size for i in members) > MAX_UNPACKED_BYTES:
        raise VoiceError("Paket çok büyük (2 GB üstü).")
    return manifests[0], members


def _read_manifest_from(source: Path) -> tuple[dict, int]:
    if source.is_dir():
        manifest = source / "voice.json"
        if not manifest.is_file():
            raise VoiceError("Klasörde voice.json yok.")
        size = sum(p.stat().st_size for p in source.iterdir() if p.is_file())
        return json.loads(manifest.read_text(encoding="utf-8")), size
    try:
        with zipfile.ZipFile(source) as z:
            manifest, members = _zip_layout(z)
            data = json.loads(z.read(manifest))
            return data, sum(i.file_size for i in members)
    except zipfile.BadZipFile:
        raise VoiceError("Dosya bir zip değil veya bozuk.") from None
    except (KeyError, ValueError) as exc:
        raise VoiceError(f"voice.json okunamadı: {exc}") from None


def inspect(source: Path) -> ImportPreview:
    """Paketi açmadan bilgilerini oku (license/source boşsa burada reddedilir)."""
    data, size = _read_manifest_from(Path(source))
    voice_id = str(data.get("id", "")).strip() if isinstance(data, dict) else ""
    voice = parse_manifest(data, _voices_root() / (voice_id or "_"))
    return ImportPreview(voice=voice, existing=_existing(voice.id), size_bytes=size)


def import_voice(source: Path, progress=None) -> Voice:
    """Paketi doğrulayıp models/voices/<id> olarak kur. Aynı id varsa yerine geçer (çağıran önce sormalı).

    progress(metin) arka plan iş parçacığından çağrılır.
    """
    source = Path(source)
    preview = inspect(source)
    voice_id = preview.voice.id
    root = _voices_root()
    staging = root / STAGING / voice_id
    shutil.rmtree(staging.parent, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        say = progress or (lambda _t: None)
        say("Dosyalar çıkarılıyor…")
        if source.is_dir():
            for p in source.iterdir():
                if p.is_file():
                    shutil.copy2(p, staging / p.name)
        else:
            with zipfile.ZipFile(source) as z:
                _manifest, members = _zip_layout(z)
                for info in members:
                    name = _safe_member(info.filename).name
                    with z.open(info) as src, open(staging / name, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
        say("sha256 doğrulanıyor…")
        load_voice(staging, check_files=True)       # license/source + her dosyanın sha256'sı
        say("Kuruluyor…")
        target = root / voice_id
        if target.exists():
            trash = root / TRASH / voice_id
            shutil.rmtree(trash, ignore_errors=True)
            trash.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, trash)
            os.replace(staging, target)
            shutil.rmtree(root / TRASH, ignore_errors=True)
        else:
            os.replace(staging, target)
        return load_voice(target, check_files=False)
    finally:
        shutil.rmtree(root / STAGING, ignore_errors=True)


def delete_voice(voice_id: str) -> None:
    root = _voices_root()
    target = root / voice_id
    if not target.is_dir() or target.parent != root:
        raise VoiceError(f"Ses bulunamadı: {voice_id}")
    trash = root / TRASH / voice_id
    shutil.rmtree(trash, ignore_errors=True)
    trash.parent.mkdir(parents=True, exist_ok=True)
    os.replace(target, trash)                # önce taşı: yarım silinmiş ses listede görünmesin
    shutil.rmtree(root / TRASH, ignore_errors=True)


def folder_size(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.iterdir() if p.is_file()) if folder.is_dir() else 0
