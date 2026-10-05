"""Konuşmaya benzeyen sentetik test sinyali (repoya ses kaydı girmesin diye kodla üretilir).

Hız testi ve CPU-GPU eşitlik testi için: ötümlü bölgeler (değişen perde + formantlar), ötümsüz gürültü
patlamaları ve sessizlikler içerir. Deterministiktir.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

VOWELS = [(730, 1090, 2440), (270, 2290, 3010), (300, 870, 2240), (530, 1840, 2480), (570, 840, 2410)]


def _resonator(freq: float, bw: float, sr: int) -> tuple[np.ndarray, np.ndarray]:
    r = np.exp(-np.pi * bw / sr)
    a = [1.0, -2 * r * np.cos(2 * np.pi * freq / sr), r * r]
    return np.array([1 - r]), np.array(a)


def speech_like(seconds: float = 10.0, sr: int = 48000, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * sr), np.float64)
    pos = int(0.2 * sr)
    while pos < len(out) - sr // 2:
        kind = rng.random()
        dur = int(rng.uniform(0.15, 0.6) * sr)
        end = min(pos + dur, len(out))
        n = end - pos
        if kind < 0.7:  # ünlü: glottal darbe dizisi + formantlar
            f0 = rng.uniform(95, 170) * (1 + 0.08 * np.sin(np.linspace(0, rng.uniform(2, 6), n)))
            phase = np.cumsum(f0 / sr)
            src = np.diff(np.floor(phase), prepend=0.0) * 1.0
            src = lfilter([1.0], [1.0, -0.95], src)
            seg = np.zeros(n)
            for freq, bw in zip(VOWELS[rng.integers(len(VOWELS))], (80, 100, 140)):
                b, a = _resonator(freq, bw, sr)
                seg += lfilter(b, a, src)
            seg += 0.002 * rng.standard_normal(n)
        elif kind < 0.85:  # ötümsüz (s, ş): yüksek frekans gürültü
            b, a = _resonator(rng.uniform(3500, 6000), 2000, sr)
            seg = lfilter(b, a, rng.standard_normal(n)) * 0.3
        else:  # sessizlik
            seg = 0.0005 * rng.standard_normal(n)
        envelope = np.hanning(n) ** 0.3
        out[pos:end] += seg * envelope
        pos = end
    peak = np.max(np.abs(out)) or 1.0
    return (0.3 * out / peak).astype(np.float32)
