"""Dosya dönüştürme: bir kaydı PSOLA (ve isteğe bağlı WORLD) ile işler.

PSOLA çıktısı, gerçek zamanlı motorun kullanacağı akış zincirinin aynısıyla
10 ms'lik bloklar halinde üretilir. Yani dosyada duyduğun ses, canlıda
duyacağın sesin aynısıdır.
"""

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import paths, wavio
from .dsp import Breathiness, HighPass, NoiseGate, ToneEQ, VoiceChain, VoiceSettings

SR = wavio.SAMPLE_RATE
BLOCK = 480  # 10 ms


@dataclass
class RenderStats:
    engine: str
    processing_s: float
    audio_s: float
    latency_ms: float | None = None
    block_mean_ms: float | None = None
    block_p99_ms: float | None = None
    block_max_ms: float | None = None

    @property
    def realtime_pct(self) -> float:
        return 100.0 * self.processing_s / self.audio_s

    def describe(self) -> str:
        text = (f"{self.engine}: {self.audio_s:.1f} sn ses {self.processing_s * 1000:.0f} ms'de işlendi "
                f"(yük: %{self.realtime_pct:.1f})")
        if self.block_mean_ms is not None:
            text += (f"\n   10 ms blok başına ort. {self.block_mean_ms:.2f} ms, "
                     f"en kötü {self.block_max_ms:.2f} ms · algoritma gecikmesi {self.latency_ms:.1f} ms")
        return text


@dataclass
class ConversionResult:
    psola_path: Path
    psola_stats: RenderStats
    world_path: Path | None
    world_stats: RenderStats | None
    input_f0_hz: float
    output_f0_hz: float


def render_psola(x: np.ndarray, settings: VoiceSettings) -> tuple[np.ndarray, RenderStats]:
    chain = VoiceChain(SR, settings)
    latency = chain.latency_samples
    padded = np.concatenate((x, np.zeros(latency + BLOCK, dtype=np.float32)))
    n_blocks = padded.size // BLOCK

    out = np.empty(n_blocks * BLOCK, dtype=np.float32)
    times = np.empty(n_blocks)
    for i in range(n_blocks):
        t0 = time.perf_counter()
        out[i * BLOCK:(i + 1) * BLOCK] = chain.process(padded[i * BLOCK:(i + 1) * BLOCK])
        times[i] = time.perf_counter() - t0

    stats = RenderStats("PSOLA", float(times.sum()), x.size / SR, latency / SR * 1000,
                        float(times.mean() * 1000), float(np.percentile(times, 99) * 1000),
                        float(times.max() * 1000))
    return out[latency:latency + x.size], stats


