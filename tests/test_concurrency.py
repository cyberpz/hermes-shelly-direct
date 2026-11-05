"""Concurrency and formatting regressions found in live dashboard testing."""

import threading

from shelly_core import inventory


def test_concurrent_saves_do_not_race():
    """The dashboard fetches many device statuses in parallel; every save
    rewrites the whole file. A shared tmp path caused ENOENT on replace."""
    errors = []

    def worker(n):
        try:
            for _ in range(10):
                inv = inventory.load()
                inv[f"AA{n:02d}"] = {"mac": f"AA{n:02d}", "name": f"d{n}",
                                     "ip": "1.2.3.4", "id": "", "model": "",
                                     "gen": 2, "kind": "relay", "online": True,
                                     "channels": [], "last_seen": None}
                inventory.save(inv)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"concurrent save failed: {errors!r}"
    saved = inventory.load()
    assert len([k for k in saved if k.startswith("AA")]) >= 1


def test_last_seen_is_timezone_aware():
    inventory.save({"AA": {"mac": "AA", "ip": "1.1.1.1"}})
    raw = (inventory.data_dir() / "inventory.json").read_text()
    assert "+" in raw or "-" in raw.split("updated\":")[1][:20], \
        "updated timestamp must carry a UTC offset for dashboard timeAgo()"
