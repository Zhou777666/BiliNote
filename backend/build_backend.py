"""Build the backend without copying/deleting the developer's .env file."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


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
    ]
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
    print(f"Backend ready: {executable}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target")
    build(parser.parse_args().target)
