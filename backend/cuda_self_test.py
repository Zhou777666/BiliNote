"""Validate frozen CUDA libraries on CI even when the runner has no GPU."""
import sys
from app.utils.cuda_runtime import prepare_cuda_runtime, _check_windows_libraries, get_cuda_status


def run():
    directories = prepare_cuda_runtime()
    if sys.platform == "win32":
        _check_windows_libraries(directories)
    import ctranslate2
    assert ctranslate2.get_supported_compute_types("cpu"), "CTranslate2 CPU runtime unavailable"
    status = get_cuda_status(force=True)
    print(f"CUDA runtime self-test passed: libraries loaded, CTranslate2={ctranslate2.__version__}, GPU available={status['available']}")


if __name__ == "__main__":
    run()
