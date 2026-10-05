"""Release zip'i üretir (bakımcı aracı; docs/DECISIONS.md D52, D54).

    .venv\\Scripts\\python launcher\\build_release.py [--model-url-taban URL] [--kuru]

Çıktı: data/release/Wichelberg-<sürüm>.zip →
    Wichelberg/Wichelberg.exe                 başlatıcı (PyInstaller, data/build/venv'de derlenir)
    Wichelberg/_wichelberg/kurulum.json       Python + paketler + ortak modeller: adres, sha256, boyut (kilitli)
    Wichelberg/_wichelberg/voicechanger/*.pyc derlenmiş uygulama kodu (.py kaynağı yok)
    Wichelberg/_wichelberg/LISANSLAR.txt      üçüncü taraf lisansları
    Wichelberg/_wichelberg/(python311.dll…)   başlatıcının kendi dosyaları (PyInstaller; tek klasör düzeyi şart)

Adımlar:
  1. requirements.txt → Windows / CPython 3.11 için tüm paketler (bağımlılıklar dahil) hazır wheel olarak indirilir,
     her birinin PyPI adresi + sha256'sı kurulum.json'a yazılır (kullanıcı bilgisayarında derleme olmaz).
  2. Python: python-build-standalone (aşağıda sabit sürüm), sha256 doğrulanır.
  3. Uygulama kodu Python 3.11 ile .pyc'ye derlenir (sürüm aynı olmalı: kullanıcının Python'u da 3.11).
  4. Başlatıcı PyInstaller ile derlenir; hepsi zip'lenir.
PyInstaller ve derleme ortamı data/build/venv'de: uygulamanın .venv'ine girmez (D54).
"""

from __future__ import annotations

import argparse
import compileall
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voicechanger import __version__  # noqa: E402
from voicechanger.ai.shared import SHARED_MODELS  # noqa: E402

BUILD = ROOT / "data" / "build"
RELEASE = ROOT / "data" / "release"
BUILD_VENV = BUILD / "venv"
APP_DIR = "_wichelberg"
SHARED_FOR_RELEASE = ("contentvec", "fcpe")   # rmvpe dağıtılmaz (D50)

