"""Execution provider katmanı: varsayılan CPU, GPU'dan sessiz geri dönüş (docs/DECISIONS.md D9)."""

import unittest
from unittest import mock

import numpy as np

from voicechanger.ai import runtime as rt
from voicechanger.ai.shared import SHARED_MODELS

SMALL_MODEL = SHARED_MODELS["fcpe"].path  # en küçük ortak model (testlerde ONNX dosyası olarak)


class RuntimeConfigTests(unittest.TestCase):
    def test_default_is_cpu(self):
        self.assertEqual(rt.RuntimeConfig().accel, rt.CPU)
        self.assertEqual(rt.RuntimeConfig.from_dict(None).accel, rt.CPU)
        self.assertEqual(rt.Runtime().provider, rt.CPU)

    def test_unknown_accel_means_cpu(self):
        self.assertEqual(rt.RuntimeConfig.from_dict({"accel": "cuda"}).accel, rt.CPU)

    def test_gpu_without_directml_falls_back(self):
        with mock.patch.object(rt, "gpu_supported", return_value=False):
            runtime = rt.Runtime(rt.RuntimeConfig(accel=rt.GPU))
        self.assertEqual(runtime.provider, rt.CPU)
        self.assertIn("DirectML", runtime.fallback_reason)
        self.assertIn("GPU devre dışı", runtime.describe())

    def test_gpu_that_failed_parity_is_not_used(self):
        ai_config = {"runtime": {"accel": "gpu", "gpu_device_id": 3},
                     "benchmark": {"gpus": [{"device_id": 3, "parity_ok": False}]}}
        with mock.patch.object(rt, "gpu_supported", return_value=True):
            runtime = rt.Runtime.from_settings(ai_config)
        self.assertEqual(runtime.provider, rt.CPU)
        self.assertIn("eşitlik", runtime.fallback_reason)

    def test_gpu_that_passed_parity_is_used(self):
        ai_config = {"runtime": {"accel": "gpu", "gpu_device_id": 3},
                     "benchmark": {"gpus": [{"device_id": 3, "parity_ok": True}]}}
        with mock.patch.object(rt, "gpu_supported", return_value=True):
            self.assertEqual(rt.Runtime.from_settings(ai_config).provider, rt.GPU)


@unittest.skipUnless(SMALL_MODEL.is_file(), "ortak modeller kurulu değil")
class SessionFallbackTests(unittest.TestCase):
    def feeds(self):
        return {"audio": (0.1 * np.random.default_rng(0).standard_normal((1, 4800))).astype(np.float32)}

    def test_gpu_open_failure_falls_back_to_cpu(self):
        runtime = rt.Runtime(rt.RuntimeConfig(accel=rt.GPU))
        runtime.fallback_reason = None  # DirectML olmasa da GPU isteniyormuş gibi
        real_create = rt.Runtime._create

        def failing(self, path, provider, gpu_dims=None):
            if provider == rt.GPU:
                raise RuntimeError("sürücü yok")
            return real_create(self, path, provider, gpu_dims)

        with mock.patch.object(rt.Runtime, "_create", failing):
            session = runtime.session(SMALL_MODEL)
            out = session.run(self.feeds())
        self.assertEqual(session.provider, rt.CPU)
        self.assertEqual(runtime.provider, rt.CPU)
        self.assertIn("açılamadı", runtime.fallback_reason)
        self.assertEqual(out[0].shape[-1], 360)

    @unittest.skipUnless(rt.gpu_supported() and rt.list_gpus(), "DirectML GPU yok")
    def test_gpu_timeout_falls_back_and_still_returns(self):
        runtime = rt.Runtime(rt.RuntimeConfig(accel=rt.GPU))
        session = runtime.session(SMALL_MODEL)
        if session.provider != rt.GPU:
            self.skipTest(f"GPU açılamadı: {runtime.fallback_reason}")
        reference = rt.Runtime().session(SMALL_MODEL).run(self.feeds())[0]
        out = session.run(self.feeds(), timeout_s=1e-6)[0]
        self.assertEqual(runtime.provider, rt.CPU)
        self.assertIn("zaman aşımı", runtime.fallback_reason)
        np.testing.assert_allclose(out, reference, atol=1e-5)


if __name__ == "__main__":
    unittest.main()
