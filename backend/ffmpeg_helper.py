import os
import subprocess
import sys
import json
from pathlib import Path
import shutil
import threading
import time
from dotenv import load_dotenv

from app.utils.logger import get_logger
logger = get_logger(__name__)


def _load_dotenv_from_multiple_paths():
    """尝试多个位置加载 .env，适配源码运行和 PyInstaller 打包场景。

    PyInstaller 打包后当前工作目录是 EXE 所在目录，而源码运行时 .env
    通常在项目根目录或 backend/ 同级。遍历常见候选路径确保能命中。
    """
    candidates = []
    # 1. 当前工作目录（EXE 所在目录）
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), '.env'))
    candidates.append(os.path.join(os.getcwd(), '.env'))
    # 2. 本脚本所在目录（backend/）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(script_dir, '.env'))
    # 3. 项目根目录（backend/../.env）
    candidates.append(os.path.join(script_dir, '..', '.env'))
    # 4. PyInstaller 打包后的 _internal/ 子目录
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, '_internal', '.env'))

    for path in candidates:
        normalized = os.path.normpath(path)
        if os.path.isfile(normalized):
            load_dotenv(normalized)
            return
    # 都没找到，fallback 到默认行为（从 CWD 找）
    load_dotenv()


_load_dotenv_from_multiple_paths()


class MediaToolError(RuntimeError):
    """Missing tool, startup, timeout, or media conversion failure."""


def _bundled_dirs():
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        roots = [exe_dir, Path(getattr(sys, "_MEIPASS", exe_dir / "_internal"))]
    else:
        roots = [Path(__file__).resolve().parent]
    return [root / "tools" / "ffmpeg" for root in roots]


def resolve_media_tool(tool="ffmpeg") -> str:
    """Explicit config, bundled tools, then PATH; never mutate PATH."""
    if tool not in ("ffmpeg", "ffprobe"):
        raise ValueError(f"Unsupported media tool: {tool}")
    filename = tool + (".exe" if os.name == "nt" else "")
    override = os.getenv("FFMPEG_BIN_PATH", "").strip().strip('"')
    if override:
        directory = Path(os.path.expandvars(override)).expanduser()
        if directory.is_file():
            directory = directory.parent
        candidate = directory / filename
        if candidate.is_file():
            return str(candidate.resolve())
        raise MediaToolError(f"配置的 FFMPEG_BIN_PATH 中找不到 {filename}：{directory}。请修改或清空该配置。")
    for directory in _bundled_dirs():
        candidate = directory / filename
        if candidate.is_file():
            return str(candidate.resolve())
    found = shutil.which(filename)
    if found:
        return str(Path(found).resolve())
    raise MediaToolError(f"找不到 {filename}。请安装完整桌面包，或将 FFMPEG_BIN_PATH 设为包含 ffmpeg 和 ffprobe 的目录。")


def with_ffmpeg_location(options: dict) -> dict:
    options = dict(options)
    if not options.get("skip_download"):
        options["ffmpeg_location"] = str(Path(resolve_media_tool()).parent)
    return options


def _run_tool(tool, arguments, timeout):
    executable = resolve_media_tool(tool)
    try:
        result = subprocess.run(
            [executable, *map(str, arguments)], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaToolError(f"{tool} 超时（{timeout} 秒）：{executable}") from exc
    except OSError as exc:
        raise MediaToolError(f"{tool} 无法启动：{executable}；{exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-3000:]
        error = MediaToolError(f"{tool} 执行失败（退出码 {result.returncode}）：{executable}\n{detail}")
        logger.error("%s", error)
        raise error
    return result


def run_ffmpeg(arguments, timeout=600):
    return _run_tool("ffmpeg", ["-nostdin", *arguments], timeout)


def probe_media(path):
    result = _run_tool("ffprobe", ["-v", "error", "-show_format", "-show_streams", "-of", "json", path], 30)
    return json.loads(result.stdout)


_status_cache = None
_status_lock = threading.Lock()


def get_media_tools_status(force=False) -> dict:
    """Bound version probes and cache for 30 seconds to keep health polls cheap."""
    global _status_cache
    key = (os.getenv("FFMPEG_BIN_PATH"), os.getenv("PATH"), tuple(map(str, _bundled_dirs())))
    with _status_lock:
        now = time.monotonic()
        if not force and _status_cache and _status_cache[0] == key and now - _status_cache[1] < 30:
            return dict(_status_cache[2])
        tools = {}
        for tool in ("ffmpeg", "ffprobe"):
            info = {"available": False, "path": None, "version": None, "error": None, "status": "missing"}
            try:
                info["path"] = resolve_media_tool(tool)
                result = _run_tool(tool, ["-version"], 5)
                lines = result.stdout.decode("utf-8", errors="replace").splitlines()
                if not lines:
                    raise MediaToolError(f"{tool} 未返回版本信息：{info['path']}")
                info.update(available=True, status="ok", version=lines[0])
            except MediaToolError as exc:
                info["status"] = "error" if info["path"] else "missing"
                info["error"] = str(exc)
            tools[tool] = info
        errors = [info["error"] for info in tools.values() if info["error"]]
        status = {
            **tools["ffmpeg"], "available": all(info["available"] for info in tools.values()),
            "status": "error" if any(info["status"] == "error" for info in tools.values()) else ("missing" if errors else "ok"),
            "ffprobe_path": tools["ffprobe"]["path"], "ffprobe_available": tools["ffprobe"]["available"],
            "error": "\n".join(errors) or None,
        }
        _status_cache = (key, now, status)
        return dict(status)


def check_ffmpeg_exists() -> bool:
    return get_media_tools_status()["available"]


def ensure_ffmpeg_or_raise():
    status = get_media_tools_status()
    if not status["available"]:
        raise MediaToolError(status["error"])
