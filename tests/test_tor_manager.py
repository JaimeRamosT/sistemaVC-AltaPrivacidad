import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

pytest.importorskip("PySide6")

from app.tor.tor_manager import TorProcessManager, _BOOTSTRAP_RE


def test_bootstrap_regex_parses_percentage_and_description():
    line = "Jul 02 12:34:56.000 [notice] Bootstrapped 45% (conn): Connecting to a relay"
    match = _BOOTSTRAP_RE.search(line)
    assert match is not None
    assert int(match.group(1)) == 45
    assert match.group(2) == "conn"


def test_bootstrap_regex_matches_100_percent():
    line = "Jul 02 12:35:10.000 [notice] Bootstrapped 100% (done): Done"
    match = _BOOTSTRAP_RE.search(line)
    assert match is not None
    assert int(match.group(1)) == 100


def test_bootstrap_regex_no_match_on_unrelated_line():
    assert _BOOTSTRAP_RE.search("Jul 02 12:00:00.000 [notice] Starting Tor") is None


def test_platform_subdir_is_one_of_expected_values():
    assert TorProcessManager.platform_subdir() in ("windows", "macos", "linux")


def test_vendor_dir_dev_mode_points_under_repo_root(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    vendor_dir = TorProcessManager.vendor_dir()
    assert vendor_dir.parts[-3:] == ("vendor", "tor", TorProcessManager.platform_subdir())


def test_vendor_dir_frozen_mode_points_under_meipass(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    vendor_dir = TorProcessManager.vendor_dir()
    assert str(vendor_dir) == str(tmp_path / "vendor" / "tor" / TorProcessManager.platform_subdir())
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)


def test_find_tor_binary_returns_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert TorProcessManager.find_tor_binary() is None
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)


def test_find_tor_binary_finds_nested_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    exe_name = "tor.exe" if TorProcessManager.platform_subdir() == "windows" else "tor"
    nested = tmp_path / "vendor" / "tor" / TorProcessManager.platform_subdir() / "sub" / exe_name
    nested.parent.mkdir(parents=True)
    nested.write_text("")

    found = TorProcessManager.find_tor_binary()
    assert found is not None
    assert found.name == exe_name

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
