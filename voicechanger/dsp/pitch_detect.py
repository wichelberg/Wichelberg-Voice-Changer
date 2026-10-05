"""YIN temel frekans (F0) tespiti, gerçek konuşma için sağlamlaştırılmış.

YIN (de Cheveigné & Kawahara, 2002) konuşmada güvenilir, basit ve ucuz bir
yöntemdir. Fark fonksiyonu FFT ile hesaplandığı için tek bir çerçeve
yalnızca birkaç on mikrosaniye sürer.

Gerçek (kısık, nefesli) erkek sesinde klasik tek eşikli YIN ötümlü
karelerin yarısını kaçırıyordu. Bu yüzden iki ekleme var:
  - Histerezis: ötümlü bölgeye girmek için katı (enter), içinde kalmak
    için gevşek (stay) eşik.
  - Oktav koruması: en iyiye yakın adaylardan en kısa periyot seçilir;
    önceki kareye yakın bir aday varsa o tercih edilir.
"""

import numpy as np
from scipy import fft as sfft


class Yin:
    def __init__(self, sample_rate: int, f0_min: float = 75.0, f0_max: float = 400.0,
                 enter_threshold: float = 0.45, stay_threshold: float = 0.65,
                 candidate_margin: float = 0.1, silence_db: float = -65.0):
        self.tau_min = int(sample_rate / f0_max)
        self.tau_max = int(np.ceil(sample_rate / f0_min))
        self.window = self.tau_max                      # entegrasyon penceresi W
        self.frame_length = self.window + self.tau_max  # gereken örnek sayısı
        self.nfft = 1 << int(np.ceil(np.log2(self.frame_length)))
        self.enter_threshold = enter_threshold
        self.stay_threshold = stay_threshold
        self.candidate_margin = candidate_margin
        self.silence_power = 10.0 ** (silence_db / 10.0)
        self._taus = np.arange(self.tau_max + 1)
        self.reset()

    def reset(self) -> None:
        self._previous = 0.0  # önceki karenin periyodu (0 = ötümsüz)

    def period(self, frame: np.ndarray) -> float:
        """Çerçevenin periyodunu örnek cinsinden döndür; sessiz/ötümsüzse 0.

        Ardışık çerçevelerle çağrılmalıdır (önceki sonucu hatırlar).
        """
        self._previous = self._estimate(frame)
        return self._previous

    def _estimate(self, frame: np.ndarray) -> float:
        x = frame.astype(np.float64, copy=False)
        if np.mean(x * x) < self.silence_power:
            return 0.0

        cmndf = self._cmndf(x)
        search = cmndf[self.tau_min:self.tau_max + 1]
        minima = np.flatnonzero((search[1:-1] <= search[:-2]) & (search[1:-1] <= search[2:])) + 1
        if minima.size == 0:
            return 0.0

        # En iyiye yakın adaylar; ilki (en kısa periyot) alt harmonik hatasını önler
        good = minima[search[minima] <= search[minima].min() + self.candidate_margin]
        i = good[0]
        if self._previous > 0.0:
            near = good[np.abs(good + self.tau_min - self._previous) < 0.15 * self._previous]
            if near.size:
                i = near[np.argmin(search[near])]

        threshold = self.stay_threshold if self._previous > 0.0 else self.enter_threshold
        if search[i] > threshold:
            return 0.0

        tau = i + self.tau_min
        # Parabolik interpolasyon ile kesirli periyot
        a, b, c = cmndf[tau - 1], cmndf[tau], cmndf[tau + 1]
        denom = a - 2.0 * b + c
        if abs(denom) > 1e-12:
            return tau + 0.5 * (a - c) / denom
        return float(tau)

    def _cmndf(self, x: np.ndarray) -> np.ndarray:
        """Birikimli ortalamaya göre normalize fark fonksiyonu."""
        w, tmax = self.window, self.tau_max
        # Çapraz korelasyon: corr[τ] = Σ_{j<W} x[j]·x[j+τ]
        spec = sfft.rfft(x, self.nfft)
        corr = sfft.irfft(spec * np.conj(sfft.rfft(x[:w], self.nfft)), self.nfft)[:tmax + 1]
        # Fark fonksiyonu: d(τ) = E(0..W) + E(τ..τ+W) - 2·corr(τ)
        cs = np.concatenate(([0.0], np.cumsum(x * x)))
        d = (cs[w] - cs[0]) + (cs[self._taus + w] - cs[self._taus]) - 2.0 * corr
        d[0] = 0.0
        np.maximum(d, 0.0, out=d)
        cmndf = np.ones_like(d)
        cmndf[1:] = d[1:] * self._taus[1:] / np.maximum(np.cumsum(d[1:]), 1e-12)
        return cmndf
