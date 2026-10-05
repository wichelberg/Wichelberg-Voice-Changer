"""voice.json doğrulama kuralları (docs/DECISIONS.md D11). Model gerektirmez."""

import json
import tempfile
import unittest
from pathlib import Path

from voicechanger.ai.voices import VoiceError, load_voice, scan_voices, sha256_file


def make_voice(root: Path, voice_id: str = "test_voice", **overrides) -> Path:
    folder = root / voice_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "model.onnx").write_bytes(b"sahte model")
    data = {
        "schema_version": 1, "id": voice_id, "display_name": "Test", "version": "1.0.0", "author": "Biri",
        "description": "", "model_type": "rvc_v2", "embedder": "contentvec_768", "sample_rate": 40000,
        "target_f0_median": 220.0, "default_index_rate": 0.5, "license": "CC-BY-4.0", "source": "Test verisi",
        "consent_note": "", "files": [{"name": "model.onnx", "sha256": sha256_file(folder / "model.onnx")}],
    }
    data.update(overrides)
    (folder / "voice.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


class VoiceManifestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_voice_loads(self):
        voice = load_voice(make_voice(self.root))
        self.assertEqual(voice.id, "test_voice")
        self.assertEqual(voice.model_path.name, "model.onnx")
        self.assertIsNone(voice.index_path)

    def test_empty_license_is_rejected(self):
        for value in ("", "   "):
            with self.subTest(value=repr(value)):
                with self.assertRaisesRegex(VoiceError, "license"):
                    load_voice(make_voice(self.root, license=value))

    def test_empty_source_is_rejected(self):
        with self.assertRaisesRegex(VoiceError, "source"):
            load_voice(make_voice(self.root, source=""))

    def test_missing_license_key_is_rejected(self):
        folder = make_voice(self.root)
        data = json.loads((folder / "voice.json").read_text(encoding="utf-8"))
        del data["license"]
        (folder / "voice.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(VoiceError, "license"):
            load_voice(folder)

    def test_id_must_match_folder(self):
        folder = make_voice(self.root, "klasor_adi", id="baska_id")
        with self.assertRaisesRegex(VoiceError, "Klasör"):
            load_voice(folder)

    def test_invalid_id(self):
        with self.assertRaisesRegex(VoiceError, "Geçersiz id"):
            load_voice(make_voice(self.root, "Kötü-İsim", id="Kötü-İsim"))

    def test_sha256_mismatch_is_rejected(self):
        folder = make_voice(self.root)
        (folder / "model.onnx").write_bytes(b"degistirilmis")
        with self.assertRaisesRegex(VoiceError, "sha256"):
            load_voice(folder)

    def test_missing_file_is_rejected(self):
        folder = make_voice(self.root)
        (folder / "model.onnx").unlink()
        with self.assertRaisesRegex(VoiceError, "eksik"):
            load_voice(folder)

    def test_model_must_be_listed(self):
        with self.assertRaisesRegex(VoiceError, "model.onnx"):
            load_voice(make_voice(self.root, files=[]))

    def test_path_in_file_name_is_rejected(self):
        files = [{"name": "../model.onnx", "sha256": "0" * 64}]
        with self.assertRaisesRegex(VoiceError, "Geçersiz dosya adı"):
            load_voice(make_voice(self.root, files=files))

    def test_unsupported_model_type(self):
        with self.assertRaisesRegex(VoiceError, "model türü"):
            load_voice(make_voice(self.root, model_type="meanvc2"))

    def test_out_of_range_numbers(self):
        with self.assertRaisesRegex(VoiceError, "target_f0_median"):
            load_voice(make_voice(self.root, target_f0_median=5))
        with self.assertRaisesRegex(VoiceError, "index_rate"):
            load_voice(make_voice(self.root, default_index_rate=1.5))

    def test_scan_lists_invalid_voices_with_reason(self):
        make_voice(self.root, "iyi_ses")
        make_voice(self.root, "lisanssiz", license="")
        entries = {e.folder.name: e for e in scan_voices(self.root)}
        self.assertIsNotNone(entries["iyi_ses"].voice)
        self.assertIsNone(entries["lisanssiz"].voice)
        self.assertIn("license", entries["lisanssiz"].error)


if __name__ == "__main__":
    unittest.main()
