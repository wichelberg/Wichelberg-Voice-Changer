"""Nefes: sese eşlik eden yumuşak aspirasyon gürültüsü.

Kadın ses telleri titreşirken genellikle tam kapanmaz; aradan kaçan hava
sese hafif bir nefes katar. Bu hava her titreşimde darbe halinde çıkar.
Bu yüzden gürültü, sesin kendi dalga biçiminin (doğrultulmuş ve
yumuşatılmış) genliğiyle örnek örnek çarpılır. Böylece nefes ses
perdesiyle birlikte atar ve sesin "içinde" duyulur; arkada ayrı bir
hışırtı gibi duyulmaz. Sessizlikte (kapı kapalıyken) hiç gürültü eklenmez.
"""

import numpy as np
from scipy import signal

MAX_LEVEL = 0.5          # %100'de nefesin sese göre yaklaşık RMS oranı
ENVELOPE_CUTOFF_HZ = 900  # titreşim darbelerini koruyacak kadar hızlı zarf


class Breathiness:
    def __init__(self, sample_rate: int, seed: int | None = None):
        self._sos = signal.butter(2, [1500.0, 7000.0], btype="bandpass", fs=sample_rate, output="sos")
        impulse = np.zeros(8192)
        impulse[0] = 1.0
        # Beyaz gürültü filtreden geçince gücü düşer; birim RMS'e normalize et
        self._norm = 1.0 / np.sqrt(np.sum(signal.sosfilt(self._sos, impulse) ** 2))
        pole = np.exp(-2.0 * np.pi * ENVELOPE_CUTOFF_HZ / sample_rate)
        self._env_b, self._env_a = [1.0 - pole], [1.0, -pole]
        self._rng = np.random.default_rng(seed)
        self.amount = 0.0
        self.reset()

    def reset(self) -> None:
        self._zi = np.zeros((self._sos.shape[0], 2))
        self._env_zi = np.zeros(1)

    def process(self, voice: np.ndarray) -> np.ndarray:
        # Zarf durumu her zaman güncellenir ki slider açılınca sıçrama olmasın
        envelope, self._env_zi = signal.lfilter(self._env_b, self._env_a, np.abs(voice), zi=self._env_zi)
        amount = min(max(self.amount, 0.0), 1.0)
        if amount == 0.0 or not envelope.any():
            return voice
        noise, self._zi = signal.sosfilt(self._sos, self._rng.standard_normal(voice.size), zi=self._zi)
        # |sinüs| ortalaması RMS'in ~0.9'u: zarf ≈ anlık RMS
        breath = noise * envelope * (self._norm * MAX_LEVEL * amount * 1.1)
        return (voice + breath).astype(np.float32)
