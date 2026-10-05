"""Başlatıcının kurulum mantığı (arayüzsüz; docs/DECISIONS.md D52, D54).

Release klasörü:
    Wichelberg.exe
    _wichelberg/              (gizli) — uygulamanın kökü (voicechanger/paths.py ROOT)
        kurulum.json          derleme anında yazılır: Python, paketler, ortak modeller (url + sha256 + boyut)
        voicechanger/*.pyc    derlenmiş uygulama kodu (.py kaynağı yok)
        python/               ilk açılışta inen Python 3.11 (python-build-standalone)
        .venv/                uygulamanın ortamı; paketler sadece buraya
        models/ config/ data/ kullanıcının sesleri, ayarları, kayıtları (güncellemede korunur)
        .kurulum_durumu.json  neyin kurulu olduğu

Sisteme hiçbir şey kurulmaz: Python, paketler, modeller bu klasörün içine iner. İndirmeler önce `.part`'a yazılır,
sha256 tutarsa yerine konur; yarım kalan indirme bir sonraki denemede kaldığı yerden sürer.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = "_wichelberg"
MANIFEST = "kurulum.json"
STATE = ".kurulum_durumu.json"
USER_AGENT = "WichelbergKurulum/1.0"
CHUNK = 1 << 20
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class KurulumHatasi(Exception):
    """Kullanıcıya gösterilecek Türkçe hata."""


class Iptal(Exception):
    pass


@dataclass
class Dosya:
    name: str
    version: str
    file: str
    url: str
    sha256: str
    size: int
    license: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Dosya":
        return cls(name=d["name"], version=d.get("version", ""), file=d["file"], url=d.get("url", ""),
                   sha256=d["sha256"], size=int(d["size"]), license=d.get("license", ""))

    @property
    def key(self) -> str:
        return f"{self.name}=={self.version}"


class Yerlesim:
    """Klasör yolları. base = exe'nin bulunduğu klasör."""

    def __init__(self, base: Path):
        self.base = Path(base)
        self.app = self.base / APP_DIR
        self.manifest = self.app / MANIFEST
        self.state = self.app / STATE
        self.python_dir = self.app / "python"
        self.python = self.python_dir / "python.exe"
        self.venv = self.app / ".venv"
        self.venv_python = self.venv / "Scripts" / "python.exe"
        self.venv_pythonw = self.venv / "Scripts" / "pythonw.exe"
        self.downloads = self.app / "indirilenler"
        self.models = self.app / "models" / "shared"
        self.logs = self.app / "data" / "logs"


@dataclass
class Plan:
    python: bool = False
    venv: bool = False
    paketler: list = field(default_factory=list)       # indirilip kurulacak Dosya'lar
    modeller: list = field(default_factory=list)       # indirilecek (adresi olan) modeller
    adressiz_modeller: list = field(default_factory=list)  # eksik ama indirme adresi tanımlı değil

    @property
    def gerekli(self) -> bool:
        return self.python or self.venv or bool(self.paketler) or bool(self.modeller)


