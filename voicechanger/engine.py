"""Gerçek zamanlı ses motoru: mikrofon → (DSP zinciri | AI) → CABLE Input (+ isteğe bağlı kulaklık).

Modlar:
  - "dsp": VoiceChain (PSOLA), ~27 ms.
  - "ai":  high-pass → gürültü kapısı → otomatik seviye → AiLive (ayrı iş parçacığında RVC) → sınırlayıcı.
           Model hazır değilse veya parça geç kalırsa SESSİZLİK (asla ham ses).
  Mod değişirken 10 ms kısılıp açılır (tıkırtı olmasın).

Mimari:
  - Giriş akışının callback'i gelen her bloğu (10 ms) ses zincirinden
    geçirir ve sonucu çıkış tamponlarına (ring buffer) yazar.
  - Her çıkış cihazının (CABLE, kulaklık) kendi akışı vardır ve kendi
    saatinde tampondan okur. Cihaz saatleri arasındaki küçük farklar
    (drift) tampon seviyesi izlenerek dengelenir.

Güvenlik (CABLE'a asla istenmeden ham ses gitmez):
  - İşleme sırasında hata olursa o blok için SESSİZLİK gönderilir.
  - Tampon boşalırsa (takılma) SESSİZLİK gönderilir.
  - Program kapanır veya çökerse akışlar da kapanır; CABLE sessiz kalır.
  Not: Dönüştürme kapatıldığında (Ctrl+F7) normal sesin gider; bu bilinçli.
"""

import threading
import time
from dataclasses import dataclass, field

import numpy as np
import psutil
import sounddevice as sd

from .dsp import VoiceChain, VoiceSettings
from .wavio import SAMPLE_RATE

DSP, AI = "dsp", "ai"
SWITCH_FADE = int(0.010 * SAMPLE_RATE)

BLOCK = 480                 # 10 ms giriş bloğu
PRIME = 120                 # çıkış okumaya başlamadan önce tamponda beklenecek ek örnek
MAX_FILL = 3 * BLOCK        # bunun üstü birikirse (saat kayması) fazlası atılır
WASAPI = "Windows WASAPI"   # Windows'un düşük gecikmeli, paylaşımlı ses arayüzü
CABLE_HINT = "CABLE Input"


class EngineError(Exception):
    """Kullanıcıya gösterilecek (Türkçe) hata."""


# ------------------------------------------------------------------ cihazlar
def refresh_devices() -> None:
    """Yeni takılan/kurulan cihazları (ör. VB-Cable) görmek için listeyi yenile.

    Yalnızca hiçbir akış açık değilken çağrılmalıdır.
    """
    sd._terminate()
    sd._initialize()


def _wasapi_index() -> int | None:
    for i, api in enumerate(sd.query_hostapis()):
        if api["name"] == WASAPI:
            return i
    return None


def list_devices(kind: str) -> list[str]:
    """kind: 'input' veya 'output'. WASAPI cihaz isimleri."""
    api = _wasapi_index()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    return [d["name"] for d in sd.query_devices() if d["hostapi"] == api and d[key] > 0]


def default_device(kind: str) -> str | None:
    api = _wasapi_index()
    if api is None:
        return None
    index = sd.query_hostapis(api)["default_input_device" if kind == "input" else "default_output_device"]
    return sd.query_devices(index)["name"] if index >= 0 else None


def is_cable(name: str | None) -> bool:
    return bool(name) and CABLE_HINT.lower() in name.lower()


def find_cable_output() -> str | None:
    """Discord'a gidecek sanal kablo girişi: 'CABLE Input (VB-Audio Virtual Cable)'."""
    return next((name for name in list_devices("output") if is_cable(name)), None)


def _device_index(name: str, kind: str) -> int:
    api = _wasapi_index()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] == api and d[key] > 0 and d["name"] == name:
            return i
    raise EngineError(f"Cihaz bulunamadı: {name}. Takılı olduğundan emin ol ve listeyi yenile.")


