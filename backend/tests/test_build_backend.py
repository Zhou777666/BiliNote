import importlib.util
import os
from pathlib import Path


def test_build_uses_defaults_and_preserves_private_env(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "build_backend.py"
    spec = importlib.util.spec_from_file_location("isolated_backend_build", source)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    backend = tmp_path / "backend"
    providers = backend / "app" / "db" / "builtin_providers.json"
    providers.parent.mkdir(parents=True)
    providers.write_text("[]")
    (tmp_path / ".env.example").write_text("DEFAULT=1\n")
    (tmp_path / "LICENSE").write_text("MIT")
    for path in (tmp_path / ".env", backend / ".env"):
        path.write_text("PRIVATE_KEY=do-not-package\n")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if "PyInstaller" in command:
            output = tmp_path / "BillNote_frontend" / "src-tauri" / "bin" / "BiliNoteBackend"
            output.mkdir(parents=True)
            (output / ("BiliNoteBackend.exe" if os.name == "nt" else "BiliNoteBackend")).write_bytes(b"test")

    monkeypatch.setattr(builder.subprocess, "run", run)
    builder.build("x86_64-pc-windows-msvc" if os.name == "nt" else "aarch64-apple-darwin")
    for path in (tmp_path / ".env", backend / ".env"):
        assert path.read_text() == "PRIVATE_KEY=do-not-package\n"
    assert (backend / "build" / "packaging" / ".env").read_text() == "DEFAULT=1\n"
    packaging = next(command for command in commands if "PyInstaller" in command)
    separator = ";" if os.name == "nt" else ":"
    sources = [packaging[index + 1].split(separator)[0] for index, arg in enumerate(packaging) if arg == "--add-data"]
    assert all(Path(path).is_absolute() for path in sources)
    assert str(tmp_path / ".env") not in sources and str(backend / ".env") not in sources
