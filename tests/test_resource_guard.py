"""core/resource_guard.py 단위 테스트.

실제 os.getloadavg()/os.cpu_count()/실제 /proc/meminfo에 의존하지 않도록 monkeypatch 한다.
"""

from core import resource_guard


def test_available_memory_mb_parses_meminfo(monkeypatch, tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       12206000 kB\nMemFree:         3459000 kB\n"
                       "MemAvailable:   11365000 kB\n")
    monkeypatch.setattr(resource_guard, "open", lambda *a, **k: meminfo.open(), raising=False)
    assert resource_guard.available_memory_mb() == 11365000 / 1024


def test_available_memory_mb_returns_none_when_unreadable(monkeypatch):
    def _raise(*a, **k):
        raise OSError("no such file")
    monkeypatch.setattr(resource_guard, "open", _raise, raising=False)
    assert resource_guard.available_memory_mb() is None


def test_has_headroom_true_under_normal_conditions(monkeypatch):
    monkeypatch.setattr(resource_guard.os, "getloadavg", lambda: (0.2, 0.1, 0.05))
    monkeypatch.setattr(resource_guard.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(resource_guard, "available_memory_mb", lambda: 8000)
    assert resource_guard.has_headroom() is True


def test_has_headroom_false_when_load_exceeds_threshold(monkeypatch):
    monkeypatch.setattr(resource_guard.os, "getloadavg", lambda: (5.0, 5.0, 5.0))
    monkeypatch.setattr(resource_guard.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(resource_guard, "available_memory_mb", lambda: 8000)
    # threshold = 2 cpus * 1.5 = 3.0, load 5.0 exceeds it
    assert resource_guard.has_headroom() is False


def test_has_headroom_false_when_memory_below_threshold(monkeypatch):
    monkeypatch.setattr(resource_guard.os, "getloadavg", lambda: (0.1, 0.1, 0.1))
    monkeypatch.setattr(resource_guard.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(resource_guard, "available_memory_mb", lambda: 500)
    assert resource_guard.has_headroom(min_free_memory_mb=1024) is False


def test_has_headroom_respects_custom_thresholds(monkeypatch):
    monkeypatch.setattr(resource_guard.os, "getloadavg", lambda: (3.0, 3.0, 3.0))
    monkeypatch.setattr(resource_guard.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(resource_guard, "available_memory_mb", lambda: 8000)
    assert resource_guard.has_headroom(max_load_per_cpu=1.0) is False
    assert resource_guard.has_headroom(max_load_per_cpu=2.0) is True


def test_has_headroom_unknown_memory_does_not_block(monkeypatch):
    monkeypatch.setattr(resource_guard.os, "getloadavg", lambda: (0.1, 0.1, 0.1))
    monkeypatch.setattr(resource_guard.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(resource_guard, "available_memory_mb", lambda: None)
    assert resource_guard.has_headroom() is True