def _wasapi_settings(exclusive: bool = False):
    if exclusive:
        # Özel mod: Windows ses karıştırıcısı atlanır (mikrofon ~22 → ~10 ms).
        # Bu sırada başka uygulamalar mikrofonu doğrudan kullanamaz;
        # Discord/FiveM CABLE Output'u okuduğu için etkilenmez.
        return sd.WasapiSettings(exclusive=True)
    # auto_convert: cihaz 48 kHz değilse Windows örnekleme hızını kendisi çevirir
    return sd.WasapiSettings(auto_convert=True)


# ------------------------------------------------------------------ tampon
class RingBuffer:
    """İki iş parçacığı (giriş yazar, çıkış okur) arasında kilitli dairesel tampon."""

    def __init__(self, capacity: int):
        self._buf = np.zeros(capacity, dtype=np.float32)
        self._read = 0
        self._count = 0
        self._lock = threading.Lock()

    @property
    def fill(self) -> int:
        return self._count

    def write(self, x: np.ndarray) -> None:
        with self._lock:
            cap = self._buf.size
            n = x.size
            if n > cap:
                x, n = x[-cap:], cap
            overflow = self._count + n - cap
            if overflow > 0:  # en eski örnekleri at
                self._read = (self._read + overflow) % cap
                self._count -= overflow
            start = (self._read + self._count) % cap
            first = min(n, cap - start)
            self._buf[start:start + first] = x[:first]
            self._buf[:n - first] = x[first:]
            self._count += n

    def read(self, n: int) -> np.ndarray | None:
        """n örnek oku; yeterli yoksa None (çağıran sessizlik basar)."""
        with self._lock:
            if self._count < n:
                return None
            cap = self._buf.size
            first = min(n, cap - self._read)
            out = np.concatenate((self._buf[self._read:self._read + first], self._buf[:n - first]))
            self._read = (self._read + n) % cap
            self._count -= n
            return out

    def discard(self, n: int) -> None:
        with self._lock:
            n = min(n, self._count)
            self._read = (self._read + n) % self._buf.size
            self._count -= n

    def clear(self) -> None:
        with self._lock:
            self._read = 0
            self._count = 0


class OutputChannel:
    """Bir çıkış cihazı: kendi akışı ve tamponu."""

    def __init__(self, device_name: str, exclusive: bool = False):
        """exclusive=True denenir, açılamazsa paylaşımlı moda düşülür."""
        index = _device_index(device_name, "output")
        self.name = device_name
        self.buffer = RingBuffer(SAMPLE_RATE)  # 1 sn kapasite
        self.underruns = 0
        self._reads = 0
        self._primed = False
        channels = min(2, sd.query_devices(index)["max_output_channels"])
        for mode in ((True, False) if exclusive else (False,)):
            try:
                self.stream = sd.OutputStream(device=index, samplerate=SAMPLE_RATE, channels=channels,
                                              dtype="float32", latency="low", callback=self._callback,
                                              extra_settings=_wasapi_settings(exclusive=mode))
            except sd.PortAudioError:
                if not mode:
                    raise
                continue
            self.exclusive = mode
            break

    def _callback(self, outdata, frames, _time, _status) -> None:
        buf = self.buffer
        if not self._primed:
            if buf.fill < frames + PRIME:
                outdata.fill(0.0)
                return
            self._primed = True
        data = buf.read(frames)
        if data is None:  # takılma: sessizlik bas, tampon tekrar dolsun
            self._primed = False
            if self._reads > 50:  # akış başlarkenki ilk oturmayı sayma
                self.underruns += 1
            outdata.fill(0.0)
            return
        self._reads += 1
        excess = buf.fill - MAX_FILL
        if excess > 0:  # cihaz saatleri arasındaki kayma birikti
            buf.discard(excess)
        outdata[:] = data[:, None]

    def start(self) -> None:
        self.stream.start()

    def close(self) -> None:
        self.stream.abort()
        self.stream.close()


