"""CTranslate2 CUDA diagnostics and bounded Windows DLL search setup."""
import ctypes
import importlib.util
import os
from pathlib import Path
import sys
import threading
import time

_dll_handles = []
_loaded_libraries = {}
_registered_dirs = set()
_setup_lock = threading.Lock()
_status_lock = threading.Lock()
_cached_status = None
_cached_at = 0.0


def cuda_library_dirs():
    roots = [Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))]
    if not getattr(sys, "frozen", False):
        spec = importlib.util.find_spec("nvidia")
        if spec and spec.submodule_search_locations:
            roots.extend(Path(path).parent for path in spec.submodule_search_locations)
        spec = importlib.util.find_spec("ctranslate2")
        if spec and spec.origin:
            roots.append(Path(spec.origin).parent.parent)
    directories = []
    for root in roots:
        directories.extend(root / "nvidia" / name / "bin" for name in ("cuda_nvrtc", "cublas", "cudnn"))
        directories.append(root / "ctranslate2")
    for variable in ("CUDA_BIN_PATH", "CUDA_PATH"):
        if os.getenv(variable):
            path = Path(os.path.expandvars(os.environ[variable])).expanduser()
            directories.append(path if variable == "CUDA_BIN_PATH" else path / "bin")
    return list(dict.fromkeys(path.resolve() for path in directories if path.is_dir()))


def prepare_cuda_runtime():
    """Register each directory once, retaining add_dll_directory handles."""
    if sys.platform != "win32":
        return []
    with _setup_lock:
        directories = cuda_library_dirs()
        existing = {os.path.normcase(path) for path in os.environ.get("PATH", "").split(os.pathsep)}
        additions = []
        for directory in directories:
            key = os.path.normcase(str(directory))
            if key not in _registered_dirs:
                _dll_handles.append(os.add_dll_directory(str(directory)))
                _registered_dirs.add(key)
            if key not in existing:
                additions.append(str(directory))
                existing.add(key)
        if additions:
            os.environ["PATH"] = os.pathsep.join(additions + [os.environ.get("PATH", "")])
        return directories


def _check_windows_libraries(directories):
    # Prefer the complete bundled NVIDIA libraries over CTranslate2's cuDNN stub.
    for name in ("cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll"):
        path = next((directory / name for directory in directories if (directory / name).is_file()), name)
        try:
            if str(path) not in _loaded_libraries:
                _loaded_libraries[str(path)] = ctypes.WinDLL(str(path))
        except OSError as exc:
            raise RuntimeError(f"无法加载 {name}：{exc}。请使用包含 CUDA 运行库的 Windows 安装包，或设置 CUDA_BIN_PATH。") from exc


def _driver_info():
    if sys.platform != "win32":
        return {}
    try:
        driver = ctypes.WinDLL("nvcuda.dll")
        if driver.cuInit(0) != 0:
            return {}
        name = ctypes.create_string_buffer(256)
        version = ctypes.c_int()
        driver.cuDeviceGetName(name, len(name), 0)
        driver.cuDriverGetVersion(ctypes.byref(version))
        return {"gpu_name": name.value.decode("utf-8", errors="replace"),
                "driver_cuda_version": f"{version.value // 1000}.{(version.value % 1000) // 10}"}
    except OSError:
        return {}


def get_cuda_status(force=False):
    global _cached_status, _cached_at
    with _status_lock:
        if not force and _cached_status is not None and time.monotonic() - _cached_at < 30:
            return dict(_cached_status)
        status = {"available": False, "backend": "CTranslate2", "version": None,
                  "gpu_name": None, "device_count": 0, "compute_types": [], "reason": None}
        try:
            directories = prepare_cuda_runtime()
            import ctranslate2
            status["device_count"] = ctranslate2.get_cuda_device_count()
            if not status["device_count"]:
                raise RuntimeError("CTranslate2 未检测到 NVIDIA CUDA 设备，请检查显卡及 NVIDIA 驱动。")
            status.update(_driver_info())
            if sys.platform == "win32":
                _check_windows_libraries(directories)
            status["compute_types"] = sorted(ctranslate2.get_supported_compute_types("cuda"))
            if not status["compute_types"]:
                raise RuntimeError("当前 GPU 没有受支持的 CUDA 计算类型。")
            status.update(available=True, version="CUDA 12 / cuDNN 9")
        except Exception as exc:
            status["reason"] = str(exc)
        _cached_status, _cached_at = status, time.monotonic()
        return dict(status)


def is_cuda_error(exc):
    message = str(exc).lower()
    return any(token in message for token in ("cuda", "cublas", "cudnn", "out of memory", "failed to allocate"))
