"""Mikrofondan test kaydı al → data/recordings/kayit_<tarih>.wav

Kullanım:
    python -m voicechanger.tools.record
    python -m voicechanger.tools.record --list
    python -m voicechanger.tools.record --device 12 --seconds 15
"""

import argparse
import sys
import time

import sounddevice as sd

from voicechanger import paths, recorder, wavio


def list_inputs() -> None:
    hostapis = sd.query_hostapis()
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            print(f"  [{i:2}] {dev['name']}  ({hostapis[dev['hostapi']]['name']})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mikrofondan test kaydı al")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--device", type=int, default=None, help="giriş cihaz numarası (--list)")
    parser.add_argument("--list", action="store_true", help="giriş cihazlarını listele")
    args = parser.parse_args()

    if args.list:
        list_inputs()
        return

    device = args.device if args.device is not None else sd.default.device[0]
    print(f"  Mikrofon: [{device}] {sd.query_devices(device)['name']}")
    for remaining in (3, 2, 1):
        print(f"  Kayıt {remaining} saniye sonra başlıyor...", flush=True)
        time.sleep(1.0)
    print(f"  ● KAYIT BAŞLADI. {args.seconds:.0f} saniye konuş.", flush=True)
    try:
        x = recorder.record(args.seconds, args.device)
    except sd.PortAudioError as exc:
        sys.exit(f"  Kayıt başarısız: {exc}\n  Başka bir cihaz dene: --list")

    paths.ensure_dirs()
    out = paths.new_recording_path()
    wavio.save(str(out), x)
    report = recorder.analyze_levels(x)
    print(f"  ■ Kaydedildi: {out.relative_to(paths.ROOT)}")
    print(f"  Tepe {report.peak_db:.1f} dBFS · arka gürültü {report.noise_floor_db:.1f} dBFS"
          f" · konuşma {report.speech_db:.1f} dBFS")
    for warning in report.warnings:
        print(f"  ⚠ {warning}")


if __name__ == "__main__":
    main()
