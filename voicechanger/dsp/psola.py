"""Gerçek zamanlı PSOLA perde + formant kaydırıcı.

Yöntem (TD-PSOLA + grain yeniden örnekleme):
  1. YIN ile her 5 ms'de periyot (T) bulunur.
  2. Ötümlü (sesli) bölgelerde, her periyotta bir "analiz işareti" konur;
     işaretler bir önceki periyotla korelasyon yapılarak hizalanır.
  3. Her işaretin etrafından 2 periyotluk Hann pencereli bir parça (grain)
     alınır.
  4. PİTCH: grain'ler çıkışa T/β aralıkla eklenir. Grain'lerin içeriği
     değişmediği için formantlar yerinde kalır. β her grain için hesaplanır:
       - sabit mod : β = 2^(yarım_ton/12)
       - hedef mod : çıkışın ortalama perdesi hedef_Hz olacak şekilde
     Tonlama genişletme, perdenin kişinin ortalaması etrafındaki sapmasını
     büyütür (log-frekansta: çıkış = merkez + tonlama × sapma).
  5. FORMANT: her grain eklenmeden önce α oranında sıkıştırılır. Bu,
     spektral zarfı α kat yukarı taşır ve pitch'ten bağımsızdır.
  6. Ötümsüz bölgelerde (s, ş, f, nefes) sabit aralıklı overlap-add yapılır;
     yalnızca formant kaydırılır.

Gecikme sabittir: grain'in tamamı için girişin hazır olması gerekir.
"""

from bisect import bisect_right

import numpy as np

from .base import VoiceProcessor
from .params import PITCH_MODE_TARGET
from .pitch_detect import Yin

FORMANT_MIN = 0.9        # sabit gecikmeyi bu alt sınıra göre hesaplıyoruz
FORMANT_MAX = 1.5
PITCH_MIN_ST = -12.0
PITCH_MAX_ST = 16.0
BETA_MIN, BETA_MAX = 2.0 ** (PITCH_MIN_ST / 12), 2.0 ** (PITCH_MAX_ST / 12)
TREMOR_RATE_HZ = 5.5        # yaşlı seste titreme hızı (4-7 Hz)
TREMOR_PITCH_CENTS = 60.0   # titreme=1'de perde salınımı ±60 cent
TREMOR_AMPLITUDE = 0.30     # titreme=1'de şiddet salınımı ±%30
LN2 = float(np.log(2.0))
REF_F0_START_HZ = 120.0  # konuşmacının ortalama perdesi için başlangıç tahmini
REF_SMOOTHING = 0.004    # 5 ms'lik her çerçevede ortalamaya katkı (~1.3 sn)
MAX_BRIDGE_MS = 60.0     # YIN'in ünlü içindeki kısa "ötümsüz" kopmalarını köprüle
BRIDGE_MIN_SIMILARITY = 0.6


