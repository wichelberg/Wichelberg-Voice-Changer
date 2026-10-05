"""Mikrofondan test kaydı ve seviye analizi."""

from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from .wavio import SAMPLE_RATE


@dataclass
class LevelReport:
    peak_db: float
    noise_floor_db: float
    speech_db: float

    @property
    def warnings(self) -> list[str]:
        out = []
        if self.peak_db >= -0.1:
            out.append("Kırpılma var. Windows'ta mikrofon seviyesini biraz düşür.")
        elif self.speech_db < -40:
            out.append("Ses çok kısık. Windows'ta mikrofon seviyesini yükselt.")
        return out


def record(seconds: float, device: int | None = None, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Blocking kayıt. Mono float32 döndürür."""
    audio = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=1,
                   dtype="float32", device=device)
    sd.wait()
    return audio[:, 0]


def block_levels_db(x: np.ndarray, block: int = 480) -> np.ndarray:
    frames = x[: x.size // block * block].reshape(-1, block).astype(np.float64)
    return 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-12)


def analyze_levels(x: np.ndarray) -> LevelReport:
    levels = block_levels_db(x)
    return LevelReport(
        peak_db=float(20 * np.log10(np.max(np.abs(x)) + 1e-12)),
        noise_floor_db=float(np.percentile(levels, 10)),
        speech_db=float(np.percentile(levels, 90)),
    )


def suggest_gate_threshold(x: np.ndarray) -> float:
    """Arka gürültünün 10 dB üstü; [-70, -30] dBFS aralığında."""
    return float(np.clip(round(analyze_levels(x).noise_floor_db + 10.0), -70.0, -30.0))