# ------------------------------------------------------------------- motor
@dataclass
class EngineStats:
    running: bool = False
    enabled: bool = True
    latency_ms: float = 0.0
    latency_parts: dict = field(default_factory=dict)
    dsp_load_pct: float = 0.0
    cpu_pct: float = 0.0
    input_db: float = -120.0
    output_db: float = -120.0
    auto_gain_db: float = 0.0
    gate_open: bool = False
    underruns: int = 0
    overflows: int = 0
    exclusive_input: bool = False
    exclusive_output: bool = False
    to_cable: bool = False          # çıkış gerçekten Discord'a giden CABLE mi
    error: str | None = None
    mode: str = DSP
    ai: object | None = None        # ai.live.AiStats (AI modunda)


class AudioEngine:
    def __init__(self, settings: VoiceSettings):
        self.chain = VoiceChain(SAMPLE_RATE, settings)
        self._input: sd.InputStream | None = None
        self._cable: OutputChannel | None = None
        self._monitor: OutputChannel | None = None
        self._outputs: tuple = ()
        self._process = psutil.Process()
        self._cpu_count = psutil.cpu_count() or 1
        self._load = 0.0
        self._cpu = 0.0
        self._input_db = -120.0
        self._output_db = -120.0
        self._overflows = 0
        self._error: str | None = None
        self._cue: np.ndarray | None = None
        self._exclusive_input = False
        self._mode = DSP                # şu an işlenen mod
        self._target_mode = DSP         # istenen mod (geçiş bitince _mode olur)
        self._switch_gain = 1.0
        self._ai = None                 # ai.live.AiLive
        self._ai_mix = 1.0              # AI modunda 1 = dönüştürülmüş, 0 = normal ses

    # ------------------------------------------------------------- yaşam döngüsü
    @property
    def running(self) -> bool:
        return self._input is not None

    def start(self, input_name: str, output_name: str, monitor_name: str | None = None,
              low_latency: bool = True) -> None:
        """low_latency: mikrofonu özel modda açmayı dene. Çıkışlar HER ZAMAN paylaşımlı.

        - Mikrofon özel modu yalnızca çıkış gerçekten CABLE ise kullanılır;
          aksi halde (ör. kulaklıkla test) Discord'un mikrofonu kullanmasını
          engellerdi.
        - CABLE Input asla özel modda açılmaz: VB-Cable özel modda sesi her
          ~10 ms'de bir parçalıyor (CABLE Output'tan geri kaydedilerek
          ölçüldü: 8 sn'de ~200 kesilme). Paylaşımlı modda kesilme yok.
        """
        if self.running:
            self.stop()
        self.chain.reset()
        self._mode = self._target_mode
        self._switch_gain = 1.0
        if self._ai is not None:
            self._ai.flush()
        self._error = None
        self._overflows = 0
        exclusive = low_latency and is_cable(output_name)
        try:
            self._cable = OutputChannel(output_name, exclusive=False)
            self._monitor = OutputChannel(monitor_name) if monitor_name else None
            self._outputs = tuple(ch for ch in (self._cable, self._monitor) if ch)
            self._input = self._open_input(input_name, exclusive)
            for channel in self._outputs:
                channel.start()
            self._input.start()
        except (sd.PortAudioError, EngineError) as exc:
            self.stop()
            raise EngineError(f"Ses akışı başlatılamadı: {exc}") from exc
        self._process.cpu_percent(None)  # CPU ölçümünü sıfırla

    def _open_input(self, name: str, exclusive: bool) -> sd.InputStream:
        """Mikrofonu aç; özel mod istenip açılamazsa paylaşımlı moda düş."""
        index = _device_index(name, "input")
        channels = min(2, sd.query_devices(index)["max_input_channels"])
        for mode in ((True, False) if exclusive else (False,)):
            try:
                stream = sd.InputStream(device=index, samplerate=SAMPLE_RATE, blocksize=BLOCK,
                                        channels=channels, dtype="float32", latency="low",
                                        callback=self._input_callback,
                                        extra_settings=_wasapi_settings(exclusive=mode))
            except sd.PortAudioError:
                if not mode:
                    raise
                continue
            self._exclusive_input = mode
            return stream
        raise EngineError("Mikrofon açılamadı.")

    def stop(self) -> None:
        """Önce girişi kapat (CABLE'a yeni ses gitmesin), sonra çıkışları."""
        stream, self._input = self._input, None
        if stream is not None:
            stream.abort()
            stream.close()
        outputs, self._outputs = self._outputs, ()
        for channel in outputs:
            channel.close()
        self._cable = self._monitor = None

    def set_monitor(self, monitor_name: str | None) -> None:
        """Çalışırken kulaklık monitörünü aç/kapat veya cihaz değiştir."""
        old = self._monitor
        new = OutputChannel(monitor_name) if monitor_name else None
        if new is not None:
            new.start()
        self._monitor = new
        self._outputs = tuple(ch for ch in (self._cable, new) if ch)
        if old is not None:
            old.close()

    # ----------------------------------------------------------------- kontrol
    @property
    def enabled(self) -> bool:
        return self.chain.enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled and not self.chain.enabled and self._ai is not None:
            self._ai.mark_valid_from_now()  # kapalıyken söylenenler dönüştürülüp tekrar duyulmasın
        self.chain.enabled = enabled
        self._cue = _cue_tone(enabled)

    @property
    def mode(self) -> str:
        return self._target_mode

    def set_mode(self, mode: str) -> None:
        """DSP ↔ AI. Çalışırken kısa bir kısma/açma ile geçilir."""
        if mode not in (DSP, AI):
            raise ValueError(mode)
        self._target_mode = mode
        if not self.running:
            self._mode = mode

    def set_ai(self, ai) -> None:
        """AI dönüştürücüyü (AiLive) değiştir; eskisi durdurulur. None: AI yok (AI modunda sessizlik)."""
        old, self._ai = self._ai, ai
        if old is not None and old is not ai:
            old.stop()

    @property
    def ai(self):
        return self._ai

    def toggle(self) -> bool:
        self.set_enabled(not self.chain.enabled)
        return self.chain.enabled

    def update(self, settings: VoiceSettings) -> None:
        self.chain.update(settings)

    # ---------------------------------------------------------------- callback
    def _input_callback(self, indata, frames, _time, status) -> None:
        if status.input_overflow:
            self._overflows += 1
        x = indata[:, 0] if indata.shape[1] == 1 else indata.mean(axis=1)
        x = np.ascontiguousarray(x, dtype=np.float32)
        self._input_db = 20.0 * np.log10(np.sqrt(np.mean(x * x)) + 1e-9)

        t0 = time.perf_counter()
        try:
            y = self._render(x)
        except Exception as exc:  # asla ham ses gönderme: sessizlik + toparlan
            self._error = f"{type(exc).__name__}: {exc}"
            y = np.zeros(frames, dtype=np.float32)
            try:
                self.chain.reset()
            except Exception:
                pass
        self._load = 0.95 * self._load + 0.05 * (time.perf_counter() - t0) / (frames / SAMPLE_RATE)
        self._output_db = 20.0 * np.log10(np.sqrt(np.mean(y * y)) + 1e-9)

        outputs = self._outputs
        if outputs:
            outputs[0].buffer.write(y)
        if len(outputs) > 1:
            outputs[1].buffer.write(self._with_cue(y))

    def _render(self, x: np.ndarray) -> np.ndarray:
        if self._target_mode != self._mode:  # geçiş: önce kıs, sonra modu değiştir
            self._switch_gain -= x.size / SWITCH_FADE
            if self._switch_gain <= 0.0:
                self._switch_gain = 0.0
                self._mode = self._target_mode
                self.chain.reset()
                self._ai_mix = 1.0 if self.chain.enabled else 0.0
                if self._mode == AI and self._ai is not None:
                    self._ai.flush()  # DSP'deyken birikmiş eski bağlamı unut
        elif self._switch_gain < 1.0:
            self._switch_gain = min(1.0, self._switch_gain + x.size / SWITCH_FADE)
        y = self._process_ai(x) if self._mode == AI else self.chain.process(x)
        if self._switch_gain < 1.0:
            y = y * np.float32(self._switch_gain)
        return y

    def _process_ai(self, x: np.ndarray) -> np.ndarray:
        """AI modu: ön işlem (DSP zincirinin ilk adımları) → AI. Normal ses = ön işlenmiş giriş."""
        chain = self.chain
        pre = chain.gate.process(chain.highpass.process(x))
        pre = chain.level.process(pre, chain.gate.is_open)
        ai = self._ai
        if ai is not None:
            ai.push(pre)
            wet = ai.pull(x.size)
        else:
            wet = np.zeros_like(pre)
        target = 1.0 if chain.enabled else 0.0
        if self._ai_mix == target:
            out = wet if target == 1.0 else pre
        else:
            step = 1.0 / (0.020 * SAMPLE_RATE)
            direction = 1.0 if target > self._ai_mix else -1.0
            ramp = np.clip(self._ai_mix + direction * step * np.arange(1, x.size + 1), 0.0, 1.0).astype(np.float32)
            self._ai_mix = float(ramp[-1])
            out = wet * ramp + pre * (1.0 - ramp)
        return chain.limiter.process(out * np.float32(chain.output_gain))

    def _with_cue(self, y: np.ndarray) -> np.ndarray:
        """Aç/kapa bip sesini YALNIZCA kulaklığa karıştır (Discord duymaz)."""
        cue = self._cue
        if cue is None:
            return y
        n = min(cue.size, y.size)
        mixed = y.copy()
        mixed[:n] += cue[:n]
        self._cue = cue[n:] if cue.size > n else None
        return mixed

    # ----------------------------------------------------------------- ölçüm
    def stats(self) -> EngineStats:
        stats = EngineStats(running=self.running, enabled=self.chain.enabled,
                            dsp_load_pct=self._load * 100.0, input_db=self._input_db,
                            output_db=self._output_db, auto_gain_db=self.chain.level.gain_db,
                            gate_open=self.chain.gate.is_open, overflows=self._overflows,
                            exclusive_input=self._exclusive_input, error=self._error, mode=self._target_mode,
                            ai=self._ai.stats() if self._ai is not None else None)
        if not self.running or self._cable is None:
            return stats
        # Kısa aralıklarda ölçüm çok oynak: üstel ortalama ile yumuşat
        sample = self._process.cpu_percent(None) / self._cpu_count
        self._cpu = 0.8 * self._cpu + 0.2 * sample
        stats.cpu_pct = self._cpu
        stats.underruns = self._cable.underruns
        stats.exclusive_output = self._cable.exclusive
        stats.to_cable = is_cable(self._cable.name)
        processing = (stats.ai.latency_ms if self._mode == AI and stats.ai is not None
                      else self.chain.latency_samples / SAMPLE_RATE * 1000.0)
        parts = {
            "giriş": self._input.latency * 1000.0,
            "işleme": processing,
            "tampon": self._cable.buffer.fill / SAMPLE_RATE * 1000.0,
            "çıkış": self._cable.stream.latency * 1000.0,
        }
        stats.latency_parts = parts
        stats.latency_ms = sum(parts.values())
        return stats


def _cue_tone(on: bool) -> np.ndarray:
    """Kısa bip: açılınca yükselen, kapanınca alçalan iki nota."""
    notes = (660.0, 990.0) if on else (990.0, 660.0)
    n = int(0.06 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    env = np.sin(np.pi * np.arange(n) / n)
    return np.concatenate([0.15 * env * np.sin(2 * np.pi * f * t) for f in notes]).astype(np.float32)
