"""Download a pinned Windows FFmpeg package and verify it before bundling."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "9.0.2"
URL = f"https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-{VERSION}-essentials_build.zip"
SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"


def prepare():
    cache = ROOT / "backend" / "build" / "media-downloads"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"ffmpeg-{VERSION}.zip"
    if not archive.exists():
        print(f"Downloading {URL}", flush=True)
        request = urllib.request.Request(URL, headers={"User-Agent": "BiliNote-build"})
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != SHA256:
        archive.unlink()
        raise RuntimeError("FFmpeg archive checksum mismatch; removed the invalid cache. Retry the download.")
    destination = ROOT / "backend" / "tools" / "ffmpeg"
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for tool in ("ffmpeg.exe", "ffprobe.exe"):
            matches = [name for name in package.namelist() if name.endswith(f"/bin/{tool}")]
            if len(matches) != 1:
                raise RuntimeError(f"Expected exactly one {tool} in the verified archive")
            with package.open(matches[0]) as source, (destination / tool).open("wb") as output:
                shutil.copyfileobj(source, output)
        # Preserve the distributor's license and build notes verbatim.
        for name in package.namelist():
            if Path(name).name.lower() in ("license", "license.txt", "readme.txt"):
                (destination / Path(name).name).write_bytes(package.read(name))
    if not any((destination / name).exists() for name in ("LICENSE", "LICENSE.txt")):
        raise RuntimeError("The package license is missing; refusing to bundle FFmpeg")
    (destination / "BUILD-SOURCE.json").write_text(json.dumps({
        "version": VERSION, "archive": URL, "sha256": SHA256,
        "ffmpeg_source": "https://github.com/FFmpeg/FFmpeg/tree/946fcce07b",
        "distributor": "https://www.gyan.dev/ffmpeg/builds/",
        "redistribution": "GPL build; distribute the corresponding FFmpeg and library sources when publishing binaries.",
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Verified FFmpeg {VERSION}: {destination}", flush=True)
    return destination


if __name__ == "__main__":
    prepare()
