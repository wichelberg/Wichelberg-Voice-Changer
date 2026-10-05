"""AI ses motorlarının ortak arayüzü (docs/DECISIONS.md D8).

Motor (engine.py) sadece bu arayüzü bilir; RVC, ileride MeanVC2 vb. bunun arkasında durur.
Ses hep 48 kHz mono float32 girer/çıkar; motor kendi içinde yeniden örnekler.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 48000


@dataclass
class ConvertParams:
    index_rate: float = 0.5     # 0: sadece kendi içerik, 1: tamamen hedef sesin index'i (tını sadakati)
    protect: float = 0.33       # ötümsüz seslerde (s, ş, nefes) index etkisini sınırla; 0.5 = kapalı


class VoiceConverter(ABC):
    block_size: int             # convert_chunk'a verilecek örnek sayısı (48 kHz)
    latency_samples: int        # algoritmik gecikme (işlem süresi hariç)

    @abstractmethod
    def convert_chunk(self, audio: np.ndarray, f0_shift_st: float, params: ConvertParams) -> np.ndarray:
        """`block_size` örnek al, aynı uzunlukta dönüştürülmüş ses ver."""

    @abstractmethod
    def reset(self) -> None:
        """Geçmişi unut (ör. akış yeniden başlarken)."""
