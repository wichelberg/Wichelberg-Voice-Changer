"""Canlı AI yolu, ses kartı olmadan: motorun callback'i gerçek zamanlı tempoda çağrılır, CABLE'a yazılan
ses toplanır. Güvenlik kuralları (D4): model hazır değilken ve geç kalınca sessizlik, ham ses asla."""

import time
import unittest
from types import SimpleNamespace

import numpy as np

from tests.test_rvc import installed_voice
from voicechanger import engine as E
from voicechanger.ai.base import ConvertParams
from voicechanger.ai.live import READY, AiLive
from voicechanger.ai.runtime import Runtime, RuntimeConfig, default_gpu, gpu_supported
from voicechanger.ai.rvc_onnx import StreamConfig
from voicechanger.ai.testsignal import speech_like
from voicechanger.dsp import VoiceSettings


class Collector:
    """OutputChannel yerine: yazılanı biriktirir."""

    def __init__(self):
        self.parts = []
        self.buffer = self

    def write(self, y):
        self.parts.append(y.copy())

    def audio(self):
        return np.concatenate(self.parts) if self.parts else np.zeros(0, np.float32)


def run_engine(engine, signal, seconds, on_block=None):
    """Callback'i 10 ms'de bir çağır (gerçek zamanlı tempo)."""
    status = SimpleNamespace(input_overflow=False)
    block = E.BLOCK
    start = time.perf_counter()
    for i in range(int(seconds * 100)):
        due = start + i * 0.010
        while time.perf_counter() < due:
            time.sleep(0.001)
        x = signal[(i * block) % (len(signal) - block):][:block]
        engine._input_callback(x[:, None], block, None, status)
        if on_block:
            on_block(i)


@unittest.skipUnless(installed_voice() is not None, "ortak modeller veya kurulu ses yok")
class LiveAiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.voice = installed_voice()
        cls.signal = speech_like(12.0, seed=21) * 0.5

    def make_engine(self):
        """Kullanıcının gerçek yolu: GPU varsa GPU (150 ms), yoksa CPU (250 ms)."""
        engine = E.AudioEngine(VoiceSettings(gate_threshold_db=-70.0))
        cable = Collector()
        engine._outputs = (cable,)
        gpu = default_gpu() if gpu_supported() else None
        runtime = Runtime(RuntimeConfig(accel="gpu", gpu_device_id=gpu.device_id) if gpu else
                          RuntimeConfig(cpu_threads=8))
        block_ms = 150 if gpu else 250
        ai = AiLive(self.voice, runtime, StreamConfig(block_ms=block_ms),
                    params=ConvertParams(index_rate=0.0))
        engine.set_ai(ai)
        engine.set_mode(E.AI)
        return engine, ai, cable

    def test_silence_while_loading_then_converted(self):
        engine, ai, cable = self.make_engine()
        ai.start()
        loaded_at = []
        run_engine(engine, self.signal, 8.0, lambda i: loaded_at.append(i) if ai.state == READY and not loaded_at
                   else None)
        engine.set_ai(None)
        out = cable.audio()
        self.assertTrue(loaded_at, "model 8 sn içinde yüklenmedi")
        before = out[: loaded_at[0] * E.BLOCK]
        self.assertEqual(float(np.abs(before).max()), 0.0, "model yüklenirken CABLE'a ses gitti")
        stats = ai.stats()
        self.assertEqual(stats.late, 0, f"geç kalan parça: {stats.late}")
        after = out[loaded_at[0] * E.BLOCK + 48000:]
        self.assertGreater(float(np.sqrt(np.mean(after ** 2))), 1e-3, "dönüştürülmüş ses gelmedi")
        self.assertLessEqual(stats.latency_ms, 1.9 * stats.block_ms + 50.0)  # zamanlayıcının üst sınırı
        print(f"\n  yükleme {loaded_at[0] * 10} ms, AI gecikmesi ≈ {stats.latency_ms:.0f} ms, "
              f"işlem %95 {stats.proc_p95_ms:.0f} ms, konuşan F0 {stats.speaker_f0_hz}, "
              f"kaydırma {stats.applied_shift_st:+.1f} st")

    def test_no_replay_after_toggle_on(self):
        """Dönüştürme kapalıyken söylenenler, açılınca tekrar (dönüştürülmüş olarak) çalınmamalı."""
        engine, ai, cable = self.make_engine()
        ai.start()
        while ai.state != READY:
            time.sleep(0.05)
        signal = self.signal.copy()
        run_engine(engine, signal, 2.0)
        engine.set_enabled(False)
        run_engine(engine, np.zeros_like(signal) + 0.0, 1.0)      # kapalıyken sessiz
        mark = len(cable.parts)
        engine.set_enabled(True)
        quiet = np.zeros_like(signal)
        run_engine(engine, quiet, 1.0)                            # açınca giriş sessiz
        engine.set_ai(None)
        tail = np.concatenate(cable.parts[mark + 5:])              # ilk 50 ms geçiş sönümü hariç
        self.assertLess(float(np.abs(tail).max()), 0.02, "açılınca eski konuşma tekrar çalındı")

    def test_errors_give_silence(self):
        engine, ai, cable = self.make_engine()
        ai.start()
        while ai.state != READY:
            time.sleep(0.05)
        ai._stream.convert_chunk = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("test"))
        run_engine(engine, self.signal, 2.0)
        engine.set_ai(None)
        out = cable.audio()
        self.assertEqual(float(np.abs(out).max()), 0.0, "hata varken CABLE'a ses gitti")
        self.assertGreater(ai.stats().errors, 0)


if __name__ == "__main__":
    unittest.main()
