import importlib.util
import logging
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest


@pytest.fixture
def helper(monkeypatch):
    logger = types.ModuleType("app.utils.logger")
    logger.get_logger = lambda name: logging.getLogger(name)
    monkeypatch.setitem(sys.modules, "app.utils.logger", logger)
    source = Path(__file__).resolve().parents[1] / "ffmpeg_helper.py"
    spec = importlib.util.spec_from_file_location("isolated_media_tools", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("FFMPEG_BIN_PATH", raising=False)
    return module


@pytest.fixture
def tools(tmp_path):
    directory = tmp_path / "媒体 tools"
    directory.mkdir()
    for tool in ("ffmpeg", "ffprobe"):
        (directory / (tool + (".exe" if os.name == "nt" else ""))).touch()
    return directory


def test_repeated_checks_do_not_grow_path(helper, tools, monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN_PATH", str(tools))
    original = os.environ["PATH"]
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b"media version 1\n", b"")

    monkeypatch.setattr(helper.subprocess, "run", run)
    for _ in range(300):
        assert helper.get_media_tools_status(force=True)["available"]
        assert os.environ["PATH"] == original
    assert len(calls) == 600
    assert all(Path(command[0]).is_absolute() for command in calls)


def test_health_cache_avoids_spawning_on_every_poll(helper, tools, monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN_PATH", str(tools))
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b"version 1", b"")
    monkeypatch.setattr(helper.subprocess, "run", run)
    for _ in range(300):
        assert helper.check_ffmpeg_exists()
    assert len(calls) == 2
    monkeypatch.setattr(helper.time, "monotonic", lambda: helper._status_cache[1] + 31)
    assert helper.check_ffmpeg_exists()
    assert len(calls) == 4


def test_bundled_tools_work_without_path(helper, tools, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(helper, "_bundled_dirs", lambda: [tools])
    assert Path(helper.resolve_media_tool()).parent == tools
    override = tmp_path / "override"
    override.mkdir()
    (override / Path(helper.resolve_media_tool()).name).touch()
    monkeypatch.setenv("FFMPEG_BIN_PATH", str(override))
    assert Path(helper.resolve_media_tool()).parent == override


def test_invalid_override_is_actionable_not_silently_ignored(helper, monkeypatch, tmp_path):
    monkeypatch.setenv("FFMPEG_BIN_PATH", str(tmp_path / "missing"))
    with pytest.raises(helper.MediaToolError, match="FFMPEG_BIN_PATH"):
        helper.resolve_media_tool()


def test_probe_is_required_and_missing_tool_is_distinct(helper, tools, monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN_PATH", str(tools))
    (tools / ("ffprobe.exe" if os.name == "nt" else "ffprobe")).unlink()
    monkeypatch.setattr(helper.subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(command, 0, b"version 1", b""))
    status = helper.get_media_tools_status()
    assert not status["available"]
    assert status["status"] == "missing"
    assert "ffprobe" in status["error"]


@pytest.mark.parametrize("failure, expected", [
    (OSError("access denied"), "无法启动"),
    (subprocess.TimeoutExpired("ffmpeg", 5), "超时"),
    (subprocess.CompletedProcess([], 17, b"", b"invalid input file"), "invalid input file"),
])
def test_errors_retain_the_actual_reason(helper, tools, monkeypatch, failure, expected):
    monkeypatch.setenv("FFMPEG_BIN_PATH", str(tools))
    def run(*args, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure
    monkeypatch.setattr(helper.subprocess, "run", run)
    with pytest.raises(helper.MediaToolError, match=expected):
        helper.run_ffmpeg(["-i", "missing.mp4", "out.mp3"])
    status = helper.get_media_tools_status()
    assert status["status"] == "error"
    assert expected in status["error"]


def test_yt_dlp_uses_resolved_directory_but_metadata_needs_no_tools(helper, tools, monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN_PATH", str(tools))
    original = {"format": "bestaudio"}
    assert helper.with_ffmpeg_location(original)["ffmpeg_location"] == str(tools.resolve())
    assert "ffmpeg_location" not in original
    monkeypatch.setenv("FFMPEG_BIN_PATH", "missing-folder")
    assert helper.with_ffmpeg_location({"skip_download": True}) == {"skip_download": True}


def test_frozen_layout_resolves_internal_tools(helper, monkeypatch, tmp_path):
    monkeypatch.setattr(helper.sys, "frozen", True, raising=False)
    monkeypatch.setattr(helper.sys, "executable", str(tmp_path / "BiliNoteBackend.exe"))
    monkeypatch.setattr(helper.sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    bundled = tmp_path / "_internal" / "tools" / "ffmpeg"
    bundled.mkdir(parents=True)
    tool = bundled / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    tool.touch()
    monkeypatch.setenv("PATH", "")
    assert helper.resolve_media_tool() == str(tool.resolve())
