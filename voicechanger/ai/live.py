"""Canlı AI dönüştürme: ses kartı callback'i ile model arasındaki köprü.

    callback (10 ms):  push(ön işlenmiş ses)  →  [kuyruk]  →  worker: RvcStream.convert_chunk
                       pull(10 ms)            ←  [çıkış FIFO] ←

- Model arka planda yüklenir; hazır olana kadar pull() SESSİZLİK verir.
- Çıkış zamanlaması: her parça, işlem süresinin son %95'ine (P) göre planlanır; gecikme ≈ parça + P + 50 ms.
  Parça yine de geç kalırsa o an SESSİZLİK gider (asla ham ses), sayaç artar, tampon yeniden kurulur.
- Sessizlik: RVC sessiz girişte de kendiliğinden gürültü üretiyor (ölçüldü, ~0.2 tepe). Bu yüzden girişin
  sessiz (kapı kapalı) olduğu anlar, gecikmeyle hizalanıp çıkışta da susturulur.
- Otomatik perde: konuşanın medyan F0'ı ölçülür; kaydırma = 12·log2(hedef / konuşan) + elle düzeltme.
  Hedef: aktif sesin voice.json'daki target_f0_median'ı. Kaydırma yumuşak değişir.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from .base import SAMPLE_RATE, ConvertParams
from .runtime import GPU, Runtime
from .rvc_onnx import RvcModel, RvcStream, StreamConfig
from .voices import Voice

LOADING, READY, ERROR, STOPPED = "yükleniyor", "hazır", "hata", "durdu"
MIN_VOICED_FRAMES = 100         # 1 sn ötümlü konuşmadan sonra konuşan F0'ına güven
F0_HISTORY_FRAMES = 800         # son ~8 sn ötümlü kare
SHIFT_DEADBAND_ST = 0.5         # bundan küçük farkları yok say
SHIFT_SLEW_ST = 0.25            # parça başına en fazla bu kadar değiştir
DROP_QUIET_DB = -50.0
ACTIVE_DB = -70.0               # ön işlenmiş girişte bunun üstü "konuşma var" (kapı kapalıyken ~sıfır)
FRAME = SAMPLE_RATE // 100


@dataclass
class AiStats:
    state: str = STOPPED
    message: str = ""
    voice: str = ""
    provider: str = ""
    block_ms: int = 0
    latency_ms: float = 0.0         # parça + planlanan işlem payı + crossfade (ses kartı hariç)
    proc_ms: float = 0.0            # son parçanın işlem süresi (kuyrukta bekleme dahil)
    proc_p95_ms: float = 0.0
    late: int = 0                   # geç kalan parça (o an sessizlik gitti)
    dropped: int = 0                # kuyruk taşması nedeniyle atlanan parça
    errors: int = 0
    speaker_f0_hz: float | None = None
    target_f0_hz: float = 0.0
    auto_shift_st: float = 0.0
    correction_st: float = 0.0
    applied_shift_st: float = 0.0


class AiLive:
    def __init__(self, voice: Voice, runtime: Runtime, stream_config: StreamConfig, pitch_method: str = "fcpe",
                 params: ConvertParams | None = None, correction_st: float = 0.0,
                 speaker_f0_hint: float | None = None, expected_proc_ms: float | None = None):
        self.voice = voice
        self.runtime = runtime
        self.config = stream_config
        self.pitch_method = pitch_method
        self.params = params or ConvertParams(index_rate=voice.default_index_rate)
        self.correction_st = correction_st
        self.block_size = stream_config.frames()[0] * (SAMPLE_RATE // 100)
        self._block_ms = self.block_size * 1000 // SAMPLE_RATE
        self._state = STOPPED
        self._message = ""
        self._model: RvcModel | None = None
        self._stream: RvcStream | None = None
        self._queue: queue.Queue = queue.Queue(maxsize=3)
        self._running = False
        self._reset_stream = False
        self._threads: list[threading.Thread] = []
        # giriş biriktirme (ses iş parçacığı)
        self._acc = np.zeros(self.block_size, np.float32)
        self._acc_fill = 0
        self._chunk_id = 0
        self._valid_from = 0                     # bu id'den eski parçaların çıktısı sessizlik
        # çıkış FIFO (worker yazar, ses iş parçacığı okur)
        self._lock = threading.Lock()
        self._fifo: deque = deque()              # (chunk_id, ndarray) — ilk öğede okuma ofseti
        self._offset = 0
        self._fill = 0
        self._primed = False
        # ölçüm
        self._proc: deque = deque(maxlen=40)
        initial = expected_proc_ms if expected_proc_ms else 0.75 * self._block_ms
        self._plan_ms = min(0.9 * self._block_ms, max(20.0, initial + 10.0))
        self._late = self._dropped = self._errors = 0
        self._last_proc = 0.0
        # sessizlik maskesi: çıkış, girişten (crossfade + arama) kare geride
        _, _, c, s, _ = stream_config.frames()
        self._act_tail = np.zeros(c + s, bool)
        self._last_active = False
        self._last_mask = False
        ramp = int(0.005 * SAMPLE_RATE)
        self._ramp = np.linspace(0.0, 1.0, ramp, dtype=np.float32)
        # perde
        self._f0_hist: deque = deque(maxlen=F0_HISTORY_FRAMES)
        self._speaker_hint = speaker_f0_hint or 120.0
        self._auto_shift = self._desired_auto_shift(self._speaker_hint)

    # ----------------------------------------------------------------- yaşam döngüsü
    def start(self) -> None:
        """Modeli arka planda yükle, sonra worker'ı çalıştır."""
        self._running = True
        self._state, self._message = LOADING, "Model yükleniyor…"
        thread = threading.Thread(target=self._load_and_run, name="ai-worker", daemon=True)
        self._threads.append(thread)
        thread.start()

    def stop(self) -> None:
        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()
        if self._model is not None:
            self._model.close()
            self._model = None
        self._state = STOPPED

    @property
    def state(self) -> str:
        return self._state

    def _load_and_run(self) -> None:
        try:
            self._model = RvcModel(self.voice, self.runtime, self.pitch_method, self.config)
            self._stream = RvcStream(self._model)
            silence = np.zeros(self.block_size, np.float32)
            for _ in range(2):  # ısınma: DirectML ilk çalıştırmada grafiği derler
                self._stream.convert_chunk(silence, 0.0, self.params)
            self._stream.reset()
        except Exception as exc:  # noqa: BLE001 — kullanıcıya gösterilir, ses sessiz kalır
            self._state, self._message = ERROR, f"Model yüklenemedi: {exc}"
            return
        self._state, self._message = READY, ""
        self._worker()

    # ----------------------------------------------------------------- ses iş parçacığı
    def push(self, x: np.ndarray) -> None:
        """Ön işlenmiş 48 kHz ses (her callback). Model hazır değilse yok sayılır."""
        if self._state != READY:
            self._acc_fill = 0
            return
        pos = 0
        while pos < x.size:
            take = min(self.block_size - self._acc_fill, x.size - pos)
            self._acc[self._acc_fill:self._acc_fill + take] = x[pos:pos + take]
            self._acc_fill += take
            pos += take
            if self._acc_fill == self.block_size:
                item = (self._chunk_id, self._acc.copy(), time.perf_counter())
                self._chunk_id += 1
                self._acc_fill = 0
                try:
                    self._queue.put_nowait(item)
                except queue.Full:  # worker yetişemiyor: en eski parçayı at
                    try:
                        self._queue.get_nowait()
                        self._dropped += 1
                    except queue.Empty:
                        pass
                    self._queue.put_nowait(item)

    def flush(self) -> None:
        """Eski sesi unut (canlı yeniden başlarken): kuyruk, çıkış ve modelin bağlam penceresi."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with self._lock:
            self._fifo.clear()
            self._offset = self._fill = 0
            self._primed = False
        self._acc_fill = 0
        self._reset_stream = True

    def mark_valid_from_now(self) -> None:
        """Bundan önce başlamış parçaların çıktısını çalma (dönüştürme yeni açıldı: tekrar duyulmasın)."""
        self._valid_from = self._chunk_id + (1 if self._acc_fill else 0)

    def pull(self, n: int) -> np.ndarray:
        """n örnek çıkış. Hazır değilse veya parça geç kaldıysa sessizlik."""
        out = np.zeros(n, np.float32)
        with self._lock:
            if not self._primed:
                return out
            if self._fill < n:  # parça zamanında gelmedi
                self._primed = False
                self._late += 1
                return out
            pos = 0
            while pos < n:
                chunk_id, data = self._fifo[0]
                take = min(n - pos, data.size - self._offset)
                if chunk_id >= self._valid_from:
                    out[pos:pos + take] = data[self._offset:self._offset + take]
                pos += take
                self._offset += take
                if self._offset == data.size:
                    self._fifo.popleft()
                    self._offset = 0
            self._fill -= n
        return out

    # ----------------------------------------------------------------- worker
    def _worker(self) -> None:
        timeout = 2.0 * self._block_ms / 1000 if self.runtime.provider == GPU else None
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            chunk_id, x, queued_at = item
            if self._reset_stream:
                self._reset_stream = False
                self._stream.reset()
            try:
                y = self._stream.convert_chunk(x, self._next_shift(), self.params, timeout)
                self._track_f0(self._stream.last_f0)
            except Exception as exc:  # noqa: BLE001 — o parça sessiz, akış sıfırlanır
                self._errors += 1
                self._message = f"İşleme hatası: {exc}"
                y = np.zeros(self.block_size, np.float32)
                self._stream.reset()
            proc_ms = (time.perf_counter() - queued_at) * 1000
            self._last_proc = proc_ms
            self._proc.append(proc_ms)
            if len(self._proc) >= 10:
                p95 = float(np.percentile(self._proc, 95))
                self._plan_ms = min(0.9 * self._block_ms, max(20.0, p95 + 10.0))
            self._enqueue_output(chunk_id, (y * self._activity_envelope(x)).astype(np.float32), proc_ms)

    def _activity_envelope(self, x: np.ndarray) -> np.ndarray:
        """Girişte konuşma olan 10 ms'lik kareler → çıkış için yumuşak 0/1 zarfı.

        Çıkış karesi f, girişin (crossfade + arama) kare öncesine karşılık gelir; ±1 kare pay bırakılır ki
        konuşmanın başı/sonu kesilmesin. Geçişler 5 ms rampa.
        """
        frames = x[: x.size // FRAME * FRAME].reshape(-1, FRAME)
        speaking = 10 * np.log10(np.mean(frames * frames, axis=1) + 1e-12) > ACTIVE_DB
        lag = self._act_tail.size
        active = np.concatenate([self._act_tail, speaking])   # active[f] ↔ çıkış karesi f
        self._act_tail = active[len(active) - lag:]
        n = speaking.size
        padded = np.concatenate([[self._last_active], active, [False]])
        mask = padded[0:n] | padded[1:n + 1] | padded[2:n + 2]
        self._last_active = bool(active[n - 1]) if n else self._last_active
        env = np.repeat(mask.astype(np.float32), FRAME)
        previous = np.concatenate([[self._last_mask], mask[:-1]])
        for f in np.flatnonzero(mask != previous):
            seg = env[f * FRAME:f * FRAME + self._ramp.size]
            seg[:] = (self._ramp if mask[f] else self._ramp[::-1])[: seg.size]
        self._last_mask = bool(mask[-1]) if n else self._last_mask
        return env

    def _enqueue_output(self, chunk_id: int, y: np.ndarray, proc_ms: float) -> None:
        """Parçayı plana göre yerleştir: başta işlem payı kadar sessizlik, fazla birikirse sessiz yerden kırp."""
        want = int(max(0.0, self._plan_ms - proc_ms) * SAMPLE_RATE / 1000)  # bu parçadan önce kalması gereken
        with self._lock:
            if not self._primed:
                self._fifo.clear()
                self._offset = 0
                self._fifo.append((-1, np.zeros(want, np.float32)))
                self._fill = want
                self._primed = True
            else:
                excess = self._fill - want
                if excess > 0.030 * SAMPLE_RATE:
                    self._drop_oldest(excess - int(0.010 * SAMPLE_RATE),
                                      force=excess > 0.100 * SAMPLE_RATE)
            self._fifo.append((chunk_id, y))
            self._fill += y.size

    def _drop_oldest(self, n: int, force: bool) -> None:
        """Gecikme birikmesin: en eski n örneği at (sessizse veya zorunluysa)."""
        if not self._fifo:
            return
        _, head = self._fifo[0]
        sample = head[self._offset:self._offset + n]
        quiet = sample.size == 0 or 20 * math.log10(float(np.sqrt(np.mean(sample * sample))) + 1e-9) < DROP_QUIET_DB
        if not (quiet or force):
            return
        while n > 0 and self._fifo:
            _, data = self._fifo[0]
            take = min(n, data.size - self._offset)
            self._offset += take
            self._fill -= take
            n -= take
            if self._offset == data.size:
                self._fifo.popleft()
                self._offset = 0

    # ----------------------------------------------------------------- perde
    def _desired_auto_shift(self, speaker_f0: float) -> float:
        return float(np.clip(12 * math.log2(self.voice.target_f0_median / max(speaker_f0, 40.0)), -12.0, 24.0))

    @property
    def speaker_f0(self) -> float | None:
        if len(self._f0_hist) < MIN_VOICED_FRAMES:
            return None
        return float(np.median(self._f0_hist))

    def _track_f0(self, f0: np.ndarray) -> None:
        voiced = f0[(f0 > 60) & (f0 < 500)]
        self._f0_hist.extend(voiced.tolist())

    def _next_shift(self) -> float:
        speaker = self.speaker_f0 or self._speaker_hint
        desired = self._desired_auto_shift(speaker)
        diff = desired - self._auto_shift
        if abs(diff) > SHIFT_DEADBAND_ST:
            self._auto_shift += float(np.clip(diff, -SHIFT_SLEW_ST, SHIFT_SLEW_ST))
        return self._auto_shift + self.correction_st

    # ----------------------------------------------------------------- ölçüm
    def stats(self) -> AiStats:
        proc_p95 = float(np.percentile(self._proc, 95)) if self._proc else 0.0
        crossfade = (self.config.frames()[2] + self.config.frames()[3]) * 10
        return AiStats(state=self._state, message=self._message, voice=self.voice.display_name,
                       provider=self.runtime.describe(), block_ms=self._block_ms,
                       latency_ms=self._block_ms + self._plan_ms + crossfade,
                       proc_ms=self._last_proc, proc_p95_ms=proc_p95, late=self._late, dropped=self._dropped,
                       errors=self._errors, speaker_f0_hz=self.speaker_f0,
                       target_f0_hz=self.voice.target_f0_median, auto_shift_st=self._auto_shift,
                       correction_st=self.correction_st, applied_shift_st=self._auto_shift + self.correction_st)


# ----------------------------------------------------------------------------- config'ten kurulum
def voice_settings(ai_cfg: dict, voice: Voice) -> dict:
    """Ses başına ayarlar (D11): perde düzeltme, index oranı, koruma. Yoksa sesin varsayılanları."""
    stored = (ai_cfg.get("per_voice") or {}).get(voice.id, {})
    return {"correction_st": float(stored.get("correction_st", 0.0)),
            "index_rate": float(stored.get("index_rate", voice.default_index_rate)),
            "protect": float(stored.get("protect", 0.33))}


def from_settings(ai_cfg: dict, voice: Voice) -> AiLive:
    """config.json → "ai" bölümünden canlı dönüştürücü (henüz başlatılmamış)."""
    from . import policy

    runtime = Runtime.from_settings(ai_cfg)
    accel = runtime.provider
    block_ms = policy.block_ms_for(ai_cfg, accel)
    context_ms = int((ai_cfg.get("stream") or {}).get("context_ms", 1000))
    per_voice = voice_settings(ai_cfg, voice)
    return AiLive(voice, runtime, StreamConfig(block_ms=block_ms, context_ms=context_ms),
                  pitch_method=ai_cfg.get("pitch_method", "fcpe"),
                  params=ConvertParams(index_rate=per_voice["index_rate"], protect=per_voice["protect"]),
                  correction_st=per_voice["correction_st"], speaker_f0_hint=ai_cfg.get("speaker_f0_hz"),
                  expected_proc_ms=policy.expected_proc_ms(ai_cfg, accel, block_ms))
