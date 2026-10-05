"""Ses Kütüphanesi: zip içe aktarma / silme (docs/DECISIONS.md D11, D49). Model gerektirmez."""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from voicechanger import paths
from voicechanger.ai import library
from voicechanger.ai.voices import VoiceError, scan_voices
from tests.test_voices import make_voice


def zip_folder(folder: Path, dest: Path, prefix: str | None = None, extra: dict | None = None) -> Path:
    prefix = folder.name if prefix is None else prefix
    with zipfile.ZipFile(dest, "w") as z:
        for p in folder.iterdir():
            z.write(p, f"{prefix}/{p.name}" if prefix else p.name)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return dest


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.src = tmp / "kaynak"
        self.voices = tmp / "models" / "voices"
        self._patch = mock.patch.object(paths, "VOICES_DIR", self.voices)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def installed(self):
        return [e.voice.id for e in scan_voices(self.voices) if e.voice]

    def test_import_zip_with_folder(self):
        pkg = zip_folder(make_voice(self.src, "yeni_ses"), self.src / "yeni_ses.zip")
        preview = library.inspect(pkg)
        self.assertEqual(preview.voice.id, "yeni_ses")
        self.assertIsNone(preview.existing)
        voice = library.import_voice(pkg)
        self.assertEqual(voice.folder, self.voices / "yeni_ses")
        self.assertEqual(self.installed(), ["yeni_ses"])
        self.assertFalse((self.voices / library.STAGING).exists())

    def test_import_zip_flat_and_folder(self):
        folder = make_voice(self.src, "duz_ses")
        library.import_voice(zip_folder(folder, self.src / "duz.zip", prefix=""))
        self.assertEqual(self.installed(), ["duz_ses"])
        library.delete_voice("duz_ses")
        library.import_voice(folder)  # klasörden içe aktarma
        self.assertEqual(self.installed(), ["duz_ses"])

    def test_empty_license_rejected_and_nothing_installed(self):
        pkg = zip_folder(make_voice(self.src, "lisanssiz", license=""), self.src / "l.zip")
        with self.assertRaisesRegex(VoiceError, "license"):
            library.inspect(pkg)
        with self.assertRaisesRegex(VoiceError, "license"):
            library.import_voice(pkg)
        self.assertEqual(self.installed(), [])

    def test_sha_mismatch_rejected(self):
        folder = make_voice(self.src, "bozuk")
        (folder / "model.onnx").write_bytes(b"degistirilmis")
        with self.assertRaisesRegex(VoiceError, "sha256"):
            library.import_voice(zip_folder(folder, self.src / "b.zip"))
        self.assertFalse((self.voices / "bozuk").exists())
        self.assertFalse((self.voices / library.STAGING).exists())

    def test_zip_slip_rejected(self):
        pkg = zip_folder(make_voice(self.src, "kotu"), self.src / "k.zip", extra={"../../disari.txt": "x"})
        with self.assertRaisesRegex(VoiceError, "güvenli değil"):
            library.import_voice(pkg)
        self.assertFalse((self.voices / "kotu").exists())

    def test_not_a_voice_package(self):
        bad = self.src / "rastgele.zip"
        self.src.mkdir(parents=True)
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("bir_sey.txt", "x")
        with self.assertRaisesRegex(VoiceError, "voice.json"):
            library.inspect(bad)
        (self.src / "zip_degil.zip").write_bytes(b"merhaba")
        with self.assertRaisesRegex(VoiceError, "zip"):
            library.inspect(self.src / "zip_degil.zip")

    def test_replace_existing_and_delete(self):
        library.import_voice(zip_folder(make_voice(self.src / "v1", "ses", version="1.0.0"), self.src / "1.zip"))
        pkg2 = zip_folder(make_voice(self.src / "v2", "ses", version="1.1.0"), self.src / "2.zip")
        preview = library.inspect(pkg2)
        self.assertEqual(preview.existing.version, "1.0.0")
        voice = library.import_voice(pkg2)
        self.assertEqual(voice.version, "1.1.0")
        self.assertEqual(json.loads((self.voices / "ses" / "voice.json").read_text())["version"], "1.1.0")
        library.delete_voice("ses")
        self.assertEqual(self.installed(), [])
        self.assertEqual([p.name for p in self.voices.iterdir()], [])
        with self.assertRaises(VoiceError):
            library.delete_voice("ses")

    def test_hidden_work_folders_are_not_listed(self):
        (self.voices / library.STAGING / "yarim").mkdir(parents=True)
        self.assertEqual(scan_voices(self.voices), [])


if __name__ == "__main__":
    unittest.main()
