"""WAV okuma/yazma yardımcıları (soundfile = libsndfile; 16/24-bit ve float okur)."""

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SAMPLE_RATE = 48000  # Discord ve VB-Cable ile uyumlu


def load_mono(path: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    x = data.mean(axis=1)
    if sr != sample_rate:
        g = np.gcd(sr, sample_rate)
        x = resample_poly(x, sample_rate // g, sr // g).astype(np.float32)
    return x


def save(path: str, x: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    sf.write(path, x, sample_rate, subtype="PCM_16")
