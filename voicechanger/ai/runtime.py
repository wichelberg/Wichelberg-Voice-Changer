"""ONNX Runtime oturumları. Execution provider seçimi SADECE burada yapılır (docs/DECISIONS.md D9).

- Varsayılan: CPUExecutionProvider.
- İsteğe bağlı: DirectML ("GPU hızlandırma (deneysel)"). Hata veya zaman aşımında bütün modeller sessizce
  CPU'ya döner; sebep `Runtime.fallback_reason` ile arayüze verilir.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import onnxruntime as ort

CPU = "cpu"
GPU = "gpu"
_PROVIDER = {CPU: "CPUExecutionProvider", GPU: "DmlExecutionProvider"}

ort.set_default_logger_severity(3)  # sadece hatalar


@dataclass
class RuntimeConfig:
    accel: str = CPU            # "cpu" | "gpu" (DirectML, deneysel)
    cpu_threads: int = 0        # 0: fiziksel çekirdek sayısına göre otomatik
    gpu_device_id: int | None = None  # None: en çok VRAM'li gerçek GPU

    @classmethod
    def from_dict(cls, data: dict | None) -> "RuntimeConfig":
        data = data or {}
        accel = data.get("accel", CPU)
        return cls(accel=accel if accel in (CPU, GPU) else CPU,
                   cpu_threads=int(data.get("cpu_threads", 0) or 0),
                   gpu_device_id=data.get("gpu_device_id"))

    def to_dict(self) -> dict:
        return {"accel": self.accel, "cpu_threads": self.cpu_threads, "gpu_device_id": self.gpu_device_id}


# ----------------------------------------------------------------------------- donanım bilgisi
def gpu_supported() -> bool:
    """onnxruntime-directml kurulu mu (Windows 10 1903+ ve DirectX 12 GPU gerekir)."""
    return _PROVIDER[GPU] in ort.get_available_providers()


@dataclass
class GpuInfo:
    device_id: int        # DirectML device_id = DXGI adaptör sırası
    name: str
    vram_mb: int


def list_gpus() -> list[GpuInfo]:
    """DXGI ile ekran kartlarını listeler (yazılım adaptörü hariç). Hata olursa boş liste."""
    try:
        return _dxgi_adapters()
    except Exception:
        return []


def default_gpu() -> GpuInfo | None:
    gpus = list_gpus()
    return max(gpus, key=lambda g: g.vram_mb) if gpus else None


def cpu_name() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except Exception:
        import platform
        return platform.processor() or "bilinmeyen CPU"


def physical_cores() -> int:
    try:
        import psutil
        return psutil.cpu_count(logical=False) or os.cpu_count() or 1
    except Exception:
        return os.cpu_count() or 1


# ----------------------------------------------------------------------------- runtime
class Runtime:
    """Bir motorun bütün ONNX oturumlarının ortak sağlayıcı durumu.

    GPU bir kez başarısız olursa (açılamama, çalışma hatası, zaman aşımı) bütün oturumlar CPU'ya geçer ve
    bu oturum boyunca CPU'da kalır.
    """

    def __init__(self, config: RuntimeConfig | None = None, gpu_block_reason: str | None = None):
        self.config = config or RuntimeConfig()
        self.fallback_reason: str | None = None
        self._lock = threading.Lock()
        self._sessions: list[ModelSession] = []
        if self.config.accel == GPU:
            if not gpu_supported():
                self.fallback_reason = "DirectML bu kurulumda yok"
            elif gpu_block_reason:
                self.fallback_reason = gpu_block_reason

    @classmethod
    def from_settings(cls, ai_config: dict | None) -> "Runtime":
        """config.json'daki "ai" bölümünden. Hız testinde CPU ile eşitlik testini geçemeyen GPU kullanılmaz."""
        ai_config = ai_config or {}
        cfg = RuntimeConfig.from_dict(ai_config.get("runtime"))
        reason = None
        if cfg.accel == GPU:
            device = cfg.gpu_device_id
            if device is None:
                gpu = default_gpu()
                device = gpu.device_id if gpu else 0
            for item in (ai_config.get("benchmark") or {}).get("gpus", []):
                if item.get("device_id") == device and item.get("parity_ok") is False:
                    reason = "bu GPU'nun sonucu CPU'dan farklı (eşitlik testi başarısız)"
        return cls(cfg, reason)

    @property
    def provider(self) -> str:
        """Şu an kullanılması gereken sağlayıcı: "cpu" veya "gpu"."""
        if self.config.accel == GPU and self.fallback_reason is None:
            return GPU
        return CPU

    def describe(self) -> str:
        if self.provider == GPU:
            gpu = self._gpu()
            return f"GPU (DirectML{': ' + gpu.name if gpu else ''})"
        text = f"CPU ({self.threads()} iş parçacığı)"
        if self.config.accel == GPU:
            text += f" — GPU devre dışı: {self.fallback_reason}"
        return text

    def threads(self) -> int:
        return self.config.cpu_threads or max(1, physical_cores())

    def session(self, path: Path | str, gpu_dims: dict[str, int] | None = None) -> "ModelSession":
        """gpu_dims: GPU'da girdi boyutlarını sabitle. DirectML sadece sabit boyutta hızlı (bir oturum = bir
        parça boyutu); boyut verilmezse ilk çalıştırmanın boyutu hızlı, diğerleri ~6 kat yavaş olur."""
        sess = ModelSession(self, Path(path), gpu_dims)
        with self._lock:
            self._sessions.append(sess)
        return sess

    def release(self, sess: "ModelSession") -> None:
        with self._lock:
            if sess in self._sessions:
                self._sessions.remove(sess)

    def fall_back(self, reason: str) -> None:
        """GPU'yu bırak; her oturum bir sonraki çağrıda CPU'da yeniden açılır."""
        with self._lock:
            if self.fallback_reason is None:
                self.fallback_reason = reason

    # -- oturum seçenekleri
    def _gpu(self) -> GpuInfo | None:
        if self.config.gpu_device_id is not None:
            for gpu in list_gpus():
                if gpu.device_id == self.config.gpu_device_id:
                    return gpu
            return GpuInfo(self.config.gpu_device_id, f"GPU {self.config.gpu_device_id}", 0)
        return default_gpu()

    def _create(self, path: Path, provider: str, gpu_dims: dict[str, int] | None = None) -> ort.InferenceSession:
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        if provider == GPU:
            so.enable_mem_pattern = False  # DirectML şartı
            for name, value in (gpu_dims or {}).items():
                so.add_free_dimension_override_by_name(name, int(value))
            gpu = self._gpu()
            options = {"device_id": gpu.device_id if gpu else 0}
            return ort.InferenceSession(str(path), so, providers=[(_PROVIDER[GPU], options)])
        so.intra_op_num_threads = self.threads()
        # Bekleyen iş parçacıkları boşta dönmesin: oyunla aynı anda CPU'yu boşuna yakmayalım.
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        return ort.InferenceSession(str(path), so, providers=[_PROVIDER[CPU]])


