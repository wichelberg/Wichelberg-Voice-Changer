"""Hız testi: CPU ve (varsa) GPU'yu OYUN BENZERİ YÜK ALTINDA ölçer, ayar önerir, config.json'a yazar.

Kullanım:
    python -m voicechanger.tools.benchmark            # tam test (~4-6 dk)
    python -m voicechanger.tools.benchmark --quick    # kısa test
    python -m voicechanger.tools.benchmark --voice <id> --no-save
    python -m voicechanger.tools.benchmark --json sonuc.json   # config'e yazma, sonucu dosyaya ver (arayüz)

- Parçalar gerçek zamanlı tempoda gelir (canlıdaki gibi); arka planda mantıksal çekirdeklerin ~%60'ını meşgul
  eden 60 FPS'lik sahte "oyun" çalışır (tools/loadsim.py). Ölçülen: işlem süresi, geç kalan parça, bizim CPU
  yükü, oyunun kare hızı, GPU'da kullanım ve VRAM.
- Kurulu bir sesle ve kodla üretilen sentetik konuşmayla ölçer (repoya kayıt girmez).
- GPU yalnızca CPU ile eşitlik testini geçerse önerilir. GPU hızlandırma kendiliğinden AÇILMAZ (D9).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil

from voicechanger import paths, settings as config
from voicechanger.ai import parity
from voicechanger.ai.base import ConvertParams
from voicechanger.ai.runtime import CPU, GPU, Runtime, RuntimeConfig, cpu_name, gpu_supported, list_gpus, \
    physical_cores
from voicechanger.ai.rvc_onnx import RvcModel, RvcStream, StreamConfig
from voicechanger.ai.testsignal import speech_like
from voicechanger.ai.voices import VoiceError, load_voice, scan_voices
from voicechanger.tools.loadsim import GameLoad

CPU_BLOCKS_MS = (200, 250, 300)
GPU_BLOCKS_MS = (150, 200, 250)
LATENCY_LIMIT_MS = 500     # D8: ilk sürümlerde kabul edilen üst sınır
HEADROOM = 0.75            # işlem, parça süresinin en fazla %75'i (yük dalgalanmasına pay)
IO_MS = 30                 # ses kartı + VB-Cable tamponları (canlı yolda ölçülen ~25-35 ms)
RUN_S = 8.0                # her ölçüm (gerçek zamanlı)
SHIFT_ST = 5.0
PARAMS = ConvertParams(index_rate=0.5)


def _pick_voice(voice_id: str | None, cfg: dict):
    wanted = voice_id or cfg["ai"].get("active_voice")
    entries = [e for e in scan_voices() if e.voice is not None]
    if wanted:
        entries = [e for e in entries if e.voice.id == wanted] or entries
    if not entries:
        sys.exit("Kurulu ses yok. Hız testi bir ses modeliyle ölçer; önce bir ses kur.")
    try:
        return load_voice(entries[0].folder)
    except VoiceError as exc:
        sys.exit(f"Ses yüklenemedi: {exc}")


def convert_all(model: RvcModel, signal: np.ndarray) -> np.ndarray:
    """Arka arkaya (bekleme yok) çevir: CPU-GPU eşitlik karşılaştırması için."""
    stream = RvcStream(model)
    n = len(signal) // stream.block_size
    return np.concatenate([stream.convert_chunk(signal[i * stream.block_size:(i + 1) * stream.block_size],
                                                SHIFT_ST, PARAMS) for i in range(n)])


def realtime(model: RvcModel, signal: np.ndarray, load: GameLoad | None = None, gpu_stats=None) -> dict:
    """Parçaları gerçek zamanlı tempoda ver (canlıdaki gibi) ve ölç."""
    stream = RvcStream(model)
    block_ms = stream.config.block_ms
    chunks = min(int(RUN_S * 1000 / block_ms), len(signal) // stream.block_size - 1)
    stream.convert_chunk(signal[: stream.block_size], SHIFT_ST, PARAMS)  # ısınma
    proc = psutil.Process()
    proc.cpu_percent(None)
    if gpu_stats:
        gpu_stats.sample()
    if load:
        load.mark()
    times = []
    start = time.perf_counter()
    for i in range(chunks):
        due = start + (i + 1) * block_ms / 1000
        while time.perf_counter() < due:
            time.sleep(0.002)
        t = time.perf_counter()
        stream.convert_chunk(signal[(i + 1) * stream.block_size:(i + 2) * stream.block_size], SHIFT_ST, PARAMS)
        times.append(time.perf_counter() - t)
    times = np.array(times) * 1000
    p95 = float(np.percentile(times, 95))
    late = int(np.sum(times > 0.95 * block_ms))
    latency = block_ms + 50 + p95 + IO_MS  # 50: crossfade + SOLA arama
    row = {"block_ms": block_ms, "p50_ms": round(float(np.median(times)), 1), "p95_ms": round(p95, 1),
           "max_ms": round(float(times.max()), 1), "late": late, "chunks": chunks,
           "cpu_load_pct": round(proc.cpu_percent(None) / (psutil.cpu_count() or 1), 1),
           "latency_ms": round(latency),
           "ok": bool(late == 0 and p95 <= HEADROOM * block_ms and latency <= LATENCY_LIMIT_MS)}
    if load:
        row["game_fps"] = round(load.fps(), 1)
    if gpu_stats:
        g = gpu_stats.sample()
        row.update(gpu_util_pct=round(g.process_util_pct, 1), gpu_total_pct=round(g.total_util_pct, 1),
                   vram_mb=round(g.process_vram_mb))
    return row


def recommend(rows: list[dict], cpu_slack_ms: int = 50) -> dict | None:
    """En düşük gecikme; ondan en fazla cpu_slack_ms kötü olanlar arasından en az CPU yükü (GPU'da 0)."""
    ok = [r for r in rows if r["ok"]]
    if not ok:
        return None
    best = min(r["latency_ms"] for r in ok)
    near = [r for r in ok if r["latency_ms"] <= best + cpu_slack_ms]
    return min(near, key=lambda r: (r["cpu_load_pct"], r["latency_ms"]))


def _line(r: dict) -> str:
    text = (f"   parça {r['block_ms']:>3} ms: işlem medyan {r['p50_ms']:>4.0f} / %95 {r['p95_ms']:>4.0f} ms, "
            f"geç {r['late']}/{r['chunks']}, bizim CPU %{r['cpu_load_pct']:>4.1f}")
    if "gpu_util_pct" in r:
        text += f", GPU %{r['gpu_util_pct']:.0f}, VRAM {r['vram_mb']} MB"
    if "game_fps" in r:
        text += f", oyun {r['game_fps']:.1f} FPS"
    return text + f" → canlı gecikme ≈ {r['latency_ms']} ms {'✓' if r['ok'] else '✗'}"


def main() -> None:
    ap = argparse.ArgumentParser(description="AI ses dönüştürme hız testi (oyun benzeri yük altında)")
    ap.add_argument("--quick", action="store_true", help="daha az ölçüm")
    ap.add_argument("--voice", help="ölçümde kullanılacak ses id")
    ap.add_argument("--no-save", action="store_true", help="config.json'a yazma")
    ap.add_argument("--json", help="sonucu config.json yerine bu dosyaya yaz (arayüz kendisi uygular)")
    args = ap.parse_args()

    cfg = config.load_config()
    ai_cfg = cfg["ai"]
    voice = _pick_voice(args.voice, cfg)
    pitch_method = ai_cfg.get("pitch_method", "fcpe")
    context_ms = int(ai_cfg.get("stream", {}).get("context_ms", 1000))
    signal = speech_like(RUN_S + 2.0, seed=1)
    cores = physical_cores()
    logical = psutil.cpu_count() or cores
    candidates = (cores // 2, cores - 2) if args.quick else (2, 4, 6, cores - 2, cores)
    threads_list = sorted({t for t in candidates if 2 <= t <= cores})
    game_procs = max(2, round(0.6 * logical))
    gpus = list_gpus() if gpu_supported() else []
    total_steps = 1 + len(threads_list) * len(CPU_BLOCKS_MS) + len(gpus) * (1 + len(GPU_BLOCKS_MS))
    done_steps = 0

    def step(n: int = 1) -> None:  # arayüzdeki ilerleme çubuğu bu satırı okur
        nonlocal done_steps
        done_steps = min(total_steps, done_steps + n)
        print(f"[ilerleme] {done_steps}/{total_steps}", flush=True)

    system = {"cpu": cpu_name(), "physical_cores": cores, "logical_cores": logical,
              "ram_gb": round(psutil.virtual_memory().total / 2**30, 1)}
    print(f"İşlemci: {system['cpu']} ({cores} çekirdek / {logical} iş parçacığı), RAM {system['ram_gb']} GB")
    print(f"Ses: {voice.display_name} ({voice.sample_rate} Hz), perde: {pitch_method}, bağlam {context_ms} ms")
    with GameLoad(game_procs) as load:
        time.sleep(4)
        game_base = load.fps()
    print(f"Sahte oyun yükü: {game_procs} süreç, bizsiz {game_base:.1f} FPS\n")
    step()

    def stream_cfg(block_ms: int) -> StreamConfig:
        return StreamConfig(block_ms=block_ms, context_ms=context_ms)

    # ---------------------------------------------------------------- CPU (oyun yükü altında)
    cpu_results = []
    for threads in threads_list:
        runtime = Runtime(RuntimeConfig(accel=CPU, cpu_threads=threads))
        rows = []
        for block_ms in CPU_BLOCKS_MS:  # canlıdaki gibi: bir model = bir parça boyutu
            model = RvcModel(voice, runtime, pitch_method, stream_cfg(block_ms))
            with GameLoad(game_procs) as load:
                rows.append(realtime(model, signal, load))
            model.close()
            step()
        cpu_results.append({"threads": threads, "blocks": rows})
        print(f"CPU {threads} iş parçacığı (oyun yükü altında):")
        for r in rows:
            print(_line(r))

    # ---------------------------------------------------------------- GPU (oyun yükü altında)
    gpu_results = []
    if gpu_supported():
        from voicechanger.ai.gpustats import GpuStats

        try:
            gpu_stats = GpuStats()
        except OSError:
            gpu_stats = None
        ref_model = RvcModel(voice, Runtime(RuntimeConfig(accel=CPU)), pitch_method, stream_cfg(250))
        reference = convert_all(ref_model, signal[: 48000 * 6])
        ref_model.close()
        for gpu in gpus:
            runtime = Runtime(RuntimeConfig(accel=GPU, gpu_device_id=gpu.device_id))
            started = time.perf_counter()
            try:  # DirectML: her parça boyutu için sabit boyutlu oturum
                model = RvcModel(voice, runtime, pitch_method, stream_cfg(250))
            except Exception as exc:  # noqa: BLE001 — sürücü hatası raporlanır, test sürer
                print(f"\nGPU {gpu.name}: açılamadı ({exc})")
                step(1 + len(GPU_BLOCKS_MS))
                continue
            load_s = time.perf_counter() - started
            output = convert_all(model, signal[: 48000 * 6])
            model.close()
            if runtime.provider != GPU:
                print(f"\nGPU {gpu.name}: kullanılamadı ({runtime.fallback_reason})")
                step(1 + len(GPU_BLOCKS_MS))
                continue
            result = parity.compare(reference, output)
            print(f"\nGPU {gpu.name} (DirectML, {gpu.vram_mb} MB): CPU ile eşitlik → {result.describe()}")
            step()
            rows = []
            if result.ok:
                for block_ms in GPU_BLOCKS_MS:
                    model = RvcModel(voice, runtime, pitch_method, stream_cfg(block_ms))
                    with GameLoad(game_procs) as load:
                        rows.append(realtime(model, signal, load, gpu_stats))
                    model.close()
                    step()
                for r in rows:
                    print(_line(r))
            else:
                print("   Bu GPU kullanılmayacak ve ayarlarda gösterilmeyecek (sonuç CPU'dan farklı).")
                step(len(GPU_BLOCKS_MS))
            gpu_results.append({"device_id": gpu.device_id, "name": gpu.name, "vram_mb": gpu.vram_mb,
                                "load_s": round(load_s, 1), "parity_ok": result.ok,
                                "parity": {"snr_db": round(result.snr_db, 1),
                                           "spectral_median_db": round(result.spectral_median_db, 4),
                                           "spectral_p95_db": round(result.spectral_p95_db, 4)},
                                "blocks": rows})
    else:
        print("\nDirectML yok: GPU ölçülmedi.")

    # ---------------------------------------------------------------- öneri
    cpu_best = recommend([{**r, "cpu_threads": i["threads"]} for i in cpu_results for r in i["blocks"]])
    gpu_best = recommend([{**r, "gpu_device_id": i["device_id"], "name": i["name"]}
                          for i in gpu_results for r in i["blocks"]], cpu_slack_ms=0)
    min_threads = next((i["threads"] for i in cpu_results if any(r["ok"] for r in i["blocks"])), None)
    provider = GPU if gpu_best and (cpu_best is None or gpu_best["latency_ms"] + 30 < cpu_best["latency_ms"]
                                    or gpu_best["cpu_load_pct"] * 2 < cpu_best["cpu_load_pct"]) else CPU

    print("\n=== Öneri (oyun yükü altında) ===")
    if cpu_best:
        print(f"CPU: {cpu_best['cpu_threads']} iş parçacığı, parça {cpu_best['block_ms']} ms → canlı gecikme ≈ "
              f"{cpu_best['latency_ms']} ms, bizim CPU yükü ≈ %{cpu_best['cpu_load_pct']}")
    else:
        print(f"CPU: bu işlemci oyunla birlikte {LATENCY_LIMIT_MS} ms içinde güvenle çeviremiyor. "
              "AI modu için GPU gerekir; aksi hâlde DSP modunu kullan.")
    if gpu_best:
        print(f"GPU: {gpu_best['name']}, parça {gpu_best['block_ms']} ms → canlı gecikme ≈ {gpu_best['latency_ms']} ms, "
              f"GPU %{gpu_best.get('gpu_util_pct', 0):.0f}, VRAM {gpu_best.get('vram_mb', 0)} MB")
    if provider == GPU:
        print("Önerilen: GPU hızlandırma (ayarlardan 'GPU hızlandırma (deneysel)' ile açılır; kendiliğinden açılmaz).")
    if min_threads:
        print(f"Bu işlemcide oyunla birlikte en az {min_threads} iş parçacığı gerekiyor.")

    result = {"date": datetime.now().isoformat(timespec="seconds"), "system": system, "voice": voice.id,
              "sample_rate": voice.sample_rate, "pitch_method": pitch_method, "context_ms": context_ms,
              "quick": args.quick, "game_load": {"processes": game_procs, "fps_without_us": round(game_base, 1)},
              "cpu": cpu_results, "gpus": gpu_results, "cpu_ai_ok": cpu_best is not None,
              "recommended": {"provider": provider, "cpu": cpu_best, "gpu": gpu_best}, "min_threads": min_threads}
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return
    if args.no_save:
        return
    cfg = config.load_config()
    apply_result(cfg["ai"], result)
    config.save_config(cfg)
    print(f"\nSonuç kaydedildi: {paths.CONFIG_FILE.relative_to(paths.ROOT)} → ai.benchmark")


def apply_result(ai_cfg: dict, result: dict) -> None:
    """Hız testi sonucunu ve önerilen iş parçacığı / parça boyutunu ayarlara yaz (GPU'yu kendiliğinden açmaz)."""
    ai_cfg["benchmark"] = result
    cpu_best, gpu_best = result["recommended"]["cpu"], result["recommended"]["gpu"]
    if cpu_best:
        ai_cfg["runtime"]["cpu_threads"] = cpu_best["cpu_threads"]
    active = gpu_best if ai_cfg["runtime"].get("accel") == GPU and gpu_best else cpu_best
    if active:
        ai_cfg["stream"]["block_ms"] = active["block_ms"]


if __name__ == "__main__":
    main()