class PsolaShifter(VoiceProcessor):
    def __init__(self, sample_rate: int = 48000, pitch_semitones: float = 10.0,
                 formant_ratio: float = 1.17, pitch_mode: str = "semitones",
                 target_f0_hz: float = 220.0, intonation: float = 1.0, smoothness: float = 0.0,
                 tremor: float = 0.0, f0_min: float = 80.0, f0_max: float = 400.0):
        super().__init__(sample_rate)
        self.pitch_mode = pitch_mode
        self.pitch_semitones = pitch_semitones
        self.target_f0_hz = target_f0_hz
        self.intonation = intonation
        self.smoothness = smoothness
        self.tremor = tremor
        self.formant_ratio = formant_ratio
        self._rng = np.random.default_rng(5)

        self._yin = Yin(sample_rate, f0_min=f0_min, f0_max=f0_max)
        self._frame_hop = int(0.005 * sample_rate)          # 5 ms'de bir F0
        self._t_max = self._yin.tau_max                      # en uzun periyot
        self._unvoiced_half = int(0.00533 * sample_rate)     # ~10.7 ms grain
        self._unvoiced_hop = self._unvoiced_half // 2
        self._max_bridge = int(MAX_BRIDGE_MS * 1e-3 * sample_rate)

        out_half_max = int(np.ceil(self._t_max / FORMANT_MIN))
        self._latency = out_half_max + self._t_max + 32

        self._hist_size = 1 << 14
        self._out_size = 1 << 13
        self._hann_cache: dict[int, np.ndarray] = {}
        self._interp_cache: dict[tuple[int, float], np.ndarray] = {}
        self.reset()

    # ------------------------------------------------------------------ API
    @property
    def latency_samples(self) -> int:
        return self._latency

    @property
    def speaker_f0_hz(self) -> float:
        """Konuşmacının (girişin) ortalama perdesi; yavaşça güncellenir."""
        return float(np.exp(self._ref_log_f0))

    def reset(self) -> None:
        self._ref_log_f0 = float(np.log(REF_F0_START_HZ))
        self._voiced_frames = 0
        self._yin.reset()
        self._hist = np.zeros(self._hist_size, dtype=np.float32)
        self._end = 0                       # girişte alınan toplam örnek (mutlak)
        self._out = np.zeros(self._out_size, dtype=np.float32)
        self._out_base = 0                  # _out[0]'ın mutlak indeksi
        self._s = 0.0                       # sıradaki sentez işaretinin konumu
        self._frame_centers: list[int] = []
        self._frame_periods: list[float] = []
        self._next_frame_end = self._yin.frame_length
        self._mark_pos: list[int] = []
        self._mark_period: list[float] = []
        self._next_mark_guess = 0
        self._last_mark: int | None = None
        self._last_period = 0.0
        self._bridged = 0  # köprülenen ötümsüz süre (örnek)
        self._smooth_period = 0.0  # akıcılık için yumuşatılmış çıkış periyodu
        self._trem_phase = 0.0
        self._trem_rate = TREMOR_RATE_HZ
        self._zero_run = 0

    def process(self, block: np.ndarray) -> np.ndarray:
        block = np.asarray(block, dtype=np.float32)
        n = block.size
        self._push_input(block)

        # Uzun süredir sessizlik varsa (gürültü kapısı kapalı) hiçbir analiz
        # yapmadan sıfır döndür: CPU ≈ 0.
        if block.any():
            nz = np.flatnonzero(block)
            self._zero_run = n - 1 - nz[-1]
        else:
            self._zero_run += n
        if self._zero_run > self._latency + 2 * self._t_max + n:
            self._idle()
            return self._emit(n)

        self._analyze_pitch()
        self._place_marks()
        self._synthesize()
        return self._emit(n)

    # ------------------------------------------------------------ yardımcılar
    def _beta(self, period: float) -> float:
        """Bu periyottaki grain için perde oranı (çıkış F0 / giriş F0)."""
        log_f0 = np.log(self.sample_rate / period)
        # Ortalama etrafındaki sapma; oktav hatalarına karşı ±1 oktavla sınırlı
        deviation = min(max(log_f0 - self._ref_log_f0, -LN2), LN2)
        if self.pitch_mode == PITCH_MODE_TARGET:
            center = np.log(max(self.target_f0_hz, 1.0))
        else:
            st = min(max(self.pitch_semitones, PITCH_MIN_ST), PITCH_MAX_ST)
            center = self._ref_log_f0 + st * LN2 / 12.0
        log_out = center + self.intonation * deviation
        return float(min(max(np.exp(log_out - log_f0), BETA_MIN), BETA_MAX))

    @property
    def _alpha(self) -> float:
        return min(max(self.formant_ratio, FORMANT_MIN), FORMANT_MAX)

    def _push_input(self, block: np.ndarray) -> None:
        n = block.size
        self._hist[:-n] = self._hist[n:]
        self._hist[-n:] = block
        self._end += n

    def _slice(self, start: int, stop: int) -> np.ndarray:
        """Mutlak [start, stop) aralığını geçmiş tampondan döndür."""
        offset = self._hist_size - self._end
        return self._hist[start + offset:stop + offset]

    def _emit(self, n: int) -> np.ndarray:
        out = self._out[:n].copy()
        self._out[:-n] = self._out[n:]
        self._out[-n:] = 0.0
        self._out_base += n
        return out

    def _idle(self) -> None:
        """Sessizlikte durumu ucuzca güncel tut."""
        self._frame_centers.clear()
        self._frame_periods.clear()
        self._mark_pos.clear()
        self._mark_period.clear()
        self._last_mark = None
        self._yin.reset()
        self._next_frame_end = self._end + self._frame_hop
        self._next_mark_guess = self._end
        self._s = float(self._end)

    # ----------------------------------------------------------- 1) F0 takibi
    def _analyze_pitch(self) -> None:
        n_frame = self._yin.frame_length
        while self._next_frame_end <= self._end:
            stop = self._next_frame_end
            period = self._yin.period(self._slice(stop - n_frame, stop))
            self._frame_centers.append(stop - n_frame // 2)
            self._frame_periods.append(period)
            self._next_frame_end += self._frame_hop
            if period > 0.0:
                # İlk çerçevelerde gerçek ortalama, sonra yavaş üstel ortalama
                self._voiced_frames += 1
                weight = max(REF_SMOOTHING, 1.0 / self._voiced_frames)
                log_f0 = np.log(self.sample_rate / period)
                self._ref_log_f0 += weight * (log_f0 - self._ref_log_f0)
        if len(self._frame_centers) > 64:
            del self._frame_centers[:32]
            del self._frame_periods[:32]

    def _period_at(self, pos: int) -> float:
        """pos'a en yakın F0 çerçevesinin periyodu (0 = ötümsüz)."""
        centers = self._frame_centers
        if not centers:
            return 0.0
        i = bisect_right(centers, pos)
        if i == 0:
            return self._frame_periods[0]
        if i == len(centers):
            return self._frame_periods[-1]
        if pos - centers[i - 1] <= centers[i] - pos:
            return self._frame_periods[i - 1]
        return self._frame_periods[i]

    # ----------------------------------------------------- 2) analiz işaretleri
    def _place_marks(self) -> None:
        while True:
            guess = self._next_mark_guess
            period = self._period_at(guess)
            bridging = False
            if period <= 0.0:
                # YIN "ötümsüz" dedi. Az önce ötümlüysek ve dalga hâlâ önceki
                # periyoda benziyorsa kısa kopmayı köprüle (aşağıda kontrol).
                if self._last_mark is not None and self._bridged < self._max_bridge:
                    period, bridging = self._last_period, True
                else:
                    if guess + self._frame_hop > self._end:
                        break
                    self._next_mark_guess = guess + self._frame_hop // 2
                    self._last_mark = None
                    continue

            t = int(round(period))
            half = t // 2
            radius = max(2, t // 6)
            if guess + max(radius + half, t) > self._end:
                break

            if self._last_mark is None or guess - self._last_mark > 2 * t:
                # Ses başlangıcı: ilk periyottaki tepe noktasına hizala
                seg = self._slice(guess, guess + t)
                pos = guess + int(np.argmax(np.abs(seg)))
            else:
                pos, similarity = self._align(self._last_mark, guess, half, radius)
                if bridging and similarity < BRIDGE_MIN_SIMILARITY:
                    self._last_mark = None  # gerçekten ötümsüz: köprü yok
                    continue
                # Hizalanmış iki işaret arası mesafe, YIN tahmininden daha doğru
                # gerçek periyottur; sentez aralığını bununla hesaplıyoruz.
                spacing = pos - self._last_mark
                if 0.75 * period <= spacing <= 1.25 * period:
                    period = float(spacing)

            self._bridged = self._bridged + (pos - self._last_mark) if bridging else 0
            self._mark_pos.append(pos)
            self._mark_period.append(period)
            self._last_mark = pos
            self._last_period = period
            self._next_mark_guess = pos + t

        if len(self._mark_pos) > 128:
            del self._mark_pos[:64]
            del self._mark_period[:64]

    def _align(self, prev: int, guess: int, half: int, radius: int) -> tuple[int, float]:
        """Önceki işaretin dalga biçimine en çok benzeyen konumu bul.

        Döndürür: (konum, benzerlik). Benzerlik normalize korelasyondur
        (1 = birebir aynı dalga, ~0 = ilgisiz/gürültü).
        """
        ref = self._slice(prev - half, prev + half)
        seg = self._slice(guess - radius - half, guess + radius + half)
        corr = np.correlate(seg, ref, mode="valid")
        cs = np.concatenate(([0.0], np.cumsum(seg.astype(np.float64) ** 2)))
        energy = cs[2 * half:] - cs[:-2 * half]
        score = corr / np.sqrt(energy[:corr.size] + 1e-12)
        best = int(np.argmax(score))
        similarity = float(score[best] / np.sqrt(np.dot(ref, ref) + 1e-12))
        return guess - radius + best, similarity

    # ---------------------------------------------------------- 3) sentez (OLA)
    def _synthesize(self) -> None:
        alpha = self._alpha
        latency = self._latency
        while True:
            s = self._s
            t = s - latency  # bu çıkış anına denk gelen giriş anı

            voiced = self._marks_around(t)
            if voiced is not None:
                center, period, next_center, weight = voiced
                half = int(round(period))
            else:
                center, period, next_center, weight = int(np.floor(t)), 0.0, None, 0.0
                half = self._unvoiced_half

            start = int(round(s)) - int(half / alpha)
            if start >= self._end:
                break  # bu grain henüz üretilecek bloğa değmiyor
            if center + half >= self._end:
                break  # (olmamalı) giriş henüz hazır değil
            if next_center is not None and next_center + half >= self._end:
                next_center = None  # sonraki işaretin girişi henüz yok: tek grain

            pitch_mod, amp_mod = self._tremor_mod()
            if voiced is not None:
                smooth = self._smoothed(period)
                hop = smooth / (self._beta(smooth) * pitch_mod)
            else:
                hop = float(self._unvoiced_hop)
                self._smooth_period = 0.0

            grain = self._grain(center, half, alpha, next_center, weight)
            if grain is not None:
                gain = min(1.0, hop * alpha / half) * amp_mod
                self._overlap_add(start, grain * gain)
            self._advance_tremor(hop)
            self._s = s + hop

    def _tremor_mod(self) -> tuple[float, float]:
        """Titreme: (perde çarpanı, şiddet çarpanı). Şiddet salınımı perdeyi biraz geriden izler."""
        if self.tremor <= 0.0:
            return 1.0, 1.0
        depth = min(self.tremor, 1.0)
        pitch = 2.0 ** (depth * TREMOR_PITCH_CENTS * np.sin(self._trem_phase) / 1200.0)
        amp = 1.0 + depth * TREMOR_AMPLITUDE * np.sin(self._trem_phase - 0.8)
        return float(pitch), float(amp)

    def _advance_tremor(self, hop: float) -> None:
        """Titreme hızı yavaşça 4.5-6.5 Hz arasında gezinir (mekanik duyulmasın)."""
        if self.tremor <= 0.0:
            return
        dt = hop / self.sample_rate
        self._trem_phase = (self._trem_phase + 2 * np.pi * self._trem_rate * dt) % (2 * np.pi)
        drift = self._rng.normal(0.0, 1.5 * np.sqrt(dt))
        self._trem_rate = float(np.clip(self._trem_rate + drift, 4.5, 6.5))

    def _smoothed(self, period: float) -> float:
        """Akıcılık: periyottan periyoda titremeyi (jitter) üstel ortalamayla yumuşat.

        Erkek sesindeki pürüz/hırıltı büyük ölçüde bu titremeden gelir. Gerçek
        bir perde sıçramasında (>%16) ortalama sıfırlanır ki tonlama gecikmesin.
        """
        amount = min(max(self.smoothness, 0.0), 1.0)
        previous = self._smooth_period
        if amount == 0.0 or previous <= 0.0 or abs(np.log(period / previous)) > 0.15:
            self._smooth_period = period
        else:
            self._smooth_period = previous + (1.0 - 0.92 * amount) * (period - previous)
        return self._smooth_period

    def _marks_around(self, t: float):
        """t'yi çevreleyen iki ötümlü işaret ve t'nin aralarındaki konumu.

        Döndürür: (işaret, periyot, sonraki_işaret | None, ağırlık 0..1) ya da
        ötümsüzse None. Perde yükseltirken aynı grain art arda tekrarlanınca
        orijinal perdede "hayalet" titreşim oluşur; iki komşu grain'i ağırlıkla
        karıştırmak bunu önler.
        """
        i = bisect_right(self._mark_pos, t) - 1
        if i < 0:
            return None
        pos, period = self._mark_pos[i], self._mark_period[i]
        if t - pos > 1.25 * period:
            return None  # işaret çok eski: burası ötümsüz
        if i + 1 < len(self._mark_pos):
            nxt, next_period = self._mark_pos[i + 1], self._mark_period[i + 1]
            if nxt - pos <= 1.25 * period:
                weight = min(max((t - pos) / (nxt - pos), 0.0), 1.0)
                return pos, (1.0 - weight) * period + weight * next_period, nxt, weight
        return pos, period, None, 0.0

    def _grain(self, center: int, half: int, alpha: float,
               next_center: int | None = None, weight: float = 0.0) -> np.ndarray | None:
        """Hann pencereli, α oranında sıkıştırılmış grain (uzunluk 2·int(half/α)+1).

        next_center verilirse iki konumdaki parçalar weight oranında karıştırılır.
        """
        seg = self._slice(center - half, center + half + 1)
        if next_center is not None and weight > 0.0:
            seg = (1.0 - weight) * seg + weight * self._slice(next_center - half, next_center + half + 1)
        if not seg.any():
            return None
        grain = seg * self._hann(half)
        if alpha == 1.0:
            return grain
        positions = self._interp_positions(half, alpha)
        return np.interp(positions, np.arange(grain.size), grain).astype(np.float32)

    def _hann(self, half: int) -> np.ndarray:
        win = self._hann_cache.get(half)
        if win is None:
            win = np.hanning(2 * half + 3)[1:-1].astype(np.float32)
            self._hann_cache[half] = win
        return win

    def _interp_positions(self, half: int, alpha: float) -> np.ndarray:
        key = (half, alpha)
        positions = self._interp_cache.get(key)
        if positions is None:
            if len(self._interp_cache) > 2048:
                self._interp_cache.clear()
            out_half = int(half / alpha)
            positions = half + np.arange(-out_half, out_half + 1) * alpha
            self._interp_cache[key] = positions
        return positions

    def _overlap_add(self, start: int, grain: np.ndarray) -> None:
        offset = start - self._out_base
        if offset < 0:  # zaten çalınmış kısma düşen baş kısmı at
            grain = grain[-offset:]
            offset = 0
        self._out[offset:offset + grain.size] += grain
