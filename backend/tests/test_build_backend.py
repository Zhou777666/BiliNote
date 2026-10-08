import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import pytest


def test_build_uses_defaults_and_preserves_private_env(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "build_backend.py"
    spec = importlib.util.spec_from_file_location("isolated_backend_build", source)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "cuda_bundle_inputs", lambda: ([], []))
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


def test_cuda_binaries_and_licenses_are_packaged(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'build_backend.py'
    spec = importlib.util.spec_from_file_location('cuda_packaging_test', source)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    def distribution(name):
        return SimpleNamespace(files=[Path(f'nvidia/{name}/bin/runtime.dll'), Path(f'{name}.dist-info/License.txt')],
                               locate_file=lambda file: tmp_path / file)
    monkeypatch.setattr(builder.importlib.metadata, 'distribution', distribution)
    binaries, licenses = builder.cuda_bundle_inputs()
    assert len(binaries) == len(licenses) == 3
    assert all(path.is_absolute() for path, destination in binaries + licenses)
    assert all(destination.startswith('nvidia/') for path, destination in binaries)
    assert all(destination.startswith('licenses/nvidia/') for path, destination in licenses)
    monkeypatch.setattr(builder.importlib.metadata, 'distribution',
                        lambda name: SimpleNamespace(files=[], locate_file=lambda file: tmp_path / file))
    with pytest.raises(RuntimeError, match='nvidia-cublas-cu12'):
        builder.cuda_bundle_inputs()
