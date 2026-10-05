"""AI modu kimde, nasıl açık (docs/DECISIONS.md D21, D27, D30). Arayüz ve motor buradan karar okur.

- GPU seçeneği yalnızca hız testinde CPU ile eşitlik testini geçen GPU varsa gösterilir.
- CPU'da AI modu yalnızca hız testi oyun yükü altında geçtiyse açılır.
"""

from __future__ import annotations

from dataclasses import dataclass

from .runtime import GPU, RuntimeConfig

DEFAULT_BLOCK_MS = {"cpu": 250, "gpu": 150}


@dataclass
class AiAvailability:
    allowed: bool
    reason: str               # neden kapalı / nasıl çalışacak (kullanıcıya gösterilir)
    gpu_choices: list[dict]   # eşitlik testini geçen GPU'lar: {"device_id", "name"}


def benchmark(ai_cfg: dict) -> dict:
    return ai_cfg.get("benchmark") or {}


def gpu_choices(ai_cfg: dict) -> list[dict]:
    return [{"device_id": g["device_id"], "name": g["name"]}
            for g in benchmark(ai_cfg).get("gpus", []) if g.get("parity_ok")]


def availability(ai_cfg: dict) -> AiAvailability:
    bench = benchmark(ai_cfg)
    choices = gpu_choices(ai_cfg)
    runtime = RuntimeConfig.from_dict(ai_cfg.get("runtime"))
    if not bench:
        return AiAvailability(False, "Hız testi yapılmamış: Ses Kütüphanesi → \"Hız testini başlat\" "
                                     "(AI modu ondan sonra açılır).",
                              choices)
    if runtime.accel == GPU and choices:
        return AiAvailability(True, "GPU ile (DirectML).", choices)
    if bench.get("cpu_ai_ok"):
        text = "CPU ile."
        if choices:
            text += " GPU hızlandırma açılırsa daha düşük gecikme ve CPU yükü."
        return AiAvailability(True, text, choices)
    if choices:
        return AiAvailability(False, "Bu işlemci AI modunu oyunla birlikte kaldıramıyor (hız testi). "
                                     "\"GPU hızlandırma\"yı aç veya DSP modunu kullan.", choices)
    return AiAvailability(False, "Bu bilgisayarda AI modu oyunla birlikte gerçek zamanlı çalışmıyor (hız testi: "
                                 "uygun GPU yok, CPU yetmiyor). DSP modunu kullan.", choices)


def block_ms_for(ai_cfg: dict, accel: str) -> int:
    rec = benchmark(ai_cfg).get("recommended", {}).get(accel)
    return int(rec["block_ms"]) if rec else DEFAULT_BLOCK_MS[accel]


def expected_proc_ms(ai_cfg: dict, accel: str, block_ms: int) -> float | None:
    """Hız testinde bu sağlayıcı + parça boyutu için ölçülen %95 işlem süresi."""
    bench = benchmark(ai_cfg)
    groups = bench.get("gpus", []) if accel == GPU else bench.get("cpu", [])
    rows = [r for g in groups for r in g.get("blocks", []) if r.get("block_ms") == block_ms]
    return min((r["p95_ms"] for r in rows), default=None)
