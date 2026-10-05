"""Global kısayol (oyun penceresi öndeyken de çalışır).

pynput, Windows'un düşük seviyeli klavye kancasını kullanır; tuşları
engellemez, sadece dinler. Oyun yönetici olarak çalışıyorsa bu programın
da yönetici olarak açılması gerekebilir.

Kısayol yazımı: "ctrl+f7", "alt+shift+v", "ctrl+alt+9"
"""

from pynput import keyboard


def to_pynput(spec: str) -> str:
    """'ctrl+f7' → '<ctrl>+<f7>'"""
    tokens = [t.strip().lower() for t in spec.split("+") if t.strip()]
    return "+".join(t if len(t) == 1 else f"<{t}>" for t in tokens)


def is_valid(spec: str) -> bool:
    try:
        keys = keyboard.HotKey.parse(to_pynput(spec))
    except (ValueError, KeyError):
        return False
    return len(keys) > 0


class GlobalHotkey:
    def __init__(self):
        self._listener: keyboard.GlobalHotKeys | None = None

    def set(self, spec: str, callback) -> None:
        """callback pynput iş parçacığında çağrılır; kısa ve iş parçacığı güvenli olmalı."""
        self.stop()
        self._listener = keyboard.GlobalHotKeys({to_pynput(spec): callback})
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
