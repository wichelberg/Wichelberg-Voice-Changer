"""Otomatik ses seviyesi (AGC) ve tepe sınırlayıcı.

AGC konuşma seviyesini ~0.3 sn'lik pencereyle ölçer ve sabit bir hedefe
(TARGET_DB) çeker. Yalnızca konuşurken (kapı açıkken) ölçer; sessizlikte
kazancı sabit tutar, yani arka plan gürültüsünü şişirmez. Kazanç yavaş
artar, hızlı azalır; "pompalama" duyulmaz. Sesin tınısına dokunmaz,
sadece seviyesini değiştirir.

Sınırlayıcı, çıkışın -1 dBFS'i aşmasını engeller (patlama/cızırtı olmaz).
"""

import numpy as np

TARGET_DB = -20.0          # konuşma RMS hedefi: Discord için yüksek ama güvenli
MAX_GAIN_DB = 30.0
MIN_GAIN_DB = -12.0
TIME_CONSTANT_S = 0.3      # seviye ölçüm penceresi
UP_DB_PER_S = 15.0         # kazanç artış hızı (yavaş: pompalama olmasın)
DOWN_DB_PER_S = 60.0       # kazanç azalış hızı (hızlı: ani bağırmada koru)
MIN_SPEECH_POWER = 1e-7    # -70 dBFS altını ölçüme katma


class AutoLevel:
    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self.enabled = True
        self.reset()

    def reset(self) -> None:
        self._power: float | None = None
        self.gain_db = 0.0

    def process(self, x: np.ndarray, speaking: bool) -> np.ndarray:
        dt = x.size / self.sample_rate
        target = self.gain_db
        if not self.enabled:
            target = 0.0
        else:
            power = float(np.mean(x.astype(np.float64) ** 2))
            if speaking and power > MIN_SPEECH_POWER:
                if self._power is None:
                    self._power = power
                else:
                    k = 1.0 - np.exp(-dt / TIME_CONSTANT_S)
                    self._power += k * (power - self._power)
            if self._power is not None:
                level_db = 10.0 * np.log10(self._power)
                target = min(max(TARGET_DB - level_db, MIN_GAIN_DB), MAX_GAIN_DB)

        step = min(max(target - self.gain_db, -DOWN_DB_PER_S * dt), UP_DB_PER_S * dt)
        start = 10.0 ** (self.gain_db / 20.0)
        self.gain_db += step
        end = 10.0 ** (self.gain_db / 20.0)
        if start == end:
            return x * np.float32(end) if end != 1.0 else x
        return (x * np.linspace(start, end, x.size, dtype=np.float32)).astype(np.float32)


class PeakLimiter:
    CEILING = 10.0 ** (-1.0 / 20.0)   # -1 dBFS
    ATTACK_S = 0.001
    RELEASE_DB_PER_S = 40.0

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self._attack = max(1, int(self.ATTACK_S * sample_rate))
        self.reset()

    def reset(self) -> None:
        self._gain = 1.0

    def process(self, x: np.ndarray) -> np.ndarray:
        peak = float(np.max(np.abs(x))) if x.size else 0.0
        needed = min(1.0, self.CEILING / peak) if peak > 0.0 else 1.0
        start = self._gain
        if needed < start:
            target = needed  # hızlı in: 1 ms içinde
        else:
            release = 10.0 ** (self.RELEASE_DB_PER_S * x.size / self.sample_rate / 20.0)
            target = min(needed, start * release, 1.0)
        self._gain = target
        if start == target == 1.0:
            out = x
        else:
            ramp = np.full(x.size, target, dtype=np.float32)
            n = min(self._attack, x.size)
            ramp[:n] = np.linspace(start, target, n, dtype=np.float32)
            out = x * ramp
        # Kalan (çok nadir) aşımlar için son güvenlik
        return np.clip(out, -1.0, 1.0).astype(np.float32)
