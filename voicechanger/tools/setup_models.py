"""Ortak modelleri (models/shared) kontrol eder; eksik/bozuk olanı indirir ve sha256 ile doğrular.

    python -m voicechanger.tools.setup_models          # gerekenler (içerik kodlayıcı + seçili perde modeli)
    python -m voicechanger.tools.setup_models --all    # isteğe bağlı olanlar dahil (rmvpe)
"""

from __future__ import annotations

import argparse
import sys

from voicechanger import paths, settings as config
from voicechanger.ai.download import DownloadError, download
from voicechanger.ai.shared import SHARED_MODELS
from voicechanger.ai.voices import sha256_file


def main() -> int:
    ap = argparse.ArgumentParser(description="Ortak AI modellerini kur/doğrula")
    ap.add_argument("--all", action="store_true", help="isteğe bağlı modelleri de kur")
    args = ap.parse_args()
    paths.ensure_dirs()
    pitch = config.load_config()["ai"].get("pitch_method", "fcpe")
    wanted = list(SHARED_MODELS) if args.all else ["contentvec", pitch]
    failed = False
    for name in wanted:
        model = SHARED_MODELS[name]
        label = f"{model.file} ({model.license})"
        if model.path.is_file() and (not model.sha256 or sha256_file(model.path) == model.sha256):
            print(f"  ✓ {label}")
            continue
        if model.path.is_file():
            print(f"  ! {model.file} bozuk (sha256 tutmuyor), yeniden indirilecek")
        if not model.url:
            print(f"  ✗ {model.file}: indirme adresi henüz yok (GitHub Releases kurulunca eklenecek)")
            failed = True
            continue
        print(f"  ↓ {label} indiriliyor…")

        def progress(done: int, total: int) -> None:
            if total:
                print(f"\r     {done / 2**20:6.1f} / {total / 2**20:.1f} MB", end="", flush=True)

        try:
            download(model.url, model.path, model.sha256, progress)
            print(f"\r  ✓ {label}                    ")
        except DownloadError as exc:
            print(f"\n  ✗ {exc}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