def render_world(x: np.ndarray, settings: VoiceSettings) -> tuple[np.ndarray, RenderStats]:
    """Adil karşılaştırma için aynı filtre, kapı, EQ ve seviye uygulanır."""
    from .dsp.world_offline import world_shift  # pyworld yalnızca gerektiğinde yüklensin

    hp, gate = HighPass(SR), NoiseGate(SR, threshold_db=settings.gate_threshold_db)
    gated = np.zeros_like(x)
    for i in range(0, x.size // BLOCK * BLOCK, BLOCK):
        gated[i:i + BLOCK] = gate.process(hp.process(x[i:i + BLOCK]))

    y, timings = world_shift(gated, SR, settings)
    breath, tone = Breathiness(SR), ToneEQ(SR)
    breath.amount = settings.breathiness
    tone.configure(settings.lowcut_hz, settings.chest_db, settings.softness, settings.air_db)
    for i in range(0, y.size, BLOCK):
        y[i:i + BLOCK] = tone.process(breath.process(y[i:i + BLOCK]))
    y = np.clip(y * 10 ** (settings.output_gain_db / 20), -1, 1).astype(np.float32)
    return y, RenderStats("WORLD", timings["analysis_s"] + timings["synthesis_s"], x.size / SR)


def median_f0(x: np.ndarray, f0_max: float = 400.0) -> float:
    """Kaydın ötümlü bölgelerindeki ortanca perde (Hz); bulunamazsa 0.

    Yalnızca bilgi amaçlı gösterge. Akıştaki YIN'den bağımsız bir ölçüm
    olsun diye WORLD'ün DIO + StoneMask F0 izleyicisi kullanılır.
    """
    import pyworld

    x64 = x.astype(np.float64)
    f0, times = pyworld.dio(x64, SR, f0_floor=60.0, f0_ceil=f0_max, frame_period=5.0)
    f0 = pyworld.stonemask(x64, f0, times, SR)
    voiced = f0[f0 > 0]
    return float(np.median(voiced)) if voiced.size else 0.0


def convert_recording(recording: Path, settings: VoiceSettings, with_world: bool = False) -> ConversionResult:
    x = wavio.load_mono(str(recording))

    y, psola_stats = render_psola(x, settings)
    psola_path = paths.output_path(recording, "psola")
    wavio.save(str(psola_path), y)

    world_path = world_stats = None
    if with_world:
        y_world, world_stats = render_world(x, settings)
        world_path = paths.output_path(recording, "world")
        wavio.save(str(world_path), y_world)

    return ConversionResult(psola_path, psola_stats, world_path, world_stats,
                            median_f0(x), median_f0(y, f0_max=600.0))


# ----------------------------------------------------------------------------- AI (stüdyo)
_AI_MODELS: dict = {}


@dataclass
class AiConversionResult:
    path: Path
    stats: RenderStats
    input_f0_hz: float
    output_f0_hz: float
    shift_st: float


def render_ai(x: np.ndarray, settings: VoiceSettings, voice, correction_st: float, params,
              pitch_method: str = "fcpe") -> tuple[np.ndarray, RenderStats, float, float]:
    """Canlı AI yolunun aynısı, dosya üzerinde: high-pass → kapı → otomatik seviye → RVC → sessizlik maskesi.

    Model CPU'da, dinamik boyutla açılır (canlıdaki GPU oturumu sabit boyutludur, ona dokunulmaz).
    Dönüş: (ses, istatistik, konuşanın F0'ı, uygulanan kaydırma).
    """
    from .ai.runtime import Runtime
    from .ai.rvc_onnx import RvcModel
    from .dsp.level import AutoLevel, PeakLimiter

    key = (voice.id, voice.version, pitch_method)
    model = _AI_MODELS.get(key)
    if model is None:
        _AI_MODELS.clear()  # bellekte tek model (D11)
        model = _AI_MODELS[key] = RvcModel(voice, Runtime(), pitch_method)

    hp, gate, level = HighPass(SR), NoiseGate(SR, threshold_db=settings.gate_threshold_db), AutoLevel(SR)
    level.enabled = settings.auto_level
    n = x.size // BLOCK * BLOCK
    pre = np.zeros(n, dtype=np.float32)
    active = np.zeros(n // BLOCK, dtype=bool)
    for i in range(0, n, BLOCK):
        block = gate.process(hp.process(x[i:i + BLOCK]))
        pre[i:i + BLOCK] = level.process(block, gate.is_open)
        active[i // BLOCK] = gate.is_open

    speaker = median_f0(pre)
    shift = float(np.clip(12 * np.log2(voice.target_f0_median / speaker), -12, 24)) if speaker else 0.0
    shift += correction_st
    t0 = time.perf_counter()
    y = model.convert_offline(pre, shift, params)
    elapsed = time.perf_counter() - t0

    # sessiz (kapı kapalı) anlarda RVC'nin kendi ürettiği gürültüyü sustur; ±10 ms pay, 5 ms rampa
    mask = active | np.roll(active, 1) | np.roll(active, -1)
    env = np.repeat(mask.astype(np.float32), BLOCK)
    ramp = int(0.005 * SR)
    env = np.convolve(env, np.ones(ramp, np.float32) / ramp, mode="same")
    limiter = PeakLimiter(SR)
    y = y[:n] * env * np.float32(10 ** (settings.output_gain_db / 20))
    out = np.concatenate([limiter.process(y[i:i + BLOCK]) for i in range(0, n, BLOCK)]) if n else y
    return out, RenderStats(f"AI ({voice.display_name})", elapsed, x.size / SR), speaker, shift


def convert_recording_ai(recording: Path, settings: VoiceSettings, voice, correction_st: float, params,
                         pitch_method: str = "fcpe") -> AiConversionResult:
    x = wavio.load_mono(str(recording))
    y, stats, speaker, shift = render_ai(x, settings, voice, correction_st, params, pitch_method)
    path = paths.output_path(recording, "ai")
    wavio.save(str(path), y)
    return AiConversionResult(path, stats, speaker, median_f0(y, f0_max=600.0), shift)
