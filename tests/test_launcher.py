"""Başlatıcının kurulum mantığı (launcher/kurulum.py, D54). İnternet gerektirmez: file:// adresleri."""

import hashlib
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "launcher"))
import kurulum as k  # noqa: E402


def item(path: Path, name="paket", version="1.0", url=True) -> dict:
    data = path.read_bytes()
    return {"name": name, "version": version, "file": path.name, "url": path.as_uri() if url else "",
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.src = self.tmp / "kaynak"
        self.src.mkdir()
        self.y = k.Yerlesim(self.tmp / "Wichelberg")
        self.y.app.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def blob(self, name: str, size: int = 300_000) -> Path:
        path = self.src / name
        path.write_bytes(bytes(range(256)) * (size // 256))
        return path

    def test_download_verifies_sha256(self):
        d = k.Dosya.from_dict(item(self.blob("a.whl")))
        seen = []
        k.indir(d, self.y.downloads / d.file, seen.append, threading.Event())
        self.assertEqual((self.y.downloads / d.file).stat().st_size, d.size)
        self.assertEqual(seen[-1], d.size)
        bad = k.Dosya.from_dict({**item(self.blob("b.whl")), "sha256": "0" * 64})
        with self.assertRaisesRegex(k.KurulumHatasi, "bozuk"):
            k.indir(bad, self.y.downloads / bad.file, lambda n: None, threading.Event())
        self.assertFalse((self.y.downloads / bad.file).exists())
        self.assertFalse((self.y.downloads / (bad.file + ".part")).exists())

    def test_unreachable_url_gives_turkish_error(self):
        d = k.Dosya.from_dict({**item(self.blob("c.whl")), "url": (self.src / "yok.whl").as_uri()})
        with self.assertRaisesRegex(k.KurulumHatasi, "indirilemedi"):
            k.indir(d, self.y.downloads / d.file, lambda n: None, threading.Event(), deneme=1)

    def test_cancel(self):
        d = k.Dosya.from_dict(item(self.blob("d.whl", 3 << 20)))
        stop = threading.Event()
        stop.set()
        with self.assertRaises(k.Iptal):
            k.indir(d, self.y.downloads / d.file, lambda n: None, stop)

    def manifest(self, paketler, modeller=()):
        return {"surum": "1.0.0", "python": {"version": "3.11.17", **{x: v for x, v in item(
            self.blob("python.tar.gz")).items() if x not in ("name", "version")}},
            "paketler": list(paketler), "modeller": list(modeller),
            "uygulama_dosyalari": ["voicechanger/__init__.pyc", "voicechanger/gui/app.pyc"]}

    def test_plan(self):
        p1, p2 = item(self.blob("numpy.whl"), "numpy", "2.0"), item(self.blob("scipy.whl"), "scipy", "1.0")
        model = item(self.blob("contentvec.onnx"), "contentvec", "", url=False)
        m = self.manifest([p1, p2], [model])
        plan = k.plan_cikar(self.y, m, {})
        self.assertTrue(plan.python and plan.venv and plan.gerekli)
        self.assertEqual(len(plan.paketler), 2)
        self.assertEqual([x.file for x in plan.adressiz_modeller], ["contentvec.onnx"])
        self.assertEqual(plan.modeller, [])
        # kurulu hâl: Python + ortam + paketler; model adresi yoksa programın açılmasını engellemez
        self.y.python.parent.mkdir(parents=True)
        self.y.python.write_bytes(b"x")
        self.y.venv_python.parent.mkdir(parents=True)
        self.y.venv_python.write_bytes(b"x")
        state = {"python": "3.11.17", "paketler": ["numpy==2.0", "scipy==1.0"]}
        self.assertFalse(k.plan_cikar(self.y, m, state).gerekli)
        # güncelleme: sadece değişen paket
        m2 = self.manifest([p1, {**p2, "version": "1.1"}], [model])
        self.assertEqual([x.key for x in k.plan_cikar(self.y, m2, state).paketler], ["scipy==1.1"])
        # yeni Python sürümü: her şey baştan
        self.assertTrue(k.plan_cikar(self.y, m, {**state, "python": "3.11.9"}).venv)
        # model adresi gelince indirilecekler listesine girer; dosya tamamsa girmez
        with_url = self.manifest([p1, p2], [item(self.src / "contentvec.onnx", "contentvec", "")])
        self.assertEqual(len(k.plan_cikar(self.y, with_url, state).modeller), 1)
        self.y.models.mkdir(parents=True)
        (self.y.models / "contentvec.onnx").write_bytes((self.src / "contentvec.onnx").read_bytes())
        self.assertFalse(k.plan_cikar(self.y, with_url, state).gerekli)

    def test_stale_app_files_removed(self):
        vc = self.y.app / "voicechanger"
        (vc / "gui").mkdir(parents=True)
        for rel in ("__init__.pyc", "gui/app.pyc", "gui/eski.pyc", "eski_modul.py"):
            (vc / rel).write_bytes(b"x")
        (vc / "notlar.txt").write_text("dokunma")
        removed = k.eski_dosyalari_temizle(self.y, self.manifest([]))
        self.assertEqual(sorted(removed), ["voicechanger/eski_modul.py", "voicechanger/gui/eski.pyc"])
        self.assertTrue((vc / "gui" / "app.pyc").exists())
        self.assertTrue((vc / "notlar.txt").exists())

    def test_long_path_detected(self):
        self.assertFalse(k.yol_cok_uzun(k.Yerlesim(Path(r"C:\Users\Kullanici Adi\OneDrive\Masaüstü\Wichelberg"))))
        self.assertTrue(k.yol_cok_uzun(k.Yerlesim(Path("C:/" + "uzun_klasor_adi/" * 8 + "Wichelberg"))))

    def test_moved_folder_fixes_venv_home(self):
        self.y.python.parent.mkdir(parents=True)
        self.y.python.write_bytes(b"x")
        self.y.venv.mkdir()
        cfg = self.y.venv / "pyvenv.cfg"
        cfg.write_text("home = D:\\eski\\yer\\python\ninclude-system-site-packages = false\n")
        k.venv_yolunu_duzelt(self.y)
        text = cfg.read_text()
        self.assertIn(f"home = {self.y.python_dir}", text)
        self.assertIn("include-system-site-packages = false", text)

    def test_state_roundtrip(self):
        self.assertEqual(k.durum_oku(self.y), {})
        k.durum_yaz(self.y, {"python": "3.11.17"})
        self.assertEqual(json.loads(self.y.state.read_text())["python"], "3.11.17")


if __name__ == "__main__":
    unittest.main()
