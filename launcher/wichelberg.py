"""Wichelberg.exe — başlatıcı (docs/DECISIONS.md D52, D54).

İlk açılışta (veya güncellemeden sonra paketler değiştiyse) kurulum ekranını gösterir: Python, paketler ve ortak
AI modelleri tek tek, boyut / hız / kalan süreyle iner. Kurulum bittiyse programı açar ve kapanır.
Program zaten açıksa yeni bir kopya açmaz, açık olanı öne getirir (iki kopya aynı anda CABLE'a yazmasın).

Geliştirme: python launcher/wichelberg.py --kok <release klasörü>
"""

from __future__ import annotations

import argparse
import ctypes
import os
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

import kurulum as k

VBCABLE_URL = "https://vb-audio.com/Cable/"
ACILIS_BEKLE_S = 40.0      # program penceresi bu süre içinde görünmezse başlatıcı yine de kapanır
ICONS = {k.BEKLIYOR: "○", k.CALISIYOR: "◐", k.TAMAM: "✓", k.ATLANDI: "!", k.HATA: "✗"}
COLORS = {"light": {"ok": "#0f7b0f", "warn": "#9d5d00", "error": "#c42b1c", "muted": "#5f5f5f",
                    "text": "#1c1c1c", "log": "#f3f3f3"},
          "dark": {"ok": "#6ccb5f", "warn": "#fce100", "error": "#ff99a4", "muted": "#a0a0a0",
                   "text": "#ffffff", "log": "#202020"}}


# --------------------------------------------------------------------------- tema
def _system_theme() -> str:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "light"


def _apply_theme(root: tk.Tk) -> dict:
    mode = _system_theme()
    try:
        import sv_ttk

        sv_ttk.set_theme(mode, root)
        root.tk.call("configure_colors")   # Tk 8.6.12: <<ThemeChanged>> köke gelmiyor (bkz. D53)
    except Exception:  # noqa: BLE001
        pass
    c = COLORS[mode]
    style = ttk.Style(root)
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 16))
    style.configure("Muted.TLabel", foreground=c["muted"])
    style.configure("Row.TLabel", font=("Segoe UI Semibold", 11))
    style.configure("Big.Accent.TButton", font=("Segoe UI Semibold", 11), padding=(16, 6))
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if mode == "dark" else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError):
        pass
    _set_icon(root)
    return c


def _set_icon(root: tk.Tk) -> None:
    icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "wichelberg.ico"
    if icon.is_file():
        try:
            root.iconbitmap(default=str(icon))
        except tk.TclError:
            pass


def _center(root: tk.Tk, w: int, h: int) -> None:
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight() - 80
    w, h = min(w, sw), min(h, sh)
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2)}")


