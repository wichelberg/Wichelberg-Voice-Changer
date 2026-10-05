"""WORLD vokoder ile offline perde + formant kaydırma (yalnızca karşılaştırma için).

WORLD tüm dosyayı tek seferde analiz eder (F0 → Harvest, spektral zarf →
CheapTrick, aperiodiklik → D4C). Kalitesi iyidir ama bloklara bölününce
gerçek zamanlıda sınır bozulmaları ve yüksek CPU getirir. Bu modül sadece
PSOLA ile kulaktan karşılaştırma yapmak için var.
"""

import time

import numpy as np
import pyworld

from .params import PITCH_MODE_TARGET, VoiceSettings


def world_shift(x: np.ndarray, sample_rate: int, settings: VoiceSettings) -> tuple[np.ndarray, dict]:
    x64 = x.astype(np.float64)
    timings = {}

    t0 = time.perf_counter()
    f0, times = pyworld.harvest(x64, sample_rate, f0_floor=70.0, f0_ceil=400.0, frame_period=5.0)
    sp = pyworld.cheaptrick(x64, f0, times, sample_rate)
    ap = pyworld.d4c(x64, f0, times, sample_rate)
    timings["analysis_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    f0_new = _map_f0(f0, settings)
    sp_new = _warp_envelope(sp, settings.formant_ratio)
    y = pyworld.synthesize(f0_new, sp_new, ap, sample_rate, frame_period=5.0)
    timings["synthesis_s"] = time.perf_counter() - t0

    return y[:x.size].astype(np.float32), timings


def _map_f0(f0: np.ndarray, s: VoiceSettings) -> np.ndarray:
    """PSOLA ile aynı perde eşlemesi: çıkış = merkez + tonlama × (giriş - ortalama), log-frekansta."""
    voiced = f0 > 0
    if not voiced.any():
        return f0
    log_f0 = np.log(f0[voiced])
    ref = np.mean(log_f0)
    deviation = np.clip(log_f0 - ref, -np.log(2), np.log(2))
    if s.pitch_mode == PITCH_MODE_TARGET:
        center = np.log(s.target_f0_hz)
    else:
        center = ref + s.pitch_semitones * np.log(2) / 12.0
    out = f0.copy()
    out[voiced] = np.exp(center + s.intonation * deviation)
    return out


def _warp_envelope(sp: np.ndarray, ratio: float) -> np.ndarray:
    """Spektral zarfı frekans ekseninde ratio kat yukarı taşı: yeni[f] = eski[f/ratio]."""
    bins = np.arange(sp.shape[1])
    src = np.clip(bins / ratio, 0, sp.shape[1] - 1)
    lo = np.floor(src).astype(int)
    hi = np.minimum(lo + 1, sp.shape[1] - 1)
    frac = src - lo
    return np.ascontiguousarray(sp[:, lo] * (1.0 - frac) + sp[:, hi] * frac)
