"""RVC v2 çıkarımı, sadece ONNX Runtime ile (torch yok).

Hat: 48 kHz ses -> 16 kHz -> ContentVec (içerik) + RMVPE (perde) -> [index] -> üretici (40/48 kHz) -> 48 kHz

- `RvcModel`: bir sesin modelleri + temel adımlar. `convert_offline` tüm kaydı tek seferde çevirir (referans kalite).
- `RvcStream`: akış hâlinde çevirir (bağlam penceresi + SOLA crossfade); `convert_chunk` arayüzü.

Model girdileri training/export_onnx.py ile birebir aynıdır. Rastgele gürültüler mutlak kare indeksine bağlı
sabit bir tablodan gelir: akış ile offline ve CPU ile GPU aynı gürültüyü görür.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from math import gcd

import numpy as np
from scipy.signal import resample_poly

from .base import SAMPLE_RATE, ConvertParams, VoiceConverter
from .runtime import Runtime
from .shared import shared_path
from .voices import Voice

SR_16K = 16000
HOP_16K = 160                        # 10 ms kare
HOP_48K = SAMPLE_RATE // 100         # 480
F0_MIN, F0_MAX = 50.0, 1100.0
_MEL_MIN = 1127 * math.log(1 + F0_MIN / 700)
_MEL_MAX = 1127 * math.log(1 + F0_MAX / 700)
_CENTS = np.pad(20 * np.arange(360) + 1997.3794084376191, (4, 4))


# ----------------------------------------------------------------------------- yardımcılar
def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x.astype(np.float32, copy=False)
    g = gcd(src, dst)
    return resample_poly(x, dst // g, src // g).astype(np.float32)


def decode_rmvpe(salience: np.ndarray, threshold: float = 0.03) -> np.ndarray:
    """RMVPE çıktısı [F,360] -> f0 (Hz), ötümsüz kareler 0. RVC'nin to_local_average_cents'i ile aynı."""
    center = np.argmax(salience, axis=1)
    padded = np.pad(salience, ((0, 0), (4, 4)))
    idx = center[:, None] + np.arange(9)[None, :]
    local = np.take_along_axis(padded, idx, axis=1)
    cents = np.sum(local * _CENTS[idx], axis=1) / np.maximum(np.sum(local, axis=1), 1e-9)
    f0 = 10 * 2 ** (cents / 1200)
    f0[salience.max(axis=1) <= threshold] = 0.0
    return f0.astype(np.float32)


def decode_fcpe(latent: np.ndarray, cent_table: np.ndarray, threshold: float = 0.006) -> np.ndarray:
    """FCPE çıktısı [F,360] -> f0 (Hz). torchfcpe'nin latent2cents_local_decoder'ı ile aynı."""
    center = np.argmax(latent, axis=1)
    idx = np.clip(center[:, None] + np.arange(-4, 5)[None, :], 0, latent.shape[1] - 1)
    local = np.take_along_axis(latent, idx, axis=1)
    cents = np.sum(local * cent_table[idx], axis=1) / np.maximum(np.sum(local, axis=1), 1e-9)
    f0 = 10 * 2 ** (cents / 1200)
    f0[latent.max(axis=1) <= threshold] = 0.0
    return f0.astype(np.float32)


def fill_unvoiced(f0: np.ndarray) -> np.ndarray:
    """Ötümsüz kareleri komşu ötümlülerden doğrusal doldur (RVC ile aynı). Hiç ötümlü yoksa olduğu gibi."""
    voiced = f0 > 0
    if not voiced.any() or voiced.all():
        return f0.copy()
    out = f0.copy()
    out[~voiced] = np.interp(np.flatnonzero(~voiced), np.flatnonzero(voiced), f0[voiced])
    return out


def coarse_pitch(f0: np.ndarray) -> np.ndarray:
    mel = 1127 * np.log(1 + f0 / 700)
    mel = np.where(mel > 0, (mel - _MEL_MIN) * 254 / (_MEL_MAX - _MEL_MIN) + 1, mel)
    return np.rint(np.clip(mel, 1, 255)).astype(np.int64)


def phase_advance(f0: np.ndarray, upp: int, sample_rate: int) -> float:
    """Üretici içindeki sinüs kaynağının bu karelerde ilerlediği faz (tur, mod 1)."""
    step = np.fmod(f0.astype(np.float64) / sample_rate * upp + 0.5, 1.0) - 0.5
    return float(np.fmod(step.sum(), 1.0))


class NoiseBank:
    """Mutlak kare/örnek indeksine bağlı sabit gürültü tablosu."""

    FRAMES = 8192
    SAMPLES = 1 << 21

    def __init__(self, seed: int = 20261004):
        rng = np.random.default_rng(seed)
        self._rnd = rng.standard_normal((192, self.FRAMES), dtype=np.float32)
        self._audio = rng.standard_normal(self.SAMPLES, dtype=np.float32)

    def frames(self, start: int, count: int) -> np.ndarray:
        idx = np.arange(start, start + count) % self.FRAMES
        return self._rnd[:, idx][None]

    def samples(self, start: int, count: int) -> np.ndarray:
        idx = np.arange(start, start + count) % self.SAMPLES
        return self._audio[idx][None, :, None]


# ----------------------------------------------------------------------------- akış ayarı
@dataclass(frozen=True)
class StreamConfig:
    block_ms: int = 250          # bir parçanın uzunluğu (gecikmenin ana kısmı)
    context_ms: int = 1000       # geçmiş bağlam (içerik kodlayıcının gördüğü)
    crossfade_ms: int = 40       # parçalar arası SOLA crossfade (en fazla 40)
    search_ms: int = 10          # SOLA hizalama arama aralığı
    margin_ms: int = 0           # üreticiye kesimden önce fazladan kare (ölçümde kaliteye etkisi yok: 0)

    def frames(self) -> tuple[int, int, int, int, int]:
        """(blok B, bağlam X, crossfade C, arama S, pay M) kare (10 ms) cinsinden."""
        b, x, c, s = (max(1, round(v / 10)) for v in (self.block_ms, self.context_ms, self.crossfade_ms,
                                                       self.search_ms))
        m = max(0, round(self.margin_ms / 10))
        c = min(c, 4)
        if (x + c + s + b) % 2:  # ContentVec 2 kareyi bir öznitelik yapar: pencere çift olsun
            x += 1
        return b, x, c, s, m

    def window(self) -> tuple[int, int]:
        """(pencere T, perde penceresi F) kare. F: RMVPE için 32'nin katı."""
        b, x, c, s, _ = self.frames()
        return x + c + s + b, -(-(b + 6) // 32) * 32

    def gpu_dims(self, upp: int) -> dict[str, dict[str, int]]:
        """Her modelin girdi boyutları (DirectML'de oturum bu boyuta sabitlenir)."""
        b, x, c, s, m = self.frames()
        t, f = self.window()
        # Perde modeli sabitlenmez: FCPE, DirectML'de sabit boyutla yanlış sonuç veriyor (ölçüldü, 2026-10-04);
        # akışta zaten hep aynı boyutla çağrıldığı için ilk çalıştırmada hızlı yola girer.
        return {"contentvec": {"n": t * HOP_16K}, "generator": {"t": t, "n": (t - (x - m)) * upp}}


# ----------------------------------------------------------------------------- model
PITCH_METHODS = ("rmvpe", "fcpe")


class RvcModel:
    """stream verilirse model o akış ayarına bağlanır: GPU'da girdi boyutları sabitlenir (DirectML sadece sabit
    boyutta hızlı). Böyle bir model offline dönüştürmede kullanılamaz; offline için stream'siz ayrı model aç."""

    def __init__(self, voice: Voice, runtime: Runtime, pitch_method: str = "fcpe",
                 stream: StreamConfig | None = None):
        if pitch_method not in PITCH_METHODS:
            raise ValueError(f"bilinmeyen perde yöntemi: {pitch_method}")
        self.voice = voice
        self.runtime = runtime
        self.pitch_method = pitch_method
        self.stream = stream
        dims = stream.gpu_dims(voice.sample_rate // 100) if stream else {}
        self.contentvec = runtime.session(shared_path("contentvec"), dims.get("contentvec"))
        self.pitch = runtime.session(shared_path(pitch_method), dims.get("pitch"))
        if pitch_method == "fcpe":
            meta = self.pitch.metadata()
            self._cent_table = np.array(json.loads(meta["cent_table"]), np.float32)
            self._fcpe_threshold = float(meta.get("threshold", 0.006))
        self.generator = runtime.session(voice.model_path, dims.get("generator"))
        meta = self.generator.metadata()
        self.sample_rate = int(meta.get("sample_rate", voice.sample_rate))
        self.upp = int(meta.get("upp", self.sample_rate // 100))
        if self.sample_rate != voice.sample_rate:
            raise ValueError(f"model.onnx {self.sample_rate} Hz, voice.json {voice.sample_rate} Hz diyor")
        self.index = None
        self.index_vectors = None
        if voice.index_path is not None:
            import faiss

            # Arama ~0.2 ms; çok iş parçacığında OpenMP iş parçacıkları sonra boşta dönüp toplam CPU'nun ~%35'ini
            # yiyor ve ONNX'i %30 yavaşlatıyordu (ölçüldü, DECISIONS D25).
            faiss.omp_set_num_threads(1)
            data = np.frombuffer(voice.index_path.read_bytes(), dtype=np.uint8)  # Unicode yol sorunu olmasın
            self.index = faiss.deserialize_index(data)
            self.index_vectors = self.index.reconstruct_n(0, self.index.ntotal)
        self.noise = NoiseBank()

    def close(self) -> None:
        for sess in (self.contentvec, self.pitch, self.generator):
            sess.close()

    # -- adımlar
    def content(self, audio16: np.ndarray) -> np.ndarray:
        """ContentVec öznitelikleri, 50 kare/sn: [(N-400)//320 + 1, 768]."""
        return self.contentvec.run({"audio": audio16[None].astype(np.float32)})[0][0]

    def f0(self, audio16: np.ndarray) -> np.ndarray:
        """Kare başına f0 (Hz, ötümsüz 0), kare i'nin merkezi 160*i. N//160 + 1 kare."""
        frames = len(audio16) // HOP_16K + 1
        if self.pitch_method == "fcpe":
            latent = self.pitch.run({"audio": audio16[None].astype(np.float32)})[0][0]
            return decode_fcpe(latent[:frames], self._cent_table, self._fcpe_threshold)
        padded_frames = -(-frames // 32) * 32
        audio = np.zeros(HOP_16K * padded_frames - HOP_16K, np.float32)
        audio[: len(audio16)] = audio16
        salience = self.pitch.run({"audio": audio[None]})[0][0]
        return decode_rmvpe(salience[:frames])

    def blend_index(self, feats: np.ndarray, rate: float) -> np.ndarray:
        if self.index is None or rate <= 0 or len(feats) == 0:
            return feats
        score, ix = self.index.search(np.ascontiguousarray(feats, dtype=np.float32), 8)
        if (ix < 0).any():
            return feats
        weight = 1.0 / np.maximum(score, 1e-12) ** 2
        weight /= weight.sum(axis=1, keepdims=True)
        retrieved = np.sum(self.index_vectors[ix] * weight[:, :, None], axis=1)
        return (rate * retrieved + (1 - rate) * feats).astype(np.float32)

    def synthesize(self, phone: np.ndarray, f0: np.ndarray, skip: int, length: int, frame0: int,
                   phase: float, timeout_s: float | None = None) -> np.ndarray:
        """phone [T,768] ve f0 [T] (100 kare/sn) -> [skip, skip+length) karelerinin sesi (model hızında).

        frame0: phone[0]'ın mutlak kare indeksi (gürültü tablosu için). phase: skip karesindeki sinüs fazı.
        """
        t = len(phone)
        flow_head = max(skip - 24, 0)
        rnd = np.zeros((1, 192, t), np.float32)
        rnd[:, :, flow_head:] = self.noise.frames(frame0 + flow_head, t - flow_head)
        feeds = {
            "phone": phone[None].astype(np.float32),
            "phone_lengths": np.array([t], np.int64),
            "pitch": coarse_pitch(f0)[None],
            "pitchf": f0[None].astype(np.float32),
            "sid": np.zeros(1, np.int64),
            "rnd": rnd,
            "noise": self.noise.samples((frame0 + skip) * self.upp, length * self.upp),
            "skip_head": np.array(skip, np.int64),
            "return_length": np.array(length, np.int64),
            "phase": np.array([phase], np.float32),
        }
        return self.generator.run(feeds, timeout_s)[0][0, 0]

    def features(self, audio16: np.ndarray, frames: int, params: ConvertParams, from_frame: int = 0):
        """100 kare/sn içerik (index + protect uygulanmış) için ortak yol. Dönüş: [frames, 768]."""
        raw = self.content(audio16)
        raw = np.concatenate([raw, raw[-1:]], axis=0)             # RVC gerçek zamanlı ile aynı
        start = from_frame // 2
        blended = raw.copy()
        blended[start:] = self.blend_index(raw[start:], params.index_rate)
        phone = np.repeat(blended, 2, axis=0)[:frames]
        raw2 = np.repeat(raw, 2, axis=0)[:frames]
        if len(phone) < frames:                                   # kısa girişte son kareyi tekrarla
            phone = np.concatenate([phone, np.repeat(phone[-1:], frames - len(phone), 0)])
            raw2 = np.concatenate([raw2, np.repeat(raw2[-1:], frames - len(raw2), 0)])
        return phone, raw2

    @staticmethod
    def protect(phone: np.ndarray, raw: np.ndarray, voiced: np.ndarray, params: ConvertParams) -> np.ndarray:
        """Ötümsüz karelerde index'li öznitelik yerine kendi özniteliğe yaklaş (RVC 'protect')."""
        if params.protect >= 0.5:
            return phone
        weight = np.where(voiced, 1.0, params.protect).astype(np.float32)[:, None]
        return phone * weight + raw * (1 - weight)

    # -- tüm kayıt
    def convert_offline(self, audio48: np.ndarray, f0_shift_st: float, params: ConvertParams) -> np.ndarray:
        """Bütün kaydı tek parça çevirir (akıştaki bağlam sınırı yok): kalite referansı."""
        if any(sess.fixed_shape for sess in (self.contentvec, self.pitch, self.generator)):
            raise RuntimeError("Bu model akış için sabit boyutla açıldı; offline için stream'siz RvcModel kullan")
        pad = SR_16K  # 1 sn yansıtmalı dolgu (RVC offline gibi)
        audio16 = resample(audio48, SAMPLE_RATE, SR_16K)
        n = len(audio16)
        padded = np.pad(audio16, (pad, pad), mode="reflect") if n > pad else np.pad(audio16, (pad, pad))
        frames = len(padded) // HOP_16K
        raw_f0 = self.f0(padded)[:frames]
        voiced = raw_f0 > 0
        f0 = fill_unvoiced(raw_f0) * 2 ** (f0_shift_st / 12)
        phone, raw = self.features(padded, frames, params)
        phone = self.protect(phone, raw, voiced, params)
        pad_frames = pad // HOP_16K
        out = self.synthesize(phone, f0, 0, frames, -pad_frames, 0.0)
        cut = pad_frames * self.upp
        out = out[cut: cut + n * self.sample_rate // SR_16K]
        return resample(out, self.sample_rate, SAMPLE_RATE)[: len(audio48)]


class RvcStream(VoiceConverter):
    """Parça parça dönüştürme. Her parçada pencere = [bağlam | crossfade | arama | yeni parça]."""

    def __init__(self, model: RvcModel, config: StreamConfig | None = None):
        if model.stream is not None:
            if config is not None and config != model.stream:
                raise ValueError("model başka bir akış ayarı için açılmış")
            config = model.stream
        self.model = model
        self.config = config or StreamConfig()
        b, x, c, s, m = self.config.frames()
        self.B, self.X, self.C, self.S, self.M = b, x, c, s, m
        self.T, self.F = self.config.window()        # pencere ve perde penceresi (kare)
        self.block_size = b * HOP_48K
        # Akış içi gecikme: çıkış parçası, girişin (C+S) kare öncesine karşılık gelir. Canlıda buna parçanın
        # kendisi (blok tamponlama) ve işlem süresi eklenir: toplam ≈ blok + latency + işlem.
        self.latency_samples = (c + s) * HOP_48K
        if self.F > self.T:
            raise ValueError("bağlam çok kısa")
        fade = np.sin(0.5 * np.pi * np.linspace(0.0, 1.0, c * HOP_48K)) ** 2
        self._fade_in = fade.astype(np.float32)
        self._fade_out = (1.0 - fade).astype(np.float32)
        self.reset()

    def reset(self) -> None:
        self._in48 = np.zeros(self.T * HOP_48K, np.float32)
        self._f0 = np.zeros(self.T, np.float32)       # ham f0 (ötümsüz 0), pencere kareleri
        self._sola = np.zeros(self.C * HOP_48K, np.float32)
        self._frame = -self.T                          # pencerenin ilk karesinin mutlak indeksi
        self._phase = 0.0                              # (X - M) karesindeki sinüs fazı
        self.last_sola_offset = 0
        self.last_f0 = np.zeros(self.B, np.float32)    # son parçanın ölçülen (kaydırılmamış) f0'ı

    def convert_chunk(self, audio: np.ndarray, f0_shift_st: float, params: ConvertParams,
                      timeout_s: float | None = None) -> np.ndarray:
        B, X, C, S, M, T, F = self.B, self.X, self.C, self.S, self.M, self.T, self.F
        if len(audio) != self.block_size:
            raise ValueError(f"parça {self.block_size} örnek olmalı, {len(audio)} geldi")
        self._in48 = np.concatenate([self._in48[self.block_size:], audio.astype(np.float32)])
        self._frame += B
        audio16 = resample(self._in48, SAMPLE_RATE, SR_16K)

        # perde: sadece son F karelik bölgede ölç, eskisi önbellekten (RVC gerçek zamanlı ile aynı eşleme)
        f0_new = self.model.f0(audio16[-(HOP_16K * F - HOP_16K):])
        self._f0 = np.concatenate([self._f0[B:], np.zeros(B, np.float32)])
        self._f0[T - F + 4:] = f0_new[3: F - 1]
        self.last_f0 = self._f0[X: X + B].copy()
        voiced = self._f0 > 0
        f0 = fill_unvoiced(self._f0) * 2 ** (f0_shift_st / 12)

        phone, raw = self.model.features(audio16, T, params, from_frame=X - M)
        phone = self.model.protect(phone, raw, voiced, params)
        skip = X - M
        out = self.model.synthesize(phone, f0, skip, T - skip, self._frame, self._phase, timeout_s)
        self._phase = math.fmod(self._phase + phase_advance(f0[X - M: X - M + B], self.model.upp,
                                                            self.model.sample_rate), 1.0)
        out = resample(out, self.model.sample_rate, SAMPLE_RATE)[M * HOP_48K:]   # kenar payını at

        # SOLA: önceki parçanın kuyruğuyla en iyi hizalanan kaymayı bul, crossfade yap
        n = C * HOP_48K
        search = out[: n + S * HOP_48K]
        num = np.correlate(search, self._sola, "valid")
        den = np.sqrt(np.convolve(search * search, np.ones(n, np.float32), "valid")) + 1e-8
        offset = int(np.argmax(num / den))
        self.last_sola_offset = offset
        result = out[offset: offset + self.block_size].copy()
        result[:n] = result[:n] * self._fade_in + self._sola * self._fade_out
        self._sola = out[offset + self.block_size: offset + self.block_size + n].copy()
        return result
