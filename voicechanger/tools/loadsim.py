"""Oyun benzeri CPU yükü (hız testi için): ayrı süreçler 60 FPS kare temposunda sabit miktarda iş yapar.

Sabit iş: CPU başkası tarafından alınırsa kare uzar ve "oyun" FPS'i düşer; böylece hem bizim gecikmemiz hem
oyuna etkimiz ölçülür. Gerçek oyunun yerini tutmaz; karşılaştırılabilir bir yük verir.
"""

from __future__ import annotations

import multiprocessing as mp
import time

FRAME_S = 1 / 60
WORK_PER_FRAME = 250000      # bu makinede (Ryzen AI 7 350) ~12 ms ≈ karenin %75'i


def _game_thread(work: int, stop, frames) -> None:
    while not stop.is_set():
        start = time.perf_counter()
        acc = 0
        for i in range(work):
            acc += i * i
        rest = FRAME_S - (time.perf_counter() - start)
        if rest > 0:
            time.sleep(rest)
        frames.value += 1


class GameLoad:
    """with GameLoad(n) as load: load.mark(); ...; load.fps()"""

    def __init__(self, processes: int, work: int = WORK_PER_FRAME):
        self._stop = mp.Event()
        self._frames = [mp.Value("l", 0, lock=False) for _ in range(processes)]
        self._procs = [mp.Process(target=_game_thread, args=(work, self._stop, f), daemon=True) for f in self._frames]
        self._mark = (0.0, 0)

    def __enter__(self) -> "GameLoad":
        for proc in self._procs:
            proc.start()
        time.sleep(1.0)
        self.mark()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        for proc in self._procs:
            proc.join(5)

    def mark(self) -> None:
        self._mark = (time.perf_counter(), sum(f.value for f in self._frames))

    def fps(self) -> float:
        if not self._frames:
            return 0.0
        elapsed = time.perf_counter() - self._mark[0]
        return (sum(f.value for f in self._frames) - self._mark[1]) / len(self._frames) / max(elapsed, 1e-6)
