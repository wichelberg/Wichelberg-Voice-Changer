"""GPU kullanımı ve VRAM (Windows performans sayaçları, PDH; her marka GPU için, ek paket yok).

Görev Yöneticisi ile aynı kaynak: "GPU Engine" ve "GPU Process Memory" sayaçları.
Kullanım:
    stats = GpuStats(); stats.sample()   # iki örnek arası en az ~0.5 sn olmalı
    s = stats.sample(); s.total_util_pct, s.process_util_pct, s.process_vram_mb
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

_PDH_FMT_DOUBLE = 0x00000200
_PDH_MORE_DATA = 0x800007D2


class _FmtValue(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _Item(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _FmtValue)]


@dataclass
class GpuSample:
    total_util_pct: float          # tüm süreçler, en yoğun motor türü (Görev Yöneticisi'ndeki "GPU" gibi)
    process_util_pct: float        # bu süreç
    process_vram_mb: float         # bu sürecin ayırdığı özel (dedicated) VRAM
    total_vram_mb: float           # ekran kartındaki toplam kullanılan özel VRAM


class GpuStats:
    def __init__(self, pid: int | None = None):
        self.pid = pid or os.getpid()
        self._pdh = ctypes.WinDLL("pdh.dll")
        for fn in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData", "PdhGetFormattedCounterArrayW",
                   "PdhCloseQuery"):
            getattr(self._pdh, fn).restype = wintypes.DWORD  # PDH durum kodları işaretsiz (0x800007D2 ...)
        self._query = wintypes.HANDLE()
        if self._pdh.PdhOpenQueryW(None, None, ctypes.byref(self._query)) != 0:
            raise OSError("PDH sorgusu açılamadı")
        self._engine = self._add(r"\GPU Engine(*)\Utilization Percentage")
        self._proc_mem = self._add(r"\GPU Process Memory(*)\Dedicated Usage")
        self._adapter_mem = self._add(r"\GPU Adapter Memory(*)\Dedicated Usage")
        self._pdh.PdhCollectQueryData(self._query)

    def _add(self, path: str) -> wintypes.HANDLE:
        counter = wintypes.HANDLE()
        if self._pdh.PdhAddEnglishCounterW(self._query, path, None, ctypes.byref(counter)) != 0:
            raise OSError(f"PDH sayacı yok: {path}")
        return counter

    def _values(self, counter) -> list[tuple[str, float]]:
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        status = self._pdh.PdhGetFormattedCounterArrayW(counter, _PDH_FMT_DOUBLE, ctypes.byref(size),
                                                        ctypes.byref(count), None)
        if status != _PDH_MORE_DATA or size.value == 0:
            return []
        buffer = (ctypes.c_byte * size.value)()
        status = self._pdh.PdhGetFormattedCounterArrayW(counter, _PDH_FMT_DOUBLE, ctypes.byref(size),
                                                        ctypes.byref(count), buffer)
        if status != 0:
            return []
        items = ctypes.cast(buffer, ctypes.POINTER(_Item))
        return [(items[i].szName, items[i].FmtValue.doubleValue) for i in range(count.value)
                if items[i].FmtValue.CStatus in (0, 1)]

    def sample(self) -> GpuSample:
        self._pdh.PdhCollectQueryData(self._query)
        tag = f"pid_{self.pid}_"
        total: dict[str, float] = {}
        mine: dict[str, float] = {}
        for name, value in self._values(self._engine):
            # örnek: pid_1234_luid_0x0000_0x0001_phys_0_eng_0_engtype_3D
            engtype = name.rsplit("engtype_", 1)[-1]
            luid = name.split("_phys_")[0].split("luid_")[-1]
            key = f"{luid}/{engtype}"
            total[key] = total.get(key, 0.0) + value
            if name.startswith(tag):
                mine[key] = mine.get(key, 0.0) + value
        proc_mem = sum(v for n, v in self._values(self._proc_mem) if n.startswith(tag))
        adapter_mem = max((v for _, v in self._values(self._adapter_mem)), default=0.0)
        return GpuSample(total_util_pct=min(100.0, max(total.values(), default=0.0)),
                         process_util_pct=min(100.0, max(mine.values(), default=0.0)),
                         process_vram_mb=proc_mem / 2**20, total_vram_mb=adapter_mem / 2**20)

    def close(self) -> None:
        self._pdh.PdhCloseQuery(self._query)