class ModelSession:
    """Tek bir ONNX modeli. Sağlayıcı değişirse kendini yeniden açar."""

    def __init__(self, runtime: Runtime, path: Path, gpu_dims: dict[str, int] | None = None):
        self.runtime = runtime
        self.path = path
        self.gpu_dims = gpu_dims
        self._session: ort.InferenceSession | None = None
        self._provider: str | None = None
        self._open()

    @property
    def provider(self) -> str | None:
        return self._provider

    @property
    def fixed_shape(self) -> bool:
        return self._provider == GPU and bool(self.gpu_dims)

    @property
    def input_names(self) -> list[str]:
        return [i.name for i in self._session.get_inputs()]

    def metadata(self) -> dict[str, str]:
        """training/export_onnx.py'nin yazdığı bilgiler (sample_rate, upp, ...)."""
        return dict(self._session.get_modelmeta().custom_metadata_map)

    def _open(self) -> None:
        wanted = self.runtime.provider
        if wanted == GPU:
            try:
                self._session = self.runtime._create(self.path, GPU, self.gpu_dims)
                self._provider = GPU
                return
            except Exception as exc:  # sürücü/GPU sorunu → CPU
                self.runtime.fall_back(f"GPU'da açılamadı ({_short(exc)})")
        self._session = self.runtime._create(self.path, CPU)
        self._provider = CPU

    def run(self, feeds: dict[str, np.ndarray], timeout_s: float | None = None) -> list[np.ndarray]:
        """Modeli çalıştır. GPU'da hata/zaman aşımı olursa CPU'ya geçip aynı girdiyle tekrar dener."""
        if self._provider != self.runtime.provider:
            self._open()
        if self._provider == CPU:
            return self._session.run(None, feeds)
        options = ort.RunOptions()
        timer = None
        if timeout_s:
            timer = threading.Timer(timeout_s, lambda: setattr(options, "terminate", True))
            timer.daemon = True
            timer.start()
        started = time.perf_counter()
        try:
            return self._session.run(None, feeds, options)
        except Exception as exc:
            if timeout_s and time.perf_counter() - started >= timeout_s:
                reason = f"zaman aşımı (> {timeout_s * 1000:.0f} ms)"
            else:
                reason = f"çalışma hatası ({_short(exc)})"
            self.runtime.fall_back(reason)
            self._open()
            return self._session.run(None, feeds)
        finally:
            if timer is not None:
                timer.cancel()

    def close(self) -> None:
        self.runtime.release(self)
        self._session = None


def _short(exc: Exception) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:120]


# ----------------------------------------------------------------------------- DXGI (ctypes, ek paket yok)
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


class _AdapterDesc1(ctypes.Structure):
    _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", ctypes.c_uint), ("DeviceId", ctypes.c_uint),
                ("SubSysId", ctypes.c_uint), ("Revision", ctypes.c_uint),
                ("DedicatedVideoMemory", ctypes.c_size_t), ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t), ("LuidLow", ctypes.c_uint32),
                ("LuidHigh", ctypes.c_int32), ("Flags", ctypes.c_uint)]


def _com_method(obj: ctypes.c_void_p, index: int, *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])


def _dxgi_adapters() -> list[GpuInfo]:
    iid = _GUID(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
    factory = ctypes.c_void_p()
    if ctypes.windll.dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
        return []
    found: list[GpuInfo] = []
    try:
        enum_adapters1 = _com_method(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            if enum_adapters1(factory, index, ctypes.byref(adapter)) != 0:
                break  # DXGI_ERROR_NOT_FOUND: liste bitti
            desc = _AdapterDesc1()
            _com_method(adapter, 10, ctypes.POINTER(_AdapterDesc1))(adapter, ctypes.byref(desc))
            _com_method(adapter, 2)(adapter)  # Release
            if not desc.Flags & 2:  # DXGI_ADAPTER_FLAG_SOFTWARE
                found.append(GpuInfo(index, desc.Description.strip(), int(desc.DedicatedVideoMemory // 2**20)))
            index += 1
    finally:
        _com_method(factory, 2)(factory)
    return found
