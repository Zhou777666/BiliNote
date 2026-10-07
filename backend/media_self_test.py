"""Offline media smoke test, also usable from the frozen Windows backend."""
import os
from pathlib import Path
import tempfile

from ffmpeg_helper import get_media_tools_status, probe_media, run_ffmpeg


def run():
    original_path = os.getenv("PATH")
    for _ in range(300):
        status = get_media_tools_status()
        assert status["available"], status["error"]
        assert os.getenv("PATH") == original_path, "Health checks changed PATH"
    with tempfile.TemporaryDirectory(prefix="BiliNote media ") as temporary:
        directory = Path(temporary)
        video, audio, screenshot = directory / "输入视频.mp4", directory / "音频.mp3", directory / "截图.jpg"
        run_ffmpeg(["-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "mpeg4", "-c:a", "aac", "-shortest", video], timeout=30)
        assert float(probe_media(video)["format"]["duration"]) > 0
        run_ffmpeg(["-y", "-i", video, "-vn", "-acodec", "libmp3lame", audio], timeout=30)
        run_ffmpeg(["-y", "-ss", "1", "-i", video, "-frames:v", "1", screenshot], timeout=30)
        assert audio.stat().st_size > 0 and screenshot.stat().st_size > 0
    print("Media self-test passed: 300 health polls, FFprobe, MP3 and screenshot, Unicode/space paths.")


if __name__ == "__main__":
    run()
