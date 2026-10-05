"""Dosya indirme + sha256 doğrulama (ortak modeller, ileride ses kataloğu).

Önce `<hedef>.part`'a indirir, sha256 tutarsa tek adımda yerine koyar: yarım/bozuk dosya asla hedefte kalmaz.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path
from typing import Callable

USER_AGENT = "WichelbergVoiceChanger/1.0"


class DownloadError(Exception):
    pass


def download(url: str, dest: Path, sha256: str, progress: Callable[[int, int], None] | None = None,
             timeout: float = 30.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, open(part, "wb") as fh:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(1 << 20):
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise DownloadError(f"İndirilemedi: {url} ({exc})") from None
    if sha256 and digest.hexdigest() != sha256.lower():
        part.unlink(missing_ok=True)
        raise DownloadError(f"{dest.name}: sha256 tutmuyor (dosya bozuk veya değiştirilmiş)")
    os.replace(part, dest)
