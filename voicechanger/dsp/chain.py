"""İşlem zinciri:
high-pass → gürültü kapısı → ses değiştirici → nefes → ton EQ → bypass karışımı
→ otomatik seviye → çıkış seviyesi → tepe sınırlayıcı.

Dönüştürme kapatıldığında (bypass) kuru ses de aynı gecikmeyle hizalanır
ve 20 ms crossfade ile geçilir. Böylece açma/kapama anında tıkırtı veya
"zıplama" duyulmaz. Otomatik seviye karışımdan sonra olduğu için normal
sesin de aynı seviyede gider.
"""

import numpy as np

from .base import VoiceProcessor
from .breath import Breathiness
from .gate import HighPass, NoiseGate
from .level import AutoLevel, PeakLimiter
from .params import VoiceSettings
from .psola import PsolaShifter
from .tone import ToneEQ


class VoiceChain:
    def __init__(self, sample_rate: int = 48000, settings: VoiceSettings | None = None,
                 processor: VoiceProcessor | None = None):
        self.sample_rate = sample_rate
        self.highpass = HighPass(sample_rate)
        self.gate = NoiseGate(sample_rate)
        self.processor = processor or PsolaShifter(sample_rate)
        self.breath = Breathiness(sample_rate)
        self.tone = ToneEQ(sample_rate)
        self.level = AutoLevel(sample_rate)
        self.limiter = PeakLimiter(sample_rate)
        self.enabled = True
        self._gain = 1.0
        self._mix = 1.0  # 1 = tamamen dönüştürülmüş, 0 = tamamen kuru
        self._mix_step = 1.0 / (0.020 * sample_rate)
        self._dry_delay = np.zeros(self.processor.latency_samples, dtype=np.float32)
        self._since_open = 1 << 30  # kapı en son kaç örnek önce açıktı
        self.update(settings or VoiceSettings())

    @property
    def output_gain(self) -> float:
        return self._gain

    @property
    def latency_samples(self) -> int:
        return self.processor.latency_samples

    def update(self, settings: VoiceSettings) -> None:
        """Ayarları uygula. Akış sürerken de güvenle çağrılabilir."""
        self.processor.set_params(**settings.processor_params())
        self.gate.threshold_db = settings.gate_threshold_db
        self.breath.amount = settings.breathiness
        self.tone.configure(settings.lowcut_hz, settings.chest_db, settings.softness, settings.air_db)
        self.level.enabled = settings.auto_level
        self._gain = 10.0 ** (settings.output_gain_db / 20.0)

    def reset(self) -> None:
        self.highpass.reset()
        self.gate.reset()
        self.processor.reset()
        self.breath.reset()
        self.tone.reset()
        self.level.reset()
        self.limiter.reset()
        self._dry_delay[:] = 0.0
        self._since_open = 1 << 30

    def process(self, block: np.ndarray) -> np.ndarray:
        x = self.gate.process(self.highpass.process(block))
        wet = self.tone.process(self.breath.process(self.processor.process(x)))
        dry = self._delay(x)

        target = 1.0 if self.enabled else 0.0
        if self._mix == target:
            out = wet if target == 1.0 else dry
        else:
            direction = 1.0 if target > self._mix else -1.0
            ramp = np.clip(self._mix + direction * self._mix_step * np.arange(1, x.size + 1), 0.0, 1.0)
            self._mix = float(ramp[-1])
            out = wet * ramp + dry * (1.0 - ramp)

        # Çıkış, girişten işlemci gecikmesi kadar geride: "konuşuyor" bilgisini de geciktir
        self._since_open = 0 if self.gate.is_open else self._since_open + x.size
        speaking = self._since_open <= self.latency_samples + x.size
        out = self.level.process(out, speaking) * np.float32(self._gain)
        return self.limiter.process(out)

    def _delay(self, x: np.ndarray) -> np.ndarray:
        """Kuru sesi işlemcinin gecikmesi kadar geciktir."""
        joined = np.concatenate((self._dry_delay, x))
        self._dry_delay = joined[x.size:]
        return joined[:x.size]
