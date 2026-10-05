"""Tüm ses işlemcilerinin ortak arayüzü.

Ses motoru (audio_engine) ve offline dönüştürücü yalnızca bu arayüzü bilir.
İleride ONNX Runtime ile çalışan bir AI modeli eklemek için yeni bir
VoiceProcessor alt sınıfı yazmak yeterlidir; motor ve arayüz değişmez.
"""

from abc import ABC, abstractmethod

import numpy as np


class VoiceProcessor(ABC):
    """Akış (streaming) halinde mono float32 ses işleyen nesne.

    process() her çağrıda gelen blok kadar örnek döndürür. Algoritmanın
    sabit gecikmesi latency_samples ile bildirilir.
    """

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate

    @property
    @abstractmethod
    def latency_samples(self) -> int:
        """Algoritmanın eklediği sabit gecikme (örnek sayısı)."""

    @abstractmethod
    def process(self, block: np.ndarray) -> np.ndarray:
        """Bir blok mono float32 ses al, aynı uzunlukta blok döndür."""

    @abstractmethod
    def reset(self) -> None:
        """İç durumu sıfırla (akış yeniden başlarken)."""

    def set_params(self, **params) -> None:
        """Çalışırken parametre güncelle (ör. pitch_semitones=10)."""
        for name, value in params.items():
            if not hasattr(self, name):
                raise AttributeError(f"Bilinmeyen parametre: {name}")
            setattr(self, name, value)