# python-build-standalone (Astral; Python PSF lisansı, derleme betikleri BSD-3). uv de bu paketleri kullanır.
PYTHON = {
    "version": "3.11.17",
    "file": "cpython-3.11.17+20261003-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
    "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/"
           "cpython-3.11.17%2B20261003-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
    "sha256": "861f9a03b0c4ca537da1754ed0556e0628dd2114a1be36e8aae6b1e2bb1304a0",
    "size": 25222085,
    "license": "PSF-2.0 (python-build-standalone: BSD-3-Clause)",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "WichelbergBuild/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


# ------------------------------------------------------------------ 1) paketler
def lock_wheels() -> list[dict]:
    wheels = BUILD / "wheels"
    shutil.rmtree(wheels, ignore_errors=True)
    wheels.mkdir(parents=True)
    subprocess.run([sys.executable, "-m", "pip", "download", "-q", "-r", str(ROOT / "requirements.txt"),
                    "--only-binary=:all:", "--platform", "win_amd64", "--python-version", "3.11",
                    "--implementation", "cp", "--abi", "cp311", "-d", str(wheels)], check=True)
    out = []
    for whl in sorted(wheels.glob("*.whl")):
        name, version = whl.name.split("-")[:2]
        meta = get_json(f"https://pypi.org/pypi/{name}/{version}/json")
        entry = next((u for u in meta["urls"] if u["filename"] == whl.name), None)
        if entry is None:
            sys.exit(f"{whl.name} PyPI'da bulunamadı")
        digest = sha256(whl)
        if entry["digests"]["sha256"] != digest:
            sys.exit(f"{whl.name}: PyPI sha256 ile indirilen tutmuyor")
        info = meta["info"]
        lic = _license(info)
        out.append({"name": info["name"], "version": version, "file": whl.name, "url": entry["url"],
                    "sha256": digest, "size": whl.stat().st_size, "license": lic})
        print(f"  {info['name']:24s} {version:12s} {whl.stat().st_size / 2**20:6.1f} MB  {lic}")
    return out


def _license(info: dict) -> str:
    if info.get("license_expression"):
        return info["license_expression"]
    classifiers = [c.split(" :: ")[-1] for c in info.get("classifiers", []) if c.startswith("License ::")]
    if classifiers:
        return ", ".join(classifiers)
    text = (info.get("license") or "").strip()
    return text.splitlines()[0][:60] if text else "?"


# ------------------------------------------------------------------ 2) Python
def check_python() -> None:
    cache = BUILD / "cache" / PYTHON["file"]
    if not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        print(f"  Python indiriliyor: {PYTHON['url']}")
        req = urllib.request.Request(PYTHON["url"], headers={"User-Agent": "WichelbergBuild/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(cache, "wb") as fh:
            shutil.copyfileobj(resp, fh)
    if sha256(cache) != PYTHON["sha256"] or cache.stat().st_size != PYTHON["size"]:
        sys.exit("Python arşivi sha256/boyut tutmuyor")
    print(f"  Python {PYTHON['version']} ✓ ({PYTHON['size'] / 2**20:.1f} MB)")


# ------------------------------------------------------------------ 3) uygulama kodu
def compile_app(dest: Path) -> list[str]:
    if sys.version_info[:2] != (3, 11):
        sys.exit("Uygulama kodu Python 3.11 ile derlenmeli (kullanıcıdaki Python 3.11)")
    src = ROOT / "voicechanger"
    target = dest / "voicechanger"
    shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if not compileall.compile_dir(str(target), legacy=True, quiet=1, force=True):
        sys.exit("derleme hatası")
    files = []
    for py in sorted(target.rglob("*.py")):
        py.unlink()
    for pyc in sorted(target.rglob("*.pyc")):
        files.append(pyc.relative_to(dest).as_posix())
    return files


# ------------------------------------------------------------------ simge
def _png(rgba: np.ndarray) -> bytes:
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def make_icon(path: Path) -> None:
    """Yuvarlak köşeli mor-mavi kare + beyaz ses dalgası çubukları (256 px, küçük boylar ondan)."""
    n = 256
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) + 0.5
    r = 56.0
    dx = np.maximum(np.maximum(r - x, x - (n - r)), 0)
    dy = np.maximum(np.maximum(r - y, y - (n - r)), 0)
    inside = np.clip(r - np.hypot(dx, dy) + 0.5, 0, 1)
    t = (x + y) / (2 * n)
    top, bottom = np.array([124, 58, 237]), np.array([37, 99, 235])
    rgb = top * (1 - t[..., None]) + bottom * t[..., None]
    alpha = inside
    heights = [0.22, 0.42, 0.66, 0.42, 0.22]
    bar_w, gap = 22, 14
    x0 = (n - (len(heights) * bar_w + (len(heights) - 1) * gap)) / 2
    white = np.zeros((n, n), np.float32)
    for i, hgt in enumerate(heights):
        cx = x0 + i * (bar_w + gap) + bar_w / 2
        half = hgt * n / 2
        d = np.maximum(np.abs(y - n / 2) - (half - bar_w / 2), 0)
        white = np.maximum(white, np.clip(bar_w / 2 - np.hypot(np.abs(x - cx), d) + 0.5, 0, 1))
    rgb = rgb * (1 - white[..., None]) + 255 * white[..., None]
    img = np.dstack([rgb, alpha * 255]).round().clip(0, 255).astype(np.uint8)
    sizes = [256, 64, 32, 16]
    pngs = []
    for s in sizes:
        f = n // s
        small = img.astype(np.float32).reshape(s, f, s, f, 4).mean(axis=(1, 3)).round().astype(np.uint8)
        pngs.append(_png(np.ascontiguousarray(small)))
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, data = b"", b""
    for s, p in zip(sizes, pngs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(p), offset + len(data))
        data += p
    path.write_bytes(header + entries + data)


# ------------------------------------------------------------------ lisanslar
def licenses_text(wheels: list[dict], models: list[dict]) -> str:
    lines = ["Wichelberg Voice Changer — üçüncü taraf bileşenleri ve lisansları", "",
             f"Python {PYTHON['version']} — {PYTHON['license']}",
             "PyInstaller başlatıcısı — GPL-2.0-or-later, önyükleyici istisnasıyla (dağıtıma izin verir)", "",
             "Paketler (kurulumda PyPI'dan iner):"]
    lines += [f"  {w['name']} {w['version']} — {w['license']}" for w in wheels]
    lines += ["", "Ortak AI modelleri:"]
    lines += [f"  {m['file']} — {m['license']} — {m['source']}" for m in models]
    lines += ["", "Ses modellerinin her birinin lisansı kendi voice.json dosyasındadır; lisansı veya kaynağı boş",
              "olan ses program tarafından yüklenmez. Gerçek kişilerin sesleri sadece rızalarıyla kullanılabilir."]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ ana akış
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-url-taban", help="ortak modellerin indirme adresi (sonuna dosya adı eklenir); "
                                               "verilmezse voicechanger/ai/shared.py'deki url kullanılır")
    a = ap.parse_args()
    pyinstaller = BUILD_VENV / "Scripts" / "pyinstaller.exe"
    if not pyinstaller.is_file():
        sys.exit("Derleme ortamı yok: py -3.11 -m venv data\\build\\venv && "
                 "data\\build\\venv\\Scripts\\python -m pip install pyinstaller sv-ttk==2.6.1")

    print(f"Wichelberg {__version__}\n1) Paketler")
    wheels = lock_wheels()
    print("2) Python")
    check_python()
    models = []
    for name in SHARED_FOR_RELEASE:
        m = SHARED_MODELS[name]
        url = (a.model_url_taban.rstrip("/") + "/" + m.file) if a.model_url_taban else m.url
        models.append({"name": m.name, "version": "", "file": m.file, "url": url, "sha256": m.sha256,
                       "size": m.size_bytes, "license": m.license, "source": m.source})
    print("3) Ortak modeller: " + ", ".join(f"{m['file']} ({'adres var' if m['url'] else 'ADRES YOK'})"
                                            for m in models))

    staging = BUILD / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    app = staging / APP_DIR
    app.mkdir(parents=True)
    print("4) Uygulama kodu derleniyor (.pyc)")
    app_files = compile_app(app)
    icon = BUILD / "wichelberg.ico"
    make_icon(icon)
    shutil.copy2(icon, app / "wichelberg.ico")
    manifest = {"surum": __version__, "python": {k: v for k, v in PYTHON.items() if k != "license"},
                "paketler": wheels, "modeller": [{k: v for k, v in m.items() if k != "source"} for m in models],
                "uygulama_dosyalari": app_files}
    (app / "kurulum.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (app / "LISANSLAR.txt").write_text(licenses_text(wheels, models), encoding="utf-8")

    print("5) Başlatıcı derleniyor (PyInstaller)")
    dist, work = BUILD / "dist", BUILD / "work"
    shutil.rmtree(dist, ignore_errors=True)
    subprocess.run([str(pyinstaller), "--noconfirm", "--clean", "--onedir", "--windowed", "--name", "Wichelberg",
                    "--contents-directory", APP_DIR, "--icon", str(icon),
                    "--add-data", f"{icon};.", "--collect-data", "sv_ttk", "--log-level", "WARN",
                    "--distpath", str(dist), "--workpath", str(work), "--specpath", str(BUILD),
                    str(ROOT / "launcher" / "wichelberg.py")], check=True)
    out = dist / "Wichelberg"
    if not (out / "Wichelberg.exe").is_file() or not (out / APP_DIR).is_dir():
        sys.exit(f"PyInstaller çıktısı beklenen yerde değil: {out}")
    for item in app.iterdir():
        target = out / APP_DIR / item.name
        if target.exists():
            if target.is_file() and item.is_file() and sha256(target) == sha256(item):
                continue
            sys.exit(f"çakışma: {target}")
        shutil.move(str(item), target)

    print("6) Zip")
    RELEASE.mkdir(parents=True, exist_ok=True)
    zip_path = RELEASE / f"Wichelberg-{__version__}.zip"
    zip_path.unlink(missing_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, Path("Wichelberg") / f.relative_to(out))
                count += 1
    shutil.copy2(ROOT / "launcher" / "RELEASE_README.md", RELEASE / "README.md")  # release reposunun README'si
    total_dl = PYTHON["size"] + sum(w["size"] for w in wheels) + sum(m["size"] for m in models)
    print(f"\n✓ {zip_path.relative_to(ROOT)}  {zip_path.stat().st_size / 2**20:.1f} MB, {count} dosya")
    print(f"  İlk açılışta inecek: {total_dl / 2**20:.0f} MB (Python {PYTHON['size'] / 2**20:.0f} + "
          f"{len(wheels)} paket {sum(w['size'] for w in wheels) / 2**20:.0f} + modeller "
          f"{sum(m['size'] for m in models) / 2**20:.0f})")
    print(f"  sha256: {sha256(zip_path)}")


if __name__ == "__main__":
    main()
