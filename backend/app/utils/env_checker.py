def is_cuda_available() -> bool:
    from app.utils.cuda_runtime import get_cuda_status
    return get_cuda_status()["available"]
def is_torch_installed() -> bool:
    try:
        import torch
        return True
    except ImportError:
        return False
