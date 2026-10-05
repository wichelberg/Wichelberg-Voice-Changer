"""CPU ve GPU çıktısının aynı olduğunu doğrular (docs/DECISIONS.md D9: "aynı kalite").

Rastgele gürültüler girdi olarak verildiği için (bkz. rvc_onnx.NoiseBank) iki sağlayıcı aynı girdiyle
neredeyse bit-düzeyinde aynı sesi üretmeli. Eşitlik testini geçemeyen GPU kullanılmaz.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import stft

MIN_SNR_DB = 35.0          # dalga biçimi
MAX_LOGMEL_DB = 0.1        # konuşma karelerinde log-spektrum farkı (medyan)


def log_spectrum(y: np.ndarray, sr: int = 48000) -> np.ndarray:
    """80 log-aralıklı bantta güç (dB), 10 ms adım."""
    hop = sr // 100
    f, _, z = stft(y, sr, nperseg=2048, noverlap=2048 - hop)
    power = np.abs(z) ** 2
    edges = np.geomspace(60, min(16000, sr / 2), 81)
    bands = np.stack([power[(f >= a) & (f < b)].sum(0) for a, b in zip(edges[:-1], edges[1:])])
    return 10 * np.log10(bands + 1e-9)


def spectral_distance(ref: np.ndarray, got: np.ndarray, sr: int = 48000) -> tuple[float, float]:
    """Konuşma karelerinde ortalama |log-spektrum farkı|: (medyan, %95) dB."""
    a, b = log_spectrum(ref, sr), log_spectrum(got, sr)
    n = min(a.shape[1], b.shape[1])
    a, b = a[:, :n], b[:, :n]
    energy = a.max(0)
    speech = energy > energy.max() - 40
    if not speech.any():
        return 0.0, 0.0
    d = np.abs(a - b)[:, speech].mean(0)
    return float(np.median(d)), float(np.percentile(d, 95))


def waveform_snr(ref: np.ndarray, got: np.ndarray) -> float:
    n = min(len(ref), len(got))
    err = ref[:n] - got[:n]
    return float(10 * np.log10(np.sum(ref[:n] ** 2) / max(np.sum(err ** 2), 1e-20)))


@dataclass
class ParityResult:
    snr_db: float
    spectral_median_db: float
    spectral_p95_db: float

    @property
    def ok(self) -> bool:
        return self.snr_db >= MIN_SNR_DB and self.spectral_median_db <= MAX_LOGMEL_DB

    def describe(self) -> str:
        verdict = "AYNI" if self.ok else "FARKLI"
        return (f"{verdict}: dalga SNR {self.snr_db:.1f} dB (en az {MIN_SNR_DB:.0f}), spektral fark medyan "
                f"{self.spectral_median_db:.3f} dB (en çok {MAX_LOGMEL_DB}), %95 {self.spectral_p95_db:.3f} dB")


def compare(ref: np.ndarray, got: np.ndarray) -> ParityResult:
    median, p95 = spectral_distance(ref, got)
    return ParityResult(waveform_snr(ref, got), median, p95)