# --------------------------------------------------------------------------- okuma / plan
def manifest_oku(y: Yerlesim) -> dict:
    try:
        return json.loads(y.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise KurulumHatasi("Program dosyaları eksik veya bozuk. Zip'i baştan, tamamen bir klasöre çıkar "
                            "(zip'in içinden çalıştırma).") from None


def durum_oku(y: Yerlesim) -> dict:
    try:
        return json.loads(y.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def durum_yaz(y: Yerlesim, durum: dict) -> None:
    tmp = y.state.with_suffix(".tmp")
    tmp.write_text(json.dumps(durum, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, y.state)


def model_tamam(y: Yerlesim, m: Dosya) -> bool:
    path = y.models / m.file
    return path.is_file() and path.stat().st_size == m.size


def plan_cikar(y: Yerlesim, manifest: dict, durum: dict) -> Plan:
    py = Dosya.from_dict({"name": "python", **manifest["python"]})
    plan = Plan()
    plan.python = not y.python.is_file() or durum.get("python") != py.version
    plan.venv = plan.python or not y.venv_python.is_file()
    kurulu = set() if plan.venv else set(durum.get("paketler", []))
    plan.paketler = [p for p in map(Dosya.from_dict, manifest["paketler"]) if p.key not in kurulu]
    for m in map(Dosya.from_dict, manifest.get("modeller", [])):
        if not model_tamam(y, m):
            (plan.modeller if m.url else plan.adressiz_modeller).append(m)
    return plan


# --------------------------------------------------------------------------- klasör işleri
MAX_APP_PATH = 100  # .venv içindeki en uzun yol ~145 karakter; Windows sınırı 260 (uzun yol desteği kapalıyken)


def yol_cok_uzun(y: Yerlesim) -> bool:
    return len(str(y.app)) > MAX_APP_PATH


def yazilabilir_mi(y: Yerlesim) -> bool:
    try:
        y.app.mkdir(parents=True, exist_ok=True)
        probe = y.app / ".yazma_testi"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def gizle(path: Path) -> None:
    """Windows'ta klasörü gizli yap (Gezgin'de "gizli öğeler" kapalıyken görünmez)."""
    try:
        FILE_ATTRIBUTE_HIDDEN = 0x2
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs != -1 and not attrs & FILE_ATTRIBUTE_HIDDEN:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs | FILE_ATTRIBUTE_HIDDEN)
    except (AttributeError, OSError):
        pass


def eski_dosyalari_temizle(y: Yerlesim, manifest: dict) -> list[str]:
    """Güncellemeden sonra yeni sürümde olmayan uygulama dosyalarını sil (zip üstüne açılınca eskiler kalır)."""
    istenen = set(manifest.get("uygulama_dosyalari", []))
    if not istenen:
        return []
    silinen = []
    root = y.app / "voicechanger"
    for path in root.rglob("*"):
        rel = path.relative_to(y.app).as_posix()
        if path.is_file() and rel not in istenen and path.suffix in (".pyc", ".py"):
            path.unlink(missing_ok=True)
            silinen.append(rel)
    return silinen


def venv_yolunu_duzelt(y: Yerlesim) -> None:
    """Klasör taşındıysa .venv'in gösterdiği Python yolunu yenile (pyvenv.cfg → home)."""
    cfg = y.venv / "pyvenv.cfg"
    if not cfg.is_file() or not y.python.is_file():
        return
    lines = cfg.read_text(encoding="utf-8").splitlines()
    want = f"home = {y.python_dir}"
    new = [want if line.split("=")[0].strip() == "home" else line for line in lines]
    if new != lines:
        cfg.write_text("\n".join(new) + "\n", encoding="utf-8")


def bos_alan_bayt(y: Yerlesim) -> int:
    return shutil.disk_usage(y.base).free


def gereken_alan(plan: Plan, manifest: dict) -> int:
    """Kabaca: indirilen + açılmış hâli (Python ve paketler açılınca ~3-4 kat)."""
    py = int(manifest["python"]["size"]) if plan.python else 0
    paket = sum(p.size for p in plan.paketler)
    model = sum(m.size for m in plan.modeller)
    return py * 5 + paket * 4 + model + 200 * 2**20


# --------------------------------------------------------------------------- indirme
def indir(item: Dosya, hedef: Path, ilerleme, iptal: threading.Event, deneme: int = 3) -> None:
    """item.url → hedef. ilerleme(alınan_bayt_toplam). sha256 tutmazsa dosya silinir ve hata verilir."""
    hedef.parent.mkdir(parents=True, exist_ok=True)
    part = hedef.with_name(hedef.name + ".part")
    son_hata = None
    for i in range(deneme):
        try:
            _indir_bir(item, part, ilerleme, iptal)
            break
        except Iptal:
            raise
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            son_hata = exc
            time.sleep(min(5, 1 + 2 * i))
    else:
        raise KurulumHatasi(f"{item.file} indirilemedi. İnternet bağlantını kontrol edip \"Tekrar dene\"ye bas.\n"
                            f"({son_hata})")
    digest = hashlib.sha256()
    with open(part, "rb") as fh:
        while block := fh.read(CHUNK):
            digest.update(block)
    if digest.hexdigest() != item.sha256.lower():
        part.unlink(missing_ok=True)
        raise KurulumHatasi(f"{item.file} bozuk indi (sha256 tutmuyor). \"Tekrar dene\"ye bas.")
    os.replace(part, hedef)


def _indir_bir(item: Dosya, part: Path, ilerleme, iptal: threading.Event) -> None:
    have = part.stat().st_size if part.exists() else 0
    if have > item.size:
        part.unlink()
        have = 0
    if have == item.size:
        ilerleme(have)
        return
    headers = {"User-Agent": USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(item.url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        if have and getattr(resp, "status", 200) != 206:  # sunucu devam etmeyi desteklemiyor: baştan
            have = 0
        with open(part, "ab" if have else "wb") as fh:
            done = have
            ilerleme(done)
            while True:
                if iptal.is_set():
                    raise Iptal()
                block = resp.read(CHUNK)
                if not block:
                    break
                fh.write(block)
                done += len(block)
                ilerleme(done)
    if part.stat().st_size != item.size:
        raise OSError(f"eksik indi ({part.stat().st_size} / {item.size} bayt)")


# --------------------------------------------------------------------------- kurulum adımları
def _calistir(args: list, y: Yerlesim, log, iptal: threading.Event, hata: str) -> None:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONNOUSERSITE="1", PIP_CONFIG_FILE=os.devnull,
               PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_CACHE_DIR="1")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    proc = subprocess.Popen([str(a) for a in args], cwd=y.app, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            creationflags=NO_WINDOW)
    lines = []
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            lines.append(line)
            log(line)
        if iptal.is_set():
            proc.kill()
    code = proc.wait()
    if iptal.is_set():
        raise Iptal()
    if code != 0:
        raise KurulumHatasi(f"{hata}\n" + "\n".join(lines[-6:]))


def python_kur(y: Yerlesim, arsiv: Path, log, iptal: threading.Event) -> None:
    tmp = y.app / "python_yeni"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    with tarfile.open(arsiv, "r:gz") as tar:
        members = tar.getmembers()
        for i, member in enumerate(members):
            if iptal.is_set():
                raise Iptal()
            tar.extract(member, tmp, filter="data")
            if i % 400 == 0:
                log(f"   açılıyor… {i}/{len(members)}")
    src = tmp / "python"
    if not (src / "python.exe").is_file():
        raise KurulumHatasi("Python arşivi beklenen biçimde değil.")
    shutil.rmtree(y.venv, ignore_errors=True)       # eski Python'a bağlı ortam artık geçersiz
    shutil.rmtree(y.python_dir, ignore_errors=True)
    os.replace(src, y.python_dir)
    shutil.rmtree(tmp, ignore_errors=True)


def venv_kur(y: Yerlesim, log, iptal: threading.Event) -> None:
    shutil.rmtree(y.venv, ignore_errors=True)
    _calistir([y.python, "-m", "venv", y.venv], y, log, iptal, "Program ortamı (.venv) oluşturulamadı.")


def paket_kur(y: Yerlesim, wheel: Path, log, iptal: threading.Event) -> None:
    _calistir([y.venv_python, "-m", "pip", "install", "--no-index", "--no-deps", "--no-warn-script-location",
               wheel], y, log, iptal, f"{wheel.name} kurulamadı.")


def vbcable_var_mi(y: Yerlesim) -> bool | None:
    """CABLE Input çıkış cihazı var mı (None: kontrol edilemedi)."""
    code = ("import sounddevice as sd; "
            "print(any('CABLE Input' in d['name'] and d['max_output_channels'] > 0 for d in sd.query_devices()))")
    try:
        out = subprocess.run([str(y.venv_python), "-c", code], cwd=y.app, capture_output=True, text=True,
                             timeout=30, creationflags=NO_WINDOW)
        return out.stdout.strip().endswith("True") if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------------------- programı aç
PROGRAM_TITLE = "Wichelberg Voice Changer"   # voicechanger/gui/app.py pencere başlığı


def program_penceresi() -> int:
    """Açık program penceresi (yoksa 0)."""
    try:
        return ctypes.windll.user32.FindWindowW(None, PROGRAM_TITLE)
    except (AttributeError, OSError):
        return 0


def one_getir(hwnd: int) -> None:
    try:
        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except (AttributeError, OSError):
        pass


def programi_baslat(y: Yerlesim) -> tuple[subprocess.Popen, Path]:
    """Programı ayrı süreçte aç (çıktısı data/logs/program.log'a)."""
    y.logs.mkdir(parents=True, exist_ok=True)
    log_path = y.logs / "program.log"
    env = dict(os.environ, PYTHONUTF8="1", PYTHONNOUSERSITE="1")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    exe = y.venv_pythonw if y.venv_pythonw.is_file() else y.venv_python
    with open(log_path, "w", encoding="utf-8") as log_fh:
        proc = subprocess.Popen([str(exe), "-m", "voicechanger"], cwd=y.app, env=env, stdout=log_fh,
                                stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    return proc, log_path


def kapanis_hatasi(proc: subprocess.Popen, log_path: Path) -> str | None:
    """Program hata ile kapandıysa günlüğün sonu; çalışıyorsa veya normal kapandıysa None."""
    code = proc.poll()
    if code is None or code == 0:
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    return "\n".join(text.strip().splitlines()[-15:]) or f"çıkış kodu {code}"


# --------------------------------------------------------------------------- tüm kurulum
ADIM_PYTHON, ADIM_PAKET, ADIM_MODEL, ADIM_CABLE = range(4)
BEKLIYOR, CALISIYOR, TAMAM, ATLANDI, HATA = "bekliyor", "calisiyor", "tamam", "atlandi", "hata"


class Rapor:
    """Arayüzün dinlediği olaylar (arka plan iş parçacığından çağrılır)."""

    def adim(self, no: int, durum: str, ayrinti: str = "") -> None: ...
    def ilerleme(self, oran: float, satir: str) -> None: ...
    def log(self, satir: str) -> None: ...


def _mb(n: float) -> str:
    return f"{n / 2**20:.1f} MB"


class _Sayac:
    """Bayt ağırlıklı genel ilerleme + indirme hızı / kalan süre."""

    def __init__(self, toplam: int, rapor: Rapor):
        self.toplam = max(1, toplam)
        self.bitti = 0
        self.rapor = rapor
        self._ornekler: list[tuple[float, int]] = []
        self._son = 0.0

    def indirme(self, item: Dosya, alinan: int) -> None:
        now = time.monotonic()
        if now - self._son < 0.1 and alinan < item.size:
            return
        self._son = now
        self._ornekler = [(t, b) for t, b in self._ornekler if now - t < 3.0] + [(now, alinan)]
        t0, b0 = self._ornekler[0]
        hiz = (alinan - b0) / (now - t0) if now - t0 > 0.3 else 0.0
        satir = f"↓ {item.name} {item.version}  {_mb(alinan)} / {_mb(item.size)}"
        if hiz > 0:
            satir += f"  ·  {hiz / 2**20:.1f} MB/sn  ·  kalan ~{max(0, item.size - alinan) / hiz:.0f} sn"
        self.rapor.ilerleme((self.bitti + alinan) / self.toplam, satir)

    def ekle(self, n: int, satir: str = "") -> None:
        self.bitti += n
        self._ornekler = []
        self.rapor.ilerleme(self.bitti / self.toplam, satir)


def kur(y: Yerlesim, manifest: dict, plan: Plan, rapor: Rapor, iptal: threading.Event) -> dict:
    """Planı uygula. Sonuç: {"vbcable": True/False/None}. Hata → KurulumHatasi, iptal → Iptal."""
    py = Dosya.from_dict({"name": "python", **manifest["python"]})
    durum = durum_oku(y)
    gerek = gereken_alan(plan, manifest)
    if bos_alan_bayt(y) < gerek:
        raise KurulumHatasi(f"Diskte yer yok: en az {gerek / 2**30:.1f} GB boş alan gerekiyor "
                            f"({y.base.anchor} sürücüsü).")
    # ağırlık: indirme = boyut, kurulum (açma / pip) = boyutun yarısı
    toplam = ((py.size * 3 // 2) if plan.python else 0) + sum(p.size * 3 // 2 for p in plan.paketler) \
        + sum(m.size for m in plan.modeller) + (5 * 2**20 if plan.venv else 0)
    sayac = _Sayac(toplam, rapor)
    log = rapor.log

    # 1) Python
    if plan.python or plan.venv:
        rapor.adim(ADIM_PYTHON, CALISIYOR, f"Python {py.version}")
        if plan.python:
            arsiv = y.downloads / py.file
            log(f"Python {py.version} indiriliyor ({_mb(py.size)}): {py.url}")
            indir(py, arsiv, lambda n: sayac.indirme(py, n), iptal)
            sayac.ekle(py.size, f"Python {py.version} açılıyor…")
            log("Python açılıyor (sadece bu klasöre; sisteme kurulmaz)…")
            python_kur(y, arsiv, log, iptal)
            arsiv.unlink(missing_ok=True)
            sayac.ekle(py.size // 2)
            durum.update(python=py.version, paketler=[])
            durum_yaz(y, durum)
        rapor.ilerleme(sayac.bitti / sayac.toplam, "Program ortamı (.venv) oluşturuluyor…")
        log("Program ortamı (.venv) oluşturuluyor…")
        venv_kur(y, log, iptal)
        sayac.ekle(5 * 2**20)
        durum["paketler"] = []
        durum_yaz(y, durum)
    rapor.adim(ADIM_PYTHON, TAMAM, f"Python {py.version}")

    # 2) Paketler: önce hepsini indir (ayrıntılı), sonra tek tek kur
    if plan.paketler:
        n = len(plan.paketler)
        rapor.adim(ADIM_PAKET, CALISIYOR, f"{n} paket indiriliyor")
        for i, p in enumerate(plan.paketler, 1):
            log(f"[{i}/{n}] {p.name} {p.version} indiriliyor ({_mb(p.size)}, lisans: {p.license or '?'})")
            indir(p, y.downloads / p.file, lambda b, p=p: sayac.indirme(p, b), iptal)
            sayac.ekle(p.size)
        kurulu = set(durum.get("paketler", []))
        for i, p in enumerate(plan.paketler, 1):
            rapor.adim(ADIM_PAKET, CALISIYOR, f"kuruluyor {i}/{n}: {p.name}")
            rapor.ilerleme(sayac.bitti / sayac.toplam, f"Kuruluyor: {p.name} {p.version}  ({i}/{n})")
            log(f"[{i}/{n}] {p.name} {p.version} kuruluyor…")
            paket_kur(y, y.downloads / p.file, log, iptal)
            (y.downloads / p.file).unlink(missing_ok=True)
            kurulu.add(p.key)
            durum["paketler"] = sorted(kurulu)
            durum_yaz(y, durum)
            sayac.ekle(p.size // 2)
    rapor.adim(ADIM_PAKET, TAMAM, f"{len(manifest['paketler'])} paket hazır")

    # 3) Ortak AI modelleri
    if plan.modeller:
        rapor.adim(ADIM_MODEL, CALISIYOR, f"{len(plan.modeller)} model indiriliyor")
        for m in plan.modeller:
            log(f"{m.file} indiriliyor ({_mb(m.size)}, lisans: {m.license}): {m.url}")
            indir(m, y.models / m.file, lambda b, m=m: sayac.indirme(m, b), iptal)
            sayac.ekle(m.size, f"✓ {m.file} doğrulandı")
            log(f"✓ {m.file} sha256 doğrulandı")
    if plan.adressiz_modeller:
        rapor.adim(ADIM_MODEL, ATLANDI, "indirme adresi yok: AI modu için gerekli, DSP modu çalışır")
        log("Ortak AI modellerinin indirme adresi bu sürümde tanımlı değil; atlandı.")
    else:
        rapor.adim(ADIM_MODEL, TAMAM, "hazır")

    # 4) VB-Cable
    rapor.adim(ADIM_CABLE, CALISIYOR, "kontrol ediliyor")
    cable = vbcable_var_mi(y)
    if cable:
        rapor.adim(ADIM_CABLE, TAMAM, "kurulu")
    else:
        rapor.adim(ADIM_CABLE, ATLANDI, "kurulu değil: programda nasıl kurulacağı anlatılıyor"
                   if cable is False else "kontrol edilemedi")
    shutil.rmtree(y.downloads, ignore_errors=True)
    durum.update(surum=manifest.get("surum"), tarih=time.strftime("%Y-%m-%d %H:%M"))
    durum_yaz(y, durum)
    rapor.ilerleme(1.0, "Kurulum tamamlandı.")
    return {"vbcable": cable}
