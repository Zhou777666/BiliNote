from app.utils.cuda_runtime import prepare_cuda_runtime, get_cuda_status, is_cuda_error

prepare_cuda_runtime()
from faster_whisper import WhisperModel
from faster_whisper.utils import download_model
from huggingface_hub.errors import LocalEntryNotFoundError

from app.decorators.timeit import timeit
from app.models.transcriber_model import TranscriptSegment, TranscriptResult
from app.transcriber.base import Transcriber
from app.transcriber.whisper_models import (
    resolve_whisper_model,
    is_local_target,
    whisper_model_files_missing,
)
from app.utils.logger import get_logger
from app.utils.path_helper import get_model_dir

from events import transcription_finished
from pathlib import Path
import threading


'''
 Size of the model to use (tiny, tiny.en, base, base.en, small, small.en, distil-small.en, medium, medium.en, distil-medium.en, large-v1, large-v2, large-v3, large, distil-large-v2, distil-large-v3, large-v3-turbo, or turbo
'''
logger=get_logger(__name__)

# Models are resolved once before GPU initialization, preferring complete local
# snapshots. CUDA errors must never delete the model or trigger a re-download.
class WhisperTranscriber(Transcriber):
    def __init__(
            self,
            model_size: str = "base",
            device: str = 'auto',
            compute_type: str = None,
            cpu_threads: int = 0,
    ):
        if device not in (None, 'auto', 'cpu', 'cuda'):
            raise ValueError(f"不支持的转写设备: {device}")
        self.device = 'cpu'
        supported = []
        if device in ('auto', 'cuda'):
            status = get_cuda_status()
            if status['available']:
                self.device = 'cuda'
                supported = status.get('compute_types', [])
            else:
                logger.warning(f"本地 Whisper 使用 CPU：{status['reason']}")
        cuda_type = 'float16' if not supported or 'float16' in supported else 'float32'
        self.compute_type = compute_type or (cuda_type if self.device == "cuda" else "int8")
        self._transcription_lock = threading.Lock()
        self.cpu_threads = cpu_threads
        self.model_size = model_size
        self.model_path = self._resolve_model_path(model_size, get_model_dir("whisper"))
        try:
            self.model = self._build_model()
        except Exception as exc:
            if self.device != 'cuda' or not is_cuda_error(exc):
                raise
            self._fallback_to_cpu(exc)
        logger.info(f"本地 Whisper 已就绪：模型={model_size}, device={self.device}, compute_type={self.compute_type}")

    @staticmethod
    def _resolve_model_path(model_size: str, model_dir: str) -> str:
        target = resolve_whisper_model(model_size)
        if is_local_target(target):
            path = str(Path(target).expanduser().resolve())
        else:
            try:
                path = download_model(target, cache_dir=model_dir, local_files_only=True)
            except LocalEntryNotFoundError:
                logger.info(f"本地无模型 {model_size}，首次下载后将使用离线缓存")
                path = download_model(target, cache_dir=model_dir, local_files_only=False)
        # faster-whisper otherwise fetches a tokenizer separately, even when
        # local_files_only=True. Fail explicitly rather than using the network.
        missing = whisper_model_files_missing(path)
        if missing:
            raise RuntimeError(f"本地模型不完整，缺少 {', '.join(missing)}：{path}。请在设置中完成模型下载；现有缓存已保留。")
        return path

    def _build_model(self) -> WhisperModel:
        return WhisperModel(
            model_size_or_path=self.model_path,
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
            local_files_only=True,
        )

    def _fallback_to_cpu(self, exc):
        logger.warning(f"CUDA 转写不可用，使用已缓存模型切换到 CPU：{exc}")
        self.device, self.compute_type = 'cpu', 'int8'
        self.model = None
        self.model = self._build_model()

    @staticmethod
    def is_cuda() -> bool:
        return get_cuda_status()['available']

    @timeit
    def transcript(self, file_path: str) -> TranscriptResult:
        # A fallback rebuild changes the shared cached transcriber instance.
        with self._transcription_lock:
            return self._transcript_with_fallback(file_path)

    def _transcript_with_fallback(self, file_path):
        try:
            return self._transcript_once(file_path)
        except Exception as exc:
            # CTranslate2 performs GPU work while iterating the lazy segments.
            if self.device == 'cuda' and is_cuda_error(exc):
                self._fallback_to_cpu(exc)
                return self._transcript_once(file_path)
            raise RuntimeError(f"本地语音转写失败：{exc}") from exc

    def _transcript_once(self, file_path):
        segments_raw, info = self.model.transcribe(file_path)
        segments = [TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip())
                    for seg in segments_raw]
        return TranscriptResult(language=info.language,
                                full_text=' '.join(seg.text for seg in segments),
                                segments=segments, raw=info)


    def on_finish(self,video_path:str,result: TranscriptResult)->None:
        print("转写完成")
        transcription_finished.send({
            "file_path": video_path,
        })

