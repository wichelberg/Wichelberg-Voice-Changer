"""AI modu kimde açık (D21, D27, D30). Model gerektirmez."""

import unittest

from voicechanger.ai import policy

GPU_OK = {"device_id": 0, "name": "RTX", "parity_ok": True,
          "blocks": [{"block_ms": 150, "p95_ms": 24.0}, {"block_ms": 200, "p95_ms": 23.0}]}
GPU_BAD = {"device_id": 1, "name": "iGPU", "parity_ok": False, "blocks": []}


def cfg(accel="cpu", cpu_ok=False, gpus=(), recommended=None):
    return {"runtime": {"accel": accel}, "benchmark": {
        "cpu_ai_ok": cpu_ok, "gpus": list(gpus), "cpu": [{"threads": 8, "blocks": [{"block_ms": 250, "p95_ms": 165.0}]}],
        "recommended": recommended or {}}}


class PolicyTests(unittest.TestCase):
    def test_no_benchmark_means_no_ai(self):
        result = policy.availability({"runtime": {"accel": "cpu"}, "benchmark": None})
        self.assertFalse(result.allowed)
        self.assertIn("Hız testi", result.reason)

    def test_cpu_allowed_only_if_benchmark_passed(self):
        self.assertTrue(policy.availability(cfg(cpu_ok=True)).allowed)
        self.assertFalse(policy.availability(cfg(cpu_ok=False)).allowed)

    def test_gpu_allows_ai_even_if_cpu_fails(self):
        self.assertTrue(policy.availability(cfg(accel="gpu", gpus=[GPU_OK])).allowed)

    def test_weak_cpu_with_good_gpu_suggests_gpu(self):
        result = policy.availability(cfg(accel="cpu", gpus=[GPU_OK]))
        self.assertFalse(result.allowed)
        self.assertIn("GPU hızlandırma", result.reason)

    def test_failed_parity_gpu_is_hidden(self):
        self.assertEqual(policy.gpu_choices(cfg(gpus=[GPU_BAD])), [])
        self.assertEqual([g["name"] for g in policy.gpu_choices(cfg(gpus=[GPU_OK, GPU_BAD]))], ["RTX"])
        result = policy.availability(cfg(accel="gpu", gpus=[GPU_BAD]))
        self.assertFalse(result.allowed)
        self.assertIn("DSP", result.reason)

    def test_block_and_expected_time(self):
        config = cfg(gpus=[GPU_OK], recommended={"gpu": {"block_ms": 150}})
        self.assertEqual(policy.block_ms_for(config, "gpu"), 150)
        self.assertEqual(policy.block_ms_for(config, "cpu"), policy.DEFAULT_BLOCK_MS["cpu"])
        self.assertEqual(policy.expected_proc_ms(config, "gpu", 150), 24.0)
        self.assertEqual(policy.expected_proc_ms(config, "cpu", 250), 165.0)
        self.assertIsNone(policy.expected_proc_ms(config, "cpu", 300))


class ApplyBenchmarkTests(unittest.TestCase):
    """Arayüzdeki hız testi sonucu ayarlara böyle yazılır (tools/benchmark.apply_result)."""

    def result(self, cpu=True):
        return {"cpu_ai_ok": cpu, "gpus": [GPU_OK], "recommended": {
            "provider": "gpu", "cpu": {"cpu_threads": 8, "block_ms": 250} if cpu else None,
            "gpu": {"gpu_device_id": 0, "block_ms": 150}}}

    def test_cpu_user_gets_cpu_block_and_gpu_is_not_enabled(self):
        from voicechanger.tools.benchmark import apply_result

        ai = {"runtime": {"accel": "cpu", "cpu_threads": 0}, "stream": {"block_ms": 300}}
        apply_result(ai, self.result())
        self.assertEqual(ai["runtime"]["accel"], "cpu")  # GPU kendiliğinden açılmaz (D9)
        self.assertEqual(ai["runtime"]["cpu_threads"], 8)
        self.assertEqual(ai["stream"]["block_ms"], 250)
        self.assertTrue(policy.availability(ai).allowed)

    def test_gpu_user_gets_gpu_block(self):
        from voicechanger.tools.benchmark import apply_result

        ai = {"runtime": {"accel": "gpu", "cpu_threads": 0}, "stream": {"block_ms": 300}}
        apply_result(ai, self.result(cpu=False))
        self.assertEqual(ai["stream"]["block_ms"], 150)
        self.assertEqual(ai["runtime"]["cpu_threads"], 0)


if __name__ == "__main__":
    unittest.main()
