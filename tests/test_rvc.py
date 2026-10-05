"""RVC ONNX hattı: yardımcı fonksiyonlar (model gerektirmez) ve kurulu bir sesle uçtan uca kontroller."""

import unittest

import numpy as np

from voicechanger.ai import parity
from voicechanger.ai.base import ConvertParams
from voicechanger.ai.runtime import Runtime
from voicechanger.ai.rvc_onnx import (NoiseBank, RvcModel, RvcStream, StreamConfig, coarse_pitch, decode_fcpe,
                                      decode_rmvpe, fill_unvoiced, phase_advance)
from voicechanger.ai.shared import missing
from voicechanger.ai.testsignal import speech_like
from voicechanger.ai.voices import load_voice, scan_voices


def installed_voice():
    if missing():
        return None
    for entry in scan_voices():
        if entry.voice is not None:
            return load_voice(entry.folder)
    return None


class HelperTests(unittest.TestCase):
    def test_decode_rmvpe_peak(self):
        salience = np.zeros((3, 360), np.float32)
        salience[0, 100] = 1.0              # tek tepe: o binin merkez centi
        salience[1, 50:52] = 0.5            # iki eşit komşu: arası
        f0 = decode_rmvpe(salience)
        self.assertAlmostEqual(f0[0], 10 * 2 ** ((20 * 100 + 1997.3794084376191) / 1200), places=2)
        self.assertGreater(f0[1], 10 * 2 ** ((20 * 50 + 1997.38) / 1200))
        self.assertEqual(f0[2], 0.0)        # eşik altı: ötümsüz

    def test_decode_fcpe_uses_table(self):
        table = np.linspace(1000, 6000, 360).astype(np.float32)
        latent = np.zeros((2, 360), np.float32)
        latent[0, 200] = 0.9
        f0 = decode_fcpe(latent, table)
        self.assertAlmostEqual(f0[0], 10 * 2 ** (table[200] / 1200), places=1)
        self.assertEqual(f0[1], 0.0)

    def test_fill_unvoiced_interpolates(self):
        f0 = np.array([0, 100, 0, 0, 200, 0], np.float32)
        np.testing.assert_allclose(fill_unvoiced(f0), [100, 100, 133.33333, 166.66667, 200, 200], rtol=1e-5)
        np.testing.assert_array_equal(fill_unvoiced(np.zeros(4, np.float32)), np.zeros(4))

    def test_coarse_pitch_range(self):
        np.testing.assert_array_equal(coarse_pitch(np.array([0.0, 50.0, 1100.0, 5000.0])), [1, 1, 255, 255])

    def test_noise_bank_is_deterministic_and_wraps(self):
        a, b = NoiseBank(), NoiseBank()
        np.testing.assert_array_equal(a.frames(5, 10), b.frames(5, 10))
        np.testing.assert_array_equal(a.frames(-3, 2), a.frames(NoiseBank.FRAMES - 3, 2))
        self.assertEqual(a.samples(0, 400).shape, (1, 400, 1))

    def test_phase_advance(self):
        # 100 Hz, 40 kHz, 400 örnek/kare: kare başına tam 1 tur → faz değişmez
        self.assertAlmostEqual(phase_advance(np.full(7, 100.0), 400, 40000), 0.0, places=6)
        self.assertAlmostEqual(phase_advance(np.full(1, 25.0), 400, 40000), 0.25, places=6)

    def test_stream_config_window_is_even(self):
        for block in (150, 200, 250, 300):
            t, f = StreamConfig(block_ms=block, context_ms=990).window()
            self.assertEqual(t % 2, 0)
            self.assertEqual(f % 32, 0)


@unittest.skipUnless(installed_voice() is not None, "ortak modeller veya kurulu ses yok")
class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.voice = installed_voice()
        cls.model = RvcModel(cls.voice, Runtime())
        cls.signal = speech_like(6.0, seed=3)
        cls.params = ConvertParams(index_rate=0.0)

    def test_offline_is_deterministic_and_same_length(self):
        a = self.model.convert_offline(self.signal, 4.0, self.params)
        b = self.model.convert_offline(self.signal, 4.0, self.params)
        self.assertEqual(len(a), len(self.signal))
        np.testing.assert_array_equal(a, b)
        self.assertLess(np.abs(a).max(), 1.0)

    def test_stream_close_to_offline(self):
        """Akış, offline'dan sadece farklı gürültü kadar + birkaç dB uzaklaşmalı."""
        reference = self.model.convert_offline(self.signal, 4.0, self.params)
        stream = RvcStream(self.model, StreamConfig(block_ms=250))
        n = len(self.signal) // stream.block_size * stream.block_size
        padded = np.concatenate([self.signal[:n], np.zeros(stream.block_size * 2, np.float32)])
        out = np.concatenate([stream.convert_chunk(padded[i:i + stream.block_size], 4.0, self.params)
                              for i in range(0, len(padded), stream.block_size)])
        out = out[stream.latency_samples:][:n]
        self.assertEqual(len(out), n)
        floor_model = RvcModel(self.voice, Runtime())
        floor_model.noise = NoiseBank(seed=99)
        floor = parity.spectral_distance(reference, floor_model.convert_offline(self.signal, 4.0, self.params))[0]
        dist = parity.spectral_distance(reference[:n], out)[0]
        self.assertLess(dist, floor + 3.0, f"akış {dist:.2f} dB, taban {floor:.2f} dB")

    def test_stream_chunk_size_is_enforced(self):
        stream = RvcStream(self.model, StreamConfig(block_ms=200))
        with self.assertRaises(ValueError):
            stream.convert_chunk(np.zeros(100, np.float32), 0.0, self.params)
        self.assertEqual(len(stream.convert_chunk(np.zeros(stream.block_size, np.float32), 0.0, self.params)),
                         stream.block_size)

    def test_index_blend(self):
        import faiss

        rng = np.random.default_rng(0)
        vectors = rng.standard_normal((64, 768)).astype(np.float32)
        index = faiss.IndexFlatL2(768)
        index.add(vectors)
        model = RvcModel.__new__(RvcModel)
        model.index, model.index_vectors = index, vectors
        query = vectors[:5] + 1e-3
        np.testing.assert_array_equal(model.blend_index(query, 0.0), query)
        np.testing.assert_allclose(model.blend_index(query, 1.0), vectors[:5], atol=1e-2)

    def test_protect_keeps_own_features_on_unvoiced(self):
        phone, raw = np.ones((4, 768), np.float32), np.zeros((4, 768), np.float32)
        voiced = np.array([True, False, True, False])
        out = RvcModel.protect(phone, raw, voiced, ConvertParams(protect=0.33))
        np.testing.assert_allclose(out[:, 0], [1, 0.33, 1, 0.33])
        self.assertIs(RvcModel.protect(phone, raw, voiced, ConvertParams(protect=0.5)), phone)


if __name__ == "__main__":
    unittest.main()
