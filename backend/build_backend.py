"""Build the backend without copying/deleting the developer's .env file."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def cuda_bundle_inputs():
    """Include dynamically loaded CUDA DLLs and NVIDIA redistribution licenses."""
    binaries, licenses = [], []
    for name in ("nvidia-cublas-cu12", "nvidia-cudnn-cu12", "nvidia-cuda-nvrtc-cu12"):
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError("Windows GPU 构建依赖未安装，请先安装 backend/requirements-windows-gpu.txt") from exc
        library_count, license_count = 0, 0
        for file in distribution.files or []:
            source = Path(distribution.locate_file(file)).resolve()
            if file.suffix == ".dll":
                binaries.append((source, str(file.parent).replace("\\", "/")))
                library_count += 1
            elif "license" in file.name.lower():
                licenses.append((source, f"licenses/nvidia/{name}"))
                license_count += 1
        if not library_count or not license_count:
            raise RuntimeError(f"{name} 的 CUDA 运行库或许可证文件不完整")
    return binaries, licenses


def build(target=None):
    if target is None:
        target = subprocess.check_output(["rustc", "-Vv"], text=True).split("host: ")[1].splitlines()[0]
    if os.name == "nt" and target != "x86_64-pc-windows-msvc":
        raise RuntimeError("This Windows media bundle supports x86_64-pc-windows-msvc only")
    backend = ROOT / "backend"
    stage = backend / "build" / "packaging"
    stage.mkdir(parents=True, exist_ok=True)
    (stage / ".env").write_bytes((ROOT / ".env.example").read_bytes())
    output = ROOT / "BillNote_frontend" / "src-tauri" / "bin"
    command = [
        sys.executable, "-m", "PyInstaller", "--clean", "-y", "--name", "BiliNoteBackend",
        "--paths", str(backend), "--distpath", str(output),
        "--workpath", str(backend / "build" / "pyinstaller"), "--specpath", str(stage),
        "--hidden-import", "uvicorn", "--hidden-import", "fastapi", "--hidden-import", "starlette",
        "--collect-data", "faster_whisper",
    ]
    if sys.version_info < (3, 12):
        command.extend(["--hidden-import", "backports.tarfile"])
    separator = ";" if os.name == "nt" else ":"
    for source, destination in [
        (stage / ".env", "."),
        (backend / "app" / "db" / "builtin_providers.json", "."),
        (backend / "app" / "db" / "builtin_providers.json", "app/db"),
        (ROOT / "LICENSE", "."),
    ]:
        command.extend(["--add-data", f"{source}{separator}{destination}"])
    if os.name == "nt":
        subprocess.run([sys.executable, str(ROOT / "scripts" / "prepare_ffmpeg.py")], check=True)
        command.extend(["--add-data", f"{backend / 'tools' / 'ffmpeg'}{separator}tools/ffmpeg"])
        binaries, licenses = cuda_bundle_inputs()
        for source, destination in binaries:
            command.extend(["--add-binary", f"{source}{separator}{destination}"])
        for source, destination in licenses:
            command.extend(["--add-data", f"{source}{separator}{destination}"])
    command.append(str(backend / "main.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    extension = ".exe" if os.name == "nt" else ""
    app_dir = output / "BiliNoteBackend"
    executable = app_dir / f"BiliNoteBackend-{target}{extension}"
    (app_dir / f"BiliNoteBackend{extension}").replace(executable)
    if os.name == "nt":
        env = os.environ.copy()
        env["FFMPEG_BIN_PATH"] = ""
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        subprocess.run([str(executable), "--media-self-test"], cwd=stage, env=env, check=True, timeout=90)
        subprocess.run([str(executable), "--cuda-runtime-self-test"], cwd=stage, env=env, check=True, timeout=90)
    print(f"Backend ready: {executable}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target")
    build(parser.parse_args().target)