# --------------------------------------------------------------------------- kurulum ekranı
class KurulumPenceresi(k.Rapor):
    ROWS = [("Python 3.11", "çalışma ortamı, sadece bu klasöre"),
            ("Program paketleri", "ses, AI ve arayüz kütüphaneleri"),
            ("Ortak AI modelleri", "ContentVec + FCPE (MIT)"),
            ("VB-Cable", "Discord / FiveM'e ses gönderen sanal kablo")]

    def __init__(self, root: tk.Tk, y: k.Yerlesim, manifest: dict, plan: k.Plan):
        self.root, self.y, self.manifest, self.plan = root, y, manifest, plan
        self.c = _apply_theme(root)
        root.title("Wichelberg Voice Changer — Kurulum")
        _center(root, 700, 640)
        root.minsize(600, 520)
        self._q: queue.Queue = queue.Queue()
        self._iptal = threading.Event()
        self._worker: threading.Thread | None = None
        self._details_open = False
        self._build()
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._poll()
        root.after(300, self.basla)

    # ---------------------------------------------------------------- arayüz
    def _build(self) -> None:
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(6, weight=1)
        head = ttk.Frame(r, padding=(24, 20, 24, 0))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Wichelberg Voice Changer", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, text=f"sürüm {self.manifest.get('surum', '?')}", style="Muted.TLabel").grid(
            row=0, column=1, sticky="e")
        py = self.manifest["python"]
        toplam = (int(py["size"]) if self.plan.python else 0) + sum(p.size for p in self.plan.paketler) \
            + sum(m.size for m in self.plan.modeller)
        ttk.Label(head, wraplength=640, justify="left", style="Muted.TLabel",
                  text=f"İlk açılış hazırlığı: gerekli dosyalar (~{toplam / 2**20:.0f} MB) bu klasöre iniyor. "
                       "Bilgisayarına başka hiçbir şey kurulmaz. İnternet hızına göre birkaç dakika sürer; "
                       "bir dahaki açılışta program doğrudan açılır.").grid(row=1, column=0, columnspan=2,
                                                                          sticky="w", pady=(6, 0))

        card = ttk.Frame(r, style="Card.TFrame", padding=(18, 14))
        card.grid(row=1, column=0, sticky="ew", padx=24, pady=(16, 0))
        card.columnconfigure(1, weight=1)
        sizes = [int(py["size"]) if self.plan.python else 0, sum(p.size for p in self.plan.paketler),
                 sum(m.size for m in self.plan.modeller), 0]
        counts = ["", f" ({len(self.manifest['paketler'])})", f" ({len(self.manifest.get('modeller', []))})", ""]
        self._icons, self._details = [], []
        for i, ((title, sub), size) in enumerate(zip(self.ROWS, sizes)):
            icon = ttk.Label(card, text=ICONS[k.BEKLIYOR], width=2, font=("Segoe UI", 14))
            icon.grid(row=2 * i, column=0, rowspan=2, sticky="nw", padx=(0, 10), pady=(4 if i else 0, 0))
            ttk.Label(card, text=title + counts[i], style="Row.TLabel").grid(row=2 * i, column=1, sticky="w",
                                                                           pady=(4 if i else 0, 0))
            ttk.Label(card, text=f"{size / 2**20:.0f} MB" if size else "", style="Muted.TLabel").grid(
                row=2 * i, column=2, sticky="e", pady=(4 if i else 0, 0))
            detail = ttk.Label(card, text=sub, style="Muted.TLabel")
            detail.grid(row=2 * i + 1, column=1, columnspan=2, sticky="w")
            self._icons.append(icon)
            self._details.append(detail)
        for no, done in ((k.ADIM_PYTHON, not (self.plan.python or self.plan.venv)),
                         (k.ADIM_PAKET, not self.plan.paketler)):
            if done:
                self.adim_ui(no, k.TAMAM, "zaten kurulu")

        self._line = ttk.Label(r, text="Hazırlanıyor…", padding=(24, 16, 24, 4))
        self._line.grid(row=2, column=0, sticky="w")
        self._bar = ttk.Progressbar(r, maximum=1.0)
        self._bar.grid(row=3, column=0, sticky="ew", padx=24)
        self._message = ttk.Label(r, wraplength=640, justify="left", padding=(24, 10, 24, 0))
        self._message.grid(row=4, column=0, sticky="w")

        tog = ttk.Frame(r, padding=(24, 8, 24, 0))
        tog.grid(row=5, column=0, sticky="ew")
        self._toggle = ttk.Button(tog, text="Ayrıntıları göster ▾", command=self._toggle_details)
        self._toggle.pack(side="left")
        self._log = tk.Text(r, height=10, wrap="word", state="disabled", font=("Consolas", 9),
                            background=self.c["log"], foreground=self.c["text"], borderwidth=0,
                            highlightthickness=0)
        self._log_frame_row = 6

        buttons = ttk.Frame(r, padding=(24, 12, 24, 20))
        buttons.grid(row=7, column=0, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        self._cable_button = ttk.Button(buttons, text="VB-Cable'ı indir", command=lambda: webbrowser.open(VBCABLE_URL))
        self._cancel = ttk.Button(buttons, text="İptal", command=self._close)
        self._cancel.grid(row=0, column=2, sticky="e")
        self._retry = ttk.Button(buttons, text="Tekrar dene", command=self.basla)
        self._open = ttk.Button(buttons, text="Programı aç", style="Big.Accent.TButton", command=self._ac)

    def _toggle_details(self) -> None:
        self._details_open = not self._details_open
        if self._details_open:
            self._log.grid(row=self._log_frame_row, column=0, sticky="nsew", padx=24, pady=(8, 0))
            self._toggle.config(text="Ayrıntıları gizle ▴")
        else:
            self._log.grid_remove()
            self._toggle.config(text="Ayrıntıları göster ▾")

    # ------------------------------------------------- Rapor (arka plandan)
    def adim(self, no: int, durum: str, ayrinti: str = "") -> None:
        self._q.put(lambda: self.adim_ui(no, durum, ayrinti))

    def ilerleme(self, oran: float, satir: str) -> None:
        self._q.put(lambda: self._ilerleme_ui(oran, satir))

    def log(self, satir: str) -> None:
        self._q.put(lambda: self._log_ui(satir))

    # ----------------------------------------------------------- ana iş parçacığı
    def adim_ui(self, no: int, durum: str, ayrinti: str) -> None:
        color = {k.TAMAM: self.c["ok"], k.HATA: self.c["error"], k.ATLANDI: self.c["warn"]}.get(durum, "")
        self._icons[no].config(text=ICONS[durum], foreground=color)
        if ayrinti:
            self._details[no].config(text=ayrinti, foreground=color or self.c["muted"])

    def _ilerleme_ui(self, oran: float, satir: str) -> None:
        self._bar["value"] = max(0.0, min(1.0, oran))
        if satir:
            self._line.config(text=satir)

    def _log_ui(self, satir: str) -> None:
        self._log.config(state="normal")
        self._log.insert("end", satir + "\n")
        self._log.see("end")
        self._log.config(state="disabled")

    def _poll(self) -> None:
        try:
            while True:
                try:
                    callback = self._q.get_nowait()
                except queue.Empty:
                    break
                try:
                    callback()
                except Exception as exc:  # noqa: BLE001 — bir hata ekranı dondurmasın
                    self._log_ui(f"(arayüz hatası: {exc!r})")
        finally:
            self.root.after(50, self._poll)

    def basla(self) -> None:
        if self._worker is not None:
            return
        self._retry.grid_remove()
        self._message.config(text="")
        self._cancel.config(text="İptal")
        self._iptal.clear()
        self.plan = k.plan_cikar(self.y, self.manifest, k.durum_oku(self.y))

        def work():
            try:
                sonuc = k.kur(self.y, self.manifest, self.plan, self, self._iptal)
                self._q.put(lambda: self._bitti(sonuc))
            except k.Iptal:
                self._q.put(self.root.destroy)
            except k.KurulumHatasi as exc:
                message = str(exc)  # `exc` except bloğundan sonra silinir: metni şimdi al
                self._q.put(lambda: self._hata(message))
            except Exception as exc:  # noqa: BLE001 — beklenmeyen hata da kullanıcıya gösterilsin
                message = f"Beklenmeyen hata: {exc!r}"
                self._q.put(lambda: self._hata(message))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _hata(self, text: str) -> None:
        self._worker = None
        for no, icon in enumerate(self._icons):
            if icon.cget("text") == ICONS[k.CALISIYOR]:
                self.adim_ui(no, k.HATA, "")
        self._line.config(text="Kurulum tamamlanamadı.")
        self._message.config(text=text, foreground=self.c["error"])
        self._log_ui("HATA: " + text)
        self._retry.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self._cancel.config(text="Kapat")

    def _bitti(self, sonuc: dict) -> None:
        self._worker = None
        self._bar["value"] = 1.0
        self._line.config(text="✓ Kurulum tamamlandı.")
        notes = []
        if sonuc.get("vbcable") is False:
            notes.append("VB-Cable kurulu değil: ses Discord'a gidemez. İndir, kur, bilgisayarı yeniden başlat "
                         "(adımlar programın ana ekranında da yazıyor).")
            self._cable_button.grid(row=0, column=0, sticky="w")
        if self.plan.adressiz_modeller:
            notes.append("Ortak AI modelleri bu sürümde indirilemedi (adres tanımlı değil). DSP modu çalışır; "
                         "AI modu için modeller gerekir.")
        self._message.config(text="\n".join(notes), foreground=self.c["warn"])
        self._cancel.grid_remove()
        self._open.grid(row=0, column=2, sticky="e")
        self._open.focus_set()

    def _ac(self) -> None:
        self.root.withdraw()
        AcilisPenceresi(self.root, self.y)

    def _close(self) -> None:
        if self._worker is not None:
            if not messagebox.askyesno("Kurulum", "Kurulum durdurulsun mu? Bir dahaki açılışta kaldığı yerden "
                                                  "devam eder."):
                return
            self._iptal.set()
            self._line.config(text="Durduruluyor…")
            return
        self.root.destroy()


# --------------------------------------------------------------------------- açılış / hata
class AcilisPenceresi:
    """Program açılırken küçük bekleme penceresi; program hata ile kapanırsa günlüğü gösterir."""

    def __init__(self, root: tk.Tk, y: k.Yerlesim):
        self.y = y
        self.win = tk.Toplevel(root) if root.state() == "withdrawn" else root
        self.root = root
        self.c = _apply_theme(root)
        self.win.title("Wichelberg — açılıyor")
        _center(self.win, 380, 130)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", root.destroy)
        frame = ttk.Frame(self.win, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Wichelberg Voice Changer açılıyor…", style="Row.TLabel").pack(anchor="w")
        bar = ttk.Progressbar(frame, mode="indeterminate")
        bar.pack(fill="x", pady=(14, 0))
        bar.start(12)
        self.proc, self.log_path = k.programi_baslat(y)
        self.started = time.monotonic()
        self._check()

    def _check(self) -> None:
        if k.program_penceresi():
            self.root.after(300, self.root.destroy)
            return
        error = k.kapanis_hatasi(self.proc, self.log_path)
        if error:
            HataPenceresi(self.root, self.y, error)   # bekleme penceresini de kaldırır
            return
        if self.proc.poll() is not None or time.monotonic() - self.started > ACILIS_BEKLE_S:
            self.root.destroy()
            return
        self.root.after(200, self._check)


class HataPenceresi:
    def __init__(self, root: tk.Tk, y: k.Yerlesim, error: str):
        self.root, self.y = root, y
        root.deiconify()
        for child in root.winfo_children():
            child.destroy()
        c = _apply_theme(root)
        root.title("Wichelberg — açılamadı")
        _center(root, 640, 420)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        ttk.Label(root, text="Program açılamadı", style="Title.TLabel", padding=(20, 18, 20, 4)).grid(
            row=0, column=0, sticky="w")
        ttk.Label(root, style="Muted.TLabel", wraplength=600, justify="left", padding=(20, 0, 20, 8),
                  text="Discord'a ses gitmiyor. \"Onar\" kurulumu baştan yapar (sesler ve ayarlar korunur). "
                       "Düzelmezse bu yazıyı, programı sana gönderen kişiye ilet.").grid(row=1, column=0,
                                                                                       sticky="w")
        text = tk.Text(root, wrap="word", font=("Consolas", 9), background=c["log"], foreground=c["text"],
                       borderwidth=0, highlightthickness=0)
        text.insert("1.0", error)
        text.config(state="disabled")
        text.grid(row=2, column=0, sticky="nsew", padx=20)
        buttons = ttk.Frame(root, padding=20)
        buttons.grid(row=3, column=0, sticky="e")
        ttk.Button(buttons, text="Onar", command=self._onar).pack(side="left")
        ttk.Button(buttons, text="Kapat", command=root.destroy).pack(side="left", padx=(8, 0))

    def _onar(self) -> None:
        self.y.state.unlink(missing_ok=True)       # Python + ortam + paketler yeniden kurulur
        shutil.rmtree(self.y.venv, ignore_errors=True)
        for child in self.root.winfo_children():
            child.destroy()
        manifest = k.manifest_oku(self.y)
        KurulumPenceresi(self.root, self.y, manifest, k.plan_cikar(self.y, manifest, {}))


# --------------------------------------------------------------------------- giriş
def _base_dir(args) -> Path:
    if args.kok:
        return Path(args.kok).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _hata_kutusu(text: str) -> None:
    root = tk.Tk()
    root.withdraw()
    _apply_theme(root)
    messagebox.showerror("Wichelberg — uyarı", text)
    root.destroy()


def main() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Wichelberg.VoiceChanger")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--kok", help="geliştirme: release klasörü (içinde _wichelberg olan)")
    args = ap.parse_args()
    y = k.Yerlesim(_base_dir(args))

    hwnd = k.program_penceresi()
    if hwnd:                       # program zaten açık: ikinci kopya açma (iki kopya CABLE'a yazmasın)
        k.one_getir(hwnd)
        return
    if not y.app.is_dir():
        _hata_kutusu(f"\"{k.APP_DIR}\" klasörü bulunamadı. Zip'in tamamını aynı klasöre çıkar; "
                     "Wichelberg.exe'yi tek başına taşıma.")
        return
    if k.yol_cok_uzun(y):
        _hata_kutusu(f"Klasör yolu çok uzun ({len(str(y.base))} karakter); Windows kurulumu tamamlayamaz.\n\n"
                     f"{y.base}\n\nWichelberg klasörünü Masaüstü veya Belgeler gibi kısa bir yere taşıyıp "
                     "tekrar aç.")
        return
    if not k.yazilabilir_mi(y):
        _hata_kutusu("Bu klasöre yazılamıyor (ör. Program Files). Klasörü Belgeler veya Masaüstü gibi bir yere "
                     "taşıyıp tekrar aç.")
        return
    try:
        manifest = k.manifest_oku(y)
    except k.KurulumHatasi as exc:
        _hata_kutusu(str(exc))
        return
    k.gizle(y.app)
    k.eski_dosyalari_temizle(y, manifest)
    k.venv_yolunu_duzelt(y)
    plan = k.plan_cikar(y, manifest, k.durum_oku(y))

    root = tk.Tk()
    if plan.gerekli:
        KurulumPenceresi(root, y, manifest, plan)
    else:
        AcilisPenceresi(root, y)
    root.mainloop()


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    main()
