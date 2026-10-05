"""Ses Kütüphanesi sekmesi: kurulu sesler, içe aktarma (zip / sürükle-bırak), önizleme, silme;
ortak AI modelleri ve hız testi (docs/DECISIONS.md D11, D26, D49, D50).

Ağır işler (içe aktarma, indirme, hız testi) arka planda çalışır; sonuçlar kuyruk üzerinden ana iş parçacığına
gelir. tkinter widget'larına yalnızca ana iş parçacığından dokunulur.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import psutil
import sounddevice as sd
import soundfile as sf

from .. import engine as audio
from .. import paths
from ..ai import library, shared
from ..ai.download import download
from ..ai.voices import VoiceError, scan_voices
from . import theme
from .widgets import ScrollFrame

BENCH_RESULT = "hiz_testi_sonuc.json"      # data/ altında, iş bitince silinir
PROGRESS_LINE = re.compile(r"^\[ilerleme\] (\d+)/(\d+)")


def _mb(n: int) -> str:
    return f"{n / 2**20:.0f} MB" if n < 2**30 else f"{n / 2**30:.2f} GB"


class LibraryPanel(ScrollFrame):
    def __init__(self, master, config: dict, on_config_change, hooks):
        """hooks: is_live(), release_voice(id), unload_ai(), voices_changed(), benchmark_applied()."""
        super().__init__(master, padding=(16, 14, 16, 14))
        self.config = config
        self._on_config_change = on_config_change
        self._hooks = hooks
        self._jobs: queue.Queue = queue.Queue()
        self._entries = []
        self._busy = False
        self._bench_proc: subprocess.Popen | None = None
        body = self.body
        body.columnconfigure(0, weight=1)
        self._build_voices(body)
        self._build_shared(body)
        self._build_benchmark(body)
        self.refresh()
        self._poll_jobs()

    # ----------------------------------------------------------------- arayüz
    def _build_voices(self, body) -> None:
        box = ttk.LabelFrame(body, text="Seslerim", padding=12)
        box.grid(sticky="ew")
        box.columnconfigure(0, weight=1)
        self._drop_hint = ttk.Label(
            box, style="Muted.TLabel", wraplength=560, justify="left",
            text="Sesler sana gönderilen .zip dosyalarıdır. Zip'i bu listeye sürükle veya \"İçe aktar…\"a bas. "
                 "Lisansı ve kaynağı yazılı olmayan veya dosyası bozuk paket kurulmaz.")
        self._drop_hint.grid(row=0, column=0, sticky="w")

        columns = ("version", "author", "size", "status")
        self._tree = ttk.Treeview(box, columns=columns, height=6, selectmode="browse")
        self._tree.heading("#0", text="Ses")
        self._tree.heading("version", text="Sürüm")
        self._tree.heading("author", text="Hazırlayan")
        self._tree.heading("size", text="Boyut")
        self._tree.heading("status", text="Durum")
        self._tree.column("#0", width=170, minwidth=120, stretch=True)
        self._tree.column("version", width=60, minwidth=50, stretch=False, anchor="center")
        self._tree.column("author", width=120, minwidth=80, stretch=True)
        self._tree.column("size", width=70, minwidth=60, stretch=False, anchor="e")
        self._tree.column("status", width=120, minwidth=80, stretch=True)
        self._tree.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._show_details())

        self._details = ttk.Label(box, wraplength=560, justify="left", style="Muted.TLabel")
        self._details.grid(row=2, column=0, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(box)
        buttons.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self._import_button = ttk.Button(buttons, text="İçe aktar…", style="Accent.TButton",
                                         command=self._choose_file)
        self._import_button.pack(side="left")
        self._preview_button = ttk.Button(buttons, text="▶ Önizle", command=self._preview)
        self._preview_button.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="■", width=3, command=sd.stop).pack(side="left", padx=(4, 0))
        self._delete_button = ttk.Button(buttons, text="Sil", command=self._delete)
        self._delete_button.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Klasörü aç", command=self._open_folder).pack(side="left", padx=(8, 0))
        self._import_status = ttk.Label(box, wraplength=560, justify="left")
        self._import_status.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self._enable_drop()

    def _build_shared(self, body) -> None:
        box = ttk.LabelFrame(body, text="Ortak AI modelleri", padding=12)
        box.grid(sticky="ew", pady=(12, 0))
        box.columnconfigure(0, weight=1)
        ttk.Label(box, style="Muted.TLabel", wraplength=560, justify="left",
                  text="Her AI sesinin kullandığı genel modeller (MIT lisanslı, kimsenin sesi değil). "
                       "Kurulumda bir kez iner.").grid(row=0, column=0, columnspan=2, sticky="w")
        self._shared_lines = ttk.Label(box, justify="left")
        self._shared_lines.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._shared_button = ttk.Button(box, text="Ortak modelleri indir", command=self._download_shared)
        self._shared_button.grid(row=1, column=1, sticky="ne", pady=(8, 0))
        self._shared_progress = ttk.Progressbar(box, maximum=1.0)
        self._shared_progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._shared_progress.grid_remove()
        self._shared_status = ttk.Label(box, wraplength=560, justify="left")
        self._shared_status.grid(row=3, column=0, columnspan=2, sticky="w")

    def _build_benchmark(self, body) -> None:
        box = ttk.LabelFrame(body, text="Hız testi", padding=12)
        box.grid(sticky="ew", pady=(12, 0))
        box.columnconfigure(0, weight=1)
        ttk.Label(box, style="Muted.TLabel", wraplength=560, justify="left",
                  text="AI modunun bu bilgisayarda oyunla birlikte gerçek zamanlı çalışıp çalışmadığını ölçer ve "
                       "ayarları seçer. ~5 dakika sürer; bu sırada bilgisayar meşgul olur, oyunu ve canlıyı kapat."
                  ).grid(row=0, column=0, columnspan=2, sticky="w")
        self._bench_summary = ttk.Label(box, wraplength=560, justify="left")
        self._bench_summary.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._bench_button = ttk.Button(box, text="Hız testini başlat", command=self._bench_clicked)
        self._bench_button.grid(row=1, column=1, sticky="ne", pady=(8, 0))
        self._bench_progress = ttk.Progressbar(box, maximum=1.0)
        self._bench_progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._bench_log = tk.Text(box, height=9, wrap="word", state="disabled", font=("Consolas", 9))
        self._bench_log.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        theme.style_text(self._bench_log)
        self._bench_progress.grid_remove()
        self._bench_log.grid_remove()

    def restyle(self) -> None:
        super().restyle()
        if hasattr(self, "_bench_log"):
            theme.style_text(self._bench_log)

    # ------------------------------------------------------------ yenileme
    def refresh(self) -> None:
        selected = self._selected_id()
        self._entries = scan_voices()
        self._tree.delete(*self._tree.get_children())
        for entry in self._entries:
            v = entry.voice
            if v is not None:
                active = v.id == self.config["ai"].get("active_voice")
                status = "✓ hazır" + (" · seçili" if active else "")
                self._tree.insert("", "end", iid=v.id, text=v.display_name,
                                  values=(v.version, v.author, _mb(library.folder_size(v.folder)), status))
            else:
                self._tree.insert("", "end", iid=f"!{entry.folder.name}", text=entry.folder.name,
                                  values=("", "", _mb(library.folder_size(entry.folder)),
                                          f"⚠ {entry.error}"))
        if not self._entries:
            self._tree.insert("", "end", iid="!bos", text="Henüz ses yok", values=("", "", "", ""))
        if selected and self._tree.exists(selected):
            self._tree.selection_set(selected)
        self._show_details()
        self._refresh_shared()
        self._refresh_benchmark_summary()

    def _selected_id(self) -> str | None:
        sel = self._tree.selection() if hasattr(self, "_tree") else ()
        return sel[0] if sel else None

    def _selected_voice(self):
        voice_id = self._selected_id()
        return next((e.voice for e in self._entries if e.voice and e.voice.id == voice_id), None)

    def _show_details(self) -> None:
        voice = self._selected_voice()
        entry_id = self._selected_id()
        if voice is None:
            broken = entry_id and entry_id.startswith("!") and entry_id != "!bos"
            self._details.config(text="Bozuk paket: silip yeniden içe aktar." if broken else "")
            self._preview_button.state(["disabled"])
            self._delete_button.state(["!disabled"] if broken else ["disabled"])
            return
        lines = []
        if voice.description:
            lines.append(voice.description)
        lines.append(f"Lisans: {voice.license}")
        lines.append(f"Kaynak: {voice.source}")
        if voice.consent_note:
            lines.append(f"Rıza: {voice.consent_note}")
        lines.append(f"Hedef perde ≈ {voice.target_f0_median:.0f} Hz · {voice.sample_rate // 1000} kHz"
                     + (" · index var" if voice.index_path else ""))
        self._details.config(text="\n".join(lines))
        self._preview_button.state(["!disabled"] if voice.preview_path else ["disabled"])
        self._delete_button.state(["!disabled"])

    def _refresh_shared(self) -> None:
        pitch = self.config["ai"].get("pitch_method", "fcpe")
        wanted = [shared.SHARED_MODELS[n] for n in ("contentvec", pitch)]
        lines = []
        for m in wanted:
            ok = m.path.is_file()
            lines.append(f"{'✓' if ok else '✗'} {m.file} ({_mb(m.size_bytes)}){'' if ok else ' — eksik'}")
        self._shared_lines.config(text="\n".join(lines))
        missing = [m for m in wanted if not m.path.is_file()]
        self._shared_lines.config(foreground=theme.color("warn" if missing else "ok"))
        if missing and not self._busy:
            self._shared_button.grid()
        else:
            self._shared_button.grid_remove()

    def _refresh_benchmark_summary(self) -> None:
        bench = self.config["ai"].get("benchmark") or {}
        if not bench:
            self._bench_summary.config(text="Henüz yapılmadı. AI modu için gerekli.",
                                       foreground=theme.color("warn"))
            return
        rec = bench.get("recommended", {})
        cpu, gpu = rec.get("cpu"), rec.get("gpu")
        parts = [f"Son test: {bench.get('date', '?')[:16].replace('T', ' ')}"]
        parts.append(f"CPU: geçti, gecikme ≈ {cpu['latency_ms']} ms" if cpu
                     else "CPU: oyunla birlikte yetmiyor")
        if gpu:
            parts.append(f"GPU: {gpu.get('name', '')}, gecikme ≈ {gpu['latency_ms']} ms")
        elif bench.get("gpus"):
            parts.append("GPU: uygun değil (eşitlik testini geçemedi)")
        ok = bool(cpu or gpu)
        self._bench_summary.config(text="\n".join(parts), foreground=theme.color("ok" if ok else "warn"))

    # ------------------------------------------------------- iş parçacıkları
    def _poll_jobs(self) -> None:
        try:
            while True:
                try:
                    callback = self._jobs.get_nowait()
                except queue.Empty:
                    break
                callback()
        finally:  # bir hata döngüyü durdurmasın (yoksa ekran "meşgul" kalır)
            self.after(60, self._poll_jobs)

    def _later(self, callback) -> None:
        """Arka plandan ana iş parçacığına."""
        self._jobs.put(callback)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in (self._import_button, self._delete_button, self._shared_button, self._bench_button):
            button.state(["disabled"] if busy else ["!disabled"])
        if not busy:
            self.refresh()

    # ------------------------------------------------------------ içe aktarma
    def _enable_drop(self) -> None:
        try:
            from tkinterdnd2 import DND_FILES

            for widget in (self._tree, self._drop_hint, self.body):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._dropped)
        except Exception:  # noqa: BLE001 — tkinterdnd2 yoksa sadece "İçe aktar…" (D14)
            pass

    def _dropped(self, event):
        files = self.tk.splitlist(event.data)
        if files:
            self.after(10, lambda: self.import_path(files[0]))
        return event.action

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(title="Ses paketi seç", filetypes=[("Ses paketi", "*.zip"),
                                                                            ("Tüm dosyalar", "*.*")])
        if path:
            self.import_path(path)

    def import_path(self, path: str) -> None:
        if self._busy:
            messagebox.showinfo("İçe aktar", "Önceki iş bitmeden yeni ses eklenemez.")
            return
        try:
            preview = library.inspect(path)
        except (VoiceError, OSError) as exc:
            messagebox.showerror("İçe aktar", f"Bu paket kurulamaz:\n{exc}")
            return
        v = preview.voice
        text = (f"{v.display_name}  (sürüm {v.version})\nHazırlayan: {v.author}\nLisans: {v.license}\n"
                f"Kaynak: {v.source}\nBoyut: {_mb(preview.size_bytes)}")
        if preview.existing is not None:
            text += (f"\n\nBu ses zaten kurulu (sürüm {preview.existing.version}). "
                     "Yenisiyle değiştirilsin mi? Ses ayarların korunur.")
        else:
            text += "\n\nKurulsun mu?"
        if not messagebox.askyesno("Ses ekle", text):
            return
        if preview.existing is not None:
            self._hooks.release_voice(v.id)
        self._set_busy(True)
        self._import_status.config(text=f"{v.display_name}: hazırlanıyor…", foreground=theme.color("muted"))

        def work():
            try:
                voice = library.import_voice(path, progress=lambda t: self._later(
                    lambda: self._import_status.config(text=f"{v.display_name}: {t}")))
                self._later(lambda: self._import_done(voice, None))
            except Exception as exc:  # noqa: BLE001 — her hata kullanıcıya gösterilsin, ekran meşgul kalmasın
                # `exc` except bloğundan sonra silinir: değeri varsayılan argümanla sabitle
                self._later(lambda error=exc: self._import_done(None, error))

        threading.Thread(target=work, daemon=True).start()

    def _import_done(self, voice, error) -> None:
        self._set_busy(False)
        if error is not None:
            self._import_status.config(text=f"⚠ Kurulamadı: {error}", foreground=theme.color("error"))
            return
        self._import_status.config(text=f"✓ {voice.display_name} kuruldu.", foreground=theme.color("ok"))
        self._hooks.voices_changed()
        self.refresh()
        if self._tree.exists(voice.id):
            self._tree.selection_set(voice.id)

    def _delete(self) -> None:
        voice_id = self._selected_id()
        if not voice_id or voice_id == "!bos":
            return
        voice = self._selected_voice()
        name = voice.display_name if voice else voice_id.lstrip("!")
        if not messagebox.askyesno("Sesi sil", f"\"{name}\" bilgisayardan silinsin mi?\n"
                                               "Tekrar kullanmak için zip'i yeniden içe aktarman gerekir."):
            return
        folder_id = voice.id if voice else voice_id.lstrip("!")
        self._hooks.release_voice(folder_id)
        sd.stop()
        try:
            library.delete_voice(folder_id)
        except (VoiceError, OSError) as exc:
            messagebox.showerror("Sesi sil", f"Silinemedi: {exc}")
            return
        self._import_status.config(text=f"{name} silindi.", foreground=theme.color("muted"))
        self._hooks.voices_changed()
        self.refresh()

    def _preview(self) -> None:
        voice = self._selected_voice()
        if voice is None or voice.preview_path is None:
            return
        default_out = audio.default_device("output")
        if audio.is_cable(default_out):
            messagebox.showwarning("Önizle", "Windows'un varsayılan çıkışı CABLE Input: önizleme Discord'a "
                                             "giderdi. Varsayılan çıkışı hoparlör/kulaklık yap.")
            return
        data, sr = sf.read(str(voice.preview_path), dtype="float32")
        sd.stop()
        sd.play(data, sr)

    def _open_folder(self) -> None:
        paths.VOICES_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(paths.VOICES_DIR)

    # ------------------------------------------------------- ortak modeller
    def _download_shared(self) -> None:
        pitch = self.config["ai"].get("pitch_method", "fcpe")
        missing = [m for m in (shared.SHARED_MODELS[n] for n in ("contentvec", pitch)) if not m.path.is_file()]
        if not missing:
            return
        if any(not m.url for m in missing):
            messagebox.showinfo("Ortak modeller", "Bu sürümde indirme adresi tanımlı değil. Ortak modelleri "
                                                  "kurulum (Wichelberg.exe) indirir.")
            return
        total = sum(m.size_bytes for m in missing)
        self._set_busy(True)
        self._shared_progress.grid()
        self._shared_progress["value"] = 0

        def work():
            done_before = 0
            try:
                for m in missing:
                    def progress(done, _total, m=m, base=done_before):
                        self._later(lambda: self._shared_step(m.file, base + done, total))
                    download(m.url, m.path, m.sha256, progress)
                    done_before += m.size_bytes
                self._later(lambda: self._shared_done(None))
            except Exception as exc:  # noqa: BLE001
                self._later(lambda error=exc: self._shared_done(error))

        threading.Thread(target=work, daemon=True).start()

    def _shared_step(self, name: str, done: int, total: int) -> None:
        self._shared_progress["value"] = done / max(1, total)
        self._shared_status.config(text=f"↓ {name} · {_mb(done)} / {_mb(total)}", foreground=theme.color("muted"))

    def _shared_done(self, error) -> None:
        self._shared_progress.grid_remove()
        if error:
            self._shared_status.config(text=f"⚠ {error}", foreground=theme.color("error"))
        else:
            self._shared_status.config(text="✓ Ortak modeller indirildi ve doğrulandı.",
                                       foreground=theme.color("ok"))
        self._set_busy(False)
        self._hooks.voices_changed()

    # --------------------------------------------------------------- hız testi
    @property
    def benchmark_running(self) -> bool:
        return self._bench_proc is not None

    def _bench_clicked(self) -> None:
        if self._bench_proc is not None:
            if messagebox.askyesno("Hız testi", "Hız testi durdurulsun mu? Sonuç kaydedilmez."):
                self.stop_benchmark()
            return
        if self._hooks.is_live():
            messagebox.showinfo("Hız testi", "Önce ana ekrandan canlıyı durdur (ölçümü bozar).")
            return
        if not any(e.voice for e in self._entries):
            messagebox.showinfo("Hız testi", "Hız testi bir AI sesiyle ölçer: önce bir ses içe aktar.")
            return
        pitch = self.config["ai"].get("pitch_method", "fcpe")
        if any(not shared.SHARED_MODELS[n].path.is_file() for n in ("contentvec", pitch)):
            messagebox.showinfo("Hız testi", "Önce ortak AI modellerini indir.")
            return
        if not messagebox.askyesno("Hız testi", "Hız testi ~5 dakika sürer ve bu sırada işlemciyi yoğun "
                                                "kullanır. Oyunu kapat. Başlasın mı?"):
            return
        self._hooks.unload_ai()
        result_file = paths.DATA_DIR / BENCH_RESULT
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        result_file.unlink(missing_ok=True)
        env = dict(os.environ, PYTHONUTF8="1")
        try:
            self._bench_proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "voicechanger.tools.benchmark", "--json", str(result_file)],
                cwd=paths.ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            messagebox.showerror("Hız testi", f"Başlatılamadı: {exc}")
            return
        self._log_clear()
        self._bench_log.grid()
        self._bench_progress.grid()
        self._bench_progress["value"] = 0
        self._bench_button.config(text="Durdur")
        self._busy = True
        for button in (self._import_button, self._delete_button, self._shared_button):
            button.state(["disabled"])
        proc = self._bench_proc

        def reader():
            for line in proc.stdout:
                line = line.rstrip()
                self._later(lambda line=line: self._bench_line(line))
            code = proc.wait()
            self._later(lambda: self._bench_done(proc, code, result_file))

        threading.Thread(target=reader, daemon=True).start()

    def _bench_line(self, line: str) -> None:
        match = PROGRESS_LINE.match(line)
        if match:
            done, total = int(match.group(1)), int(match.group(2))
            self._bench_progress["value"] = done / max(1, total)
            return
        if line:
            self._log(line)

    def _bench_done(self, proc, code: int, result_file) -> None:
        if proc is not self._bench_proc:
            return
        self._bench_proc = None
        self._bench_button.config(text="Hız testini başlat")
        self._bench_progress.grid_remove()
        result = None
        if code == 0 and result_file.is_file():
            try:
                result = json.loads(result_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                result = None
        result_file.unlink(missing_ok=True)
        if result is not None:
            from ..tools.benchmark import apply_result

            apply_result(self.config["ai"], result)
            self._on_config_change()
            self._log("✓ Sonuç kaydedildi.")
        elif code != 0:
            self._log(f"⚠ Hız testi tamamlanamadı (kod {code}).")
        self._set_busy(False)
        self._hooks.benchmark_applied()

    def stop_benchmark(self) -> None:
        """Hız testini ve sahte oyun yükü süreçlerini durdur (program kapanırken de)."""
        proc, self._bench_proc = self._bench_proc, None
        if proc is None:
            return
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except psutil.Error:
            pass
        self._bench_button.config(text="Hız testini başlat")
        self._bench_progress.grid_remove()
        self._log("Hız testi durduruldu.")
        self._set_busy(False)
        self._hooks.benchmark_applied()

    def _log_clear(self) -> None:
        self._bench_log.config(state="normal")
        self._bench_log.delete("1.0", "end")
        self._bench_log.config(state="disabled")

    def _log(self, text: str) -> None:
        self._bench_log.config(state="normal")
        self._bench_log.insert("end", text + "\n")
        self._bench_log.see("end")
        self._bench_log.config(state="disabled")
