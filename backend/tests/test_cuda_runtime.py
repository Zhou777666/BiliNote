import importlib.util
import os
from pathlib import Path
import sys
import types

import pytest


@pytest.fixture
def runtime():
    spec = importlib.util.spec_from_file_location('isolated_cuda', Path(__file__).resolve().parents[1] / 'app/utils/cuda_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_backend(monkeypatch, count=1):
    monkeypatch.setitem(sys.modules, 'ctranslate2', types.SimpleNamespace(
        get_cuda_device_count=lambda: count,
        get_supported_compute_types=lambda device: {'float16', 'int8_float16'}))


def test_detects_actual_engine_without_torch(runtime, monkeypatch):
    fake_backend(monkeypatch)
    monkeypatch.setitem(sys.modules, 'torch', None)
    monkeypatch.setattr(runtime, 'prepare_cuda_runtime', lambda: [])
    monkeypatch.setattr(runtime, '_driver_info', lambda: {})
    monkeypatch.setattr(runtime, '_check_windows_libraries', lambda dirs: None)
    assert runtime.get_cuda_status(force=True)['available']


def test_missing_device_has_reason(runtime, monkeypatch):
    fake_backend(monkeypatch, count=0)
    monkeypatch.setattr(runtime, 'prepare_cuda_runtime', lambda: [])
    status = runtime.get_cuda_status(force=True)
    assert not status['available'] and 'NVIDIA' in status['reason']


def test_missing_windows_library_is_not_reported_available(runtime, monkeypatch):
    fake_backend(monkeypatch)
    monkeypatch.setattr(runtime.sys, 'platform', 'win32')
    monkeypatch.setattr(runtime, 'prepare_cuda_runtime', lambda: [])
    monkeypatch.setattr(runtime, '_driver_info', lambda: {})
    def missing(name):
        raise OSError('DLL missing')
    monkeypatch.setattr(runtime.ctypes, 'WinDLL', missing, raising=False)
    status = runtime.get_cuda_status(force=True)
    assert not status['available'] and 'cublasLt64_12.dll' in status['reason']


def test_repeated_windows_setup_does_not_grow_path(runtime, monkeypatch, tmp_path):
    directory = tmp_path / 'CUDA 库 with spaces'
    directory.mkdir()
    monkeypatch.setattr(runtime.sys, 'platform', 'win32')
    monkeypatch.setattr(runtime, 'cuda_library_dirs', lambda: [directory])
    registered = []
    monkeypatch.setattr(runtime.os, 'add_dll_directory', lambda path: registered.append(path), raising=False)
    monkeypatch.setenv('PATH', 'original-path')
    runtime.prepare_cuda_runtime()
    expected = os.environ['PATH']
    for _ in range(300):
        runtime.prepare_cuda_runtime()
    assert os.environ['PATH'] == expected
    assert registered == [str(directory)]


def test_status_cache_avoids_repeated_driver_checks(runtime, monkeypatch):
    fake_backend(monkeypatch)
    calls = []
    monkeypatch.setattr(runtime, 'prepare_cuda_runtime', lambda: calls.append(1) or [])
    monkeypatch.setattr(runtime, '_driver_info', lambda: {})
    monkeypatch.setattr(runtime, '_check_windows_libraries', lambda dirs: None)
    for _ in range(300):
        assert runtime.get_cuda_status()['available']
    assert len(calls) == 1
