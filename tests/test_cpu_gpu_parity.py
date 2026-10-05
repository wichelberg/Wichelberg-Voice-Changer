"""CPU ve GPU (DirectML) aynı girdiyle aynı sesi üretmeli (docs/DECISIONS.md D9).

Varsayılan GPU (en çok VRAM'li) sıkı kontrol edilir. Diğer GPU'lar bilgi olarak raporlanır: eşitliği
tutmayan GPU'yu uygulama zaten kullanmaz (hız testi kaydeder, Runtime.from_settings engeller).
"""

import unittest

import numpy as np

from voicechanger.ai import parity
from voicechanger.ai.base import ConvertParams
from voicechanger.ai.runtime import CPU, GPU, Runtime, RuntimeConfig, default_gpu, gpu_supported, list_gpus
from voicechanger.ai.rvc_onnx import RvcModel, RvcStream, StreamConfig
from voicechanger.ai.testsignal import speech_like

from tests.test_rvc import installed_voice

CONFIG = StreamConfig(block_ms=250)


def stream_output(voice, runtime: Runtime, signal: np.ndarray) -> np.ndarray:
    model = RvcModel(voice, runtime, "fcpe", CONFIG)
    stream = RvcStream(model)
    params = ConvertParams(index_rate=0.5)
    n = len(signal) // stream.block_size
    out = np.concatenate([stream.convert_chunk(signal[i * stream.block_size:(i + 1) * stream.block_size], 4.0,
                                               params) for i in range(n)])
    model.close()
    return out


@unittest.skipUnless(gpu_supported() and list_gpus(), "DirectML GPU yok")
@unittest.skipUnless(installed_voice() is not None, "ortak modeller veya kurulu ses yok")
class CpuGpuParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.voice = installed_voice()
        cls.signal = speech_like(5.0, seed=11)
        cls.reference = stream_output(cls.voice, Runtime(RuntimeConfig(accel=CPU)), cls.signal)

    def check(self, device_id: int) -> parity.ParityResult:
        runtime = Runtime(RuntimeConfig(accel=GPU, gpu_device_id=device_id))
        out = stream_output(self.voice, runtime, self.signal)
        if runtime.provider != GPU:
            self.skipTest(f"GPU kullanılamadı: {runtime.fallback_reason}")
        return parity.compare(self.reference, out)

    def test_default_gpu_matches_cpu(self):
        gpu = default_gpu()
        result = self.check(gpu.device_id)
        print(f"\n  {gpu.name}: {result.describe()}")
        self.assertTrue(result.ok, result.describe())

    def test_report_other_gpus(self):
        default = default_gpu().device_id
        for gpu in list_gpus():
            if gpu.device_id != default:
                print(f"\n  (bilgi) {gpu.name}: {self.check(gpu.device_id).describe()}")


if __name__ == "__main__":
    unittest.main()
