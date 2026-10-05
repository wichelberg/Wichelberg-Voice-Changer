"""Ton EQ'su: kadınsı tınıyı şekillendiren dört filtre, tek zincirde.

  1. İncelik     : 4. derece high-pass (60–250 Hz), erkeksi gövdeyi ve
                   kaydırılamayan anlardan kalan erkek perdesini (~100–130 Hz)
                   keser; 200 Hz üstündeki kadın perdesine dokunmaz
  2. Göğüs       : peaking, ~300 Hz
  3. Yumuşaklık  : high-shelf, 2.5 kHz, en fazla -8 dB (sert harmonikler)
  4. Hava        : high-shelf, 8 kHz

Katsayılar RBJ "Audio EQ Cookbook" formülleriyle hesaplanır. Filtre durumu
bloklar arasında korunduğu için ayar değiştirirken tıkırtı oluşmaz.
"""

import numpy as np
from scipy import signal


def _peaking(fs: float, f0: float, gain_db: float, q: float) -> np.ndarray:
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2.0 * q)
    cos = np.cos(w0)
    b = [1 + alpha * a, -2 * cos, 1 - alpha * a]
    den = [1 + alpha / a, -2 * cos, 1 - alpha / a]
    return np.concatenate((b, den)) / den[0]


def _high_shelf(fs: float, f0: float, gain_db: float) -> np.ndarray:
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / fs
    cos = np.cos(w0)
    alpha = np.sin(w0) / 2.0 * np.sqrt(2.0)  # eğim S = 1
    k = 2.0 * np.sqrt(a) * alpha
    b = [a * ((a + 1) + (a - 1) * cos + k), -2 * a * ((a - 1) + (a + 1) * cos),
         a * ((a + 1) + (a - 1) * cos - k)]
    den = [(a + 1) - (a - 1) * cos + k, 2 * ((a - 1) - (a + 1) * cos), (a + 1) - (a - 1) * cos - k]
    return np.concatenate((b, den)) / den[0]


class ToneEQ:
    CHEST_HZ = 300.0
    CHEST_Q = 0.9
    SOFT_HZ = 2500.0
    SOFT_MAX_CUT_DB = 8.0
    AIR_HZ = 8000.0

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self._params = None
        self._zi = np.zeros((5, 2))
        self.configure()

    def configure(self, lowcut_hz: float = 80.0, chest_db: float = 0.0,
                  softness: float = 0.0, air_db: float = 0.0) -> None:
        params = (lowcut_hz, chest_db, softness, air_db)
        if params == self._params:
            return
        self._params = params
        fs = self.sample_rate
        sos = np.empty((5, 6))
        sos[0:2] = signal.butter(4, lowcut_hz, btype="highpass", fs=fs, output="sos")
        sos[2] = _peaking(fs, self.CHEST_HZ, chest_db, self.CHEST_Q)
        sos[3] = _high_shelf(fs, self.SOFT_HZ, -self.SOFT_MAX_CUT_DB * min(max(softness, 0.0), 1.0))
        sos[4] = _high_shelf(fs, self.AIR_HZ, air_db)
        # Tek atamayla değiştir: ses iş parçacığı asla yarım güncellenmiş katsayı görmez
        self._sos = sos

    def reset(self) -> None:
        self._zi[:] = 0.0

    def process(self, block: np.ndarray) -> np.ndarray:
        sos = self._sos  # yerel kopya: blok boyunca aynı katsayılar
        out, self._zi = signal.sosfilt(sos, block, zi=self._zi)
        return out.astype(np.float32)
