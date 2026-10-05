"""Yüksek geçiren filtre ve gürültü kapısı."""

import numpy as np
from scipy import signal


class HighPass:
    """80 Hz 2. derece Butterworth. Bloklar arasında durumu korur, tıkırtı yapmaz."""

    def __init__(self, sample_rate: int, cutoff_hz: float = 80.0):
        self._sos = signal.butter(2, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
        self.reset()

    def reset(self) -> None:
        self._zi = np.zeros((self._sos.shape[0], 2))

    def process(self, block: np.ndarray) -> np.ndarray:
        out, self._zi = signal.sosfilt(self._sos, block, zi=self._zi)
        return out.astype(np.float32)


class NoiseGate:
    """RMS tabanlı gürültü kapısı (histerezis + hold + yumuşak açılma/kapanma).

    Seviye threshold_db'yi geçince açılır. threshold_db - hysteresis_db
    altında hold_ms boyunca kalırsa kapanır. Kazanç rampalı değiştiği için
    tıkırtı oluşmaz.
    """

    def __init__(self, sample_rate: int, threshold_db: float = -45.0, hysteresis_db: float = 6.0,
                 attack_ms: float = 5.0, hold_ms: float = 150.0, release_ms: float = 80.0):
        self.sample_rate = sample_rate
        self.threshold_db = threshold_db
        self.hysteresis_db = hysteresis_db
        self._attack_step = 1.0 / max(1.0, attack_ms * 1e-3 * sample_rate)
        self._release_step = 1.0 / max(1.0, release_ms * 1e-3 * sample_rate)
        self._hold_samples = int(hold_ms * 1e-3 * sample_rate)
        self.reset()

    def reset(self) -> None:
        self._gain = 0.0
        self._open = False
        self._below_for = 0
        self.level_db = -120.0

    @property
    def is_open(self) -> bool:
        return self._open or self._gain > 0.0

    def process(self, block: np.ndarray) -> np.ndarray:
        n = block.size
        rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2) + 1e-12))
        self.level_db = 20.0 * np.log10(rms)

        if self.level_db >= self.threshold_db:
            self._open = True
            self._below_for = 0
        elif self.level_db < self.threshold_db - self.hysteresis_db:
            self._below_for += n
            if self._below_for >= self._hold_samples:
                self._open = False

        if self._open and self._gain >= 1.0:
            return block
        if not self._open and self._gain <= 0.0:
            return np.zeros_like(block)

        step = self._attack_step if self._open else -self._release_step
        ramp = np.clip(self._gain + step * np.arange(1, n + 1), 0.0, 1.0)
        self._gain = float(ramp[-1])
        return (block * ramp).astype(np.float32)
