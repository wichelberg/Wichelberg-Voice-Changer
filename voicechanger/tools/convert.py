"""Bir kaydı dönüştür → data/outputs/

Kullanım:
    python -m voicechanger.tools.convert                       # en son kayıt, kayıtlı ayarlar
    python -m voicechanger.tools.convert --preset "Hafif yetişkin" --world
    python -m voicechanger.tools.convert --input data/recordings/x.wav --pitch 11 --formant 1.2
    python -m voicechanger.tools.convert --grid                # pitch × formant kombinasyonları
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from voicechanger import paths, render, settings as config, wavio


def main() -> None:
    parser = argparse.ArgumentParser(description="Kaydı dönüştür")
    parser.add_argument("--input", type=Path, default=None, help="varsayılan: en son kayıt")
    parser.add_argument("--preset", default=None, help="varsayılan: config.json'daki son ayarlar")
    parser.add_argument("--pitch", type=float, default=None, help="yarım ton (sabit kaydırma modu)")
    parser.add_argument("--formant", type=float, default=None)
    parser.add_argument("--world", action="store_true", help="WORLD karşılaştırması da üret")
    parser.add_argument("--grid", action="store_true", help="pitch × formant kombinasyonları üret")
    args = parser.parse_args()

    recordings = paths.list_recordings()
    recording = args.input or (recordings[0] if recordings else None)
    if recording is None or not recording.exists():
        sys.exit("Kayıt bulunamadı. Önce: python -m voicechanger.tools.record")

    config.ensure_builtin_presets()
    settings = (config.load_preset(args.preset) if args.preset
                else config.settings_from_config(config.load_config()))
    if args.pitch is not None:
        settings = replace(settings, pitch_mode="semitones", pitch_semitones=args.pitch)
    if args.formant is not None:
        settings = replace(settings, formant_ratio=args.formant)

    print(f"Kayıt: {recording.name}")
    result = render.convert_recording(recording, settings, with_world=args.world)
    print(f"Algılanan perde: {result.input_f0_hz:.0f} Hz → çıkış {result.output_f0_hz:.0f} Hz")
    print(f"  {result.psola_stats.describe()}\n  → {result.psola_path.relative_to(paths.ROOT)}")
    if result.world_stats:
        print(f"  {result.world_stats.describe()}\n  → {result.world_path.relative_to(paths.ROOT)}")

    if args.grid:
        grid_dir = paths.OUTPUTS_DIR / "grid" / recording.stem
        grid_dir.mkdir(parents=True, exist_ok=True)
        x = wavio.load_mono(str(recording))
        for pitch in (8, 10, 12):
            for formant in (1.12, 1.17, 1.22):
                variant = replace(settings, pitch_mode="semitones", pitch_semitones=pitch,
                                  formant_ratio=formant)
                y, _ = render.render_psola(x, variant)
                out = grid_dir / f"p{pitch:+d}_f{formant:.2f}.wav"
                wavio.save(str(out), y)
                print(f"  {out.relative_to(paths.ROOT)}")


if __name__ == "__main__":
    main()
