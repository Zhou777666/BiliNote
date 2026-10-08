import importlib.util
import logging
from pathlib import Path
import sys
import types

import pytest


@pytest.fixture
def whisper(monkeypatch, tmp_path):
    def stub(name, **attrs):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    stub('app.utils.cuda_runtime', prepare_cuda_runtime=lambda: None,
         get_cuda_status=lambda: {'available': True},
         is_cuda_error=lambda exc: 'cuda' in str(exc).lower())
    stub('faster_whisper', WhisperModel=lambda **kwargs: types.SimpleNamespace(kwargs=kwargs))
    stub('faster_whisper.utils', download_model=lambda *args, **kwargs: str(tmp_path))
    stub('app.decorators.timeit', timeit=lambda fn: fn)
    stub('app.transcriber.base', Transcriber=object)
    stub('app.utils.logger', get_logger=lambda name: logging.getLogger(name))
    registry_spec = importlib.util.spec_from_file_location('isolated_registry', Path(__file__).resolve().parents[1] / 'app/transcriber/whisper_models.py')
    registry = importlib.util.module_from_spec(registry_spec)
    registry_spec.loader.exec_module(registry)
    stub('app.transcriber.whisper_models', resolve_whisper_model=lambda name: name,
         is_local_target=lambda target: False, whisper_model_files_missing=registry.whisper_model_files_missing)
    stub('app.utils.path_helper', get_model_dir=lambda name: str(tmp_path))
    stub('events', transcription_finished=object())
    # Use the real result dataclasses, without importing any transcription runtime.
    for module_name, file in [('app.models.transcriber_model', 'app/models/transcriber_model.py')]:
        spec = importlib.util.spec_from_file_location(module_name, Path(__file__).resolve().parents[1] / file)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)
    spec = importlib.util.spec_from_file_location('isolated_whisper', Path(__file__).resolve().parents[1] / 'app/transcriber/whisper.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (tmp_path / name).write_text('test')
    return module, tmp_path


def test_cached_model_never_calls_network(whisper, monkeypatch):
    module, path = whisper
    calls = []
    def download(target, **kwargs):
        assert kwargs['local_files_only'] is True
        calls.append(kwargs)
        return str(path)
    monkeypatch.setattr(module, 'download_model', download)
    transcriber = module.WhisperTranscriber('tiny')
    assert transcriber.model.kwargs['model_size_or_path'] == str(path)
    assert transcriber.model.kwargs['local_files_only'] is True
    assert len(calls) == 1


def test_first_download_only_when_cache_is_absent(whisper, monkeypatch):
    module, path = whisper
    calls = []
    def download(target, **kwargs):
        calls.append(kwargs['local_files_only'])
        if kwargs['local_files_only']:
            raise module.LocalEntryNotFoundError('not cached')
        return str(path)
    monkeypatch.setattr(module, 'download_model', download)
    module.WhisperTranscriber('tiny')
    assert calls == [True, False]


def test_machine_without_cuda_uses_local_cpu_model(whisper, monkeypatch):
    module, _ = whisper
    monkeypatch.setattr(module, 'get_cuda_status', lambda: {'available': False, 'reason': 'no NVIDIA GPU'})
    transcriber = module.WhisperTranscriber('tiny')
    assert transcriber.device == 'cpu' and transcriber.compute_type == 'int8'


def test_cuda_model_error_reuses_files_on_cpu(whisper, monkeypatch):
    module, path = whisper
    devices = []
    def model(**kwargs):
        devices.append(kwargs['device'])
        if kwargs['device'] == 'cuda':
            raise RuntimeError('CUDA out of memory')
        return types.SimpleNamespace(kwargs=kwargs)
    monkeypatch.setattr(module, 'WhisperModel', model)
    transcriber = module.WhisperTranscriber('tiny')
    assert devices == ['cuda', 'cpu']
    assert transcriber.device == 'cpu' and transcriber.compute_type == 'int8'
    assert (path / 'model.bin').read_text() == 'test'


def test_lazy_cuda_error_during_transcription_retries_on_cpu(whisper, monkeypatch):
    module, _ = whisper
    devices = []
    def model(**kwargs):
        device = kwargs['device']
        def transcribe(file):
            devices.append(device)
            def segments():
                if device == 'cuda':
                    raise RuntimeError('CUDA execution failed')
                yield types.SimpleNamespace(start=0, end=1, text=' test speech ')
            return segments(), types.SimpleNamespace(language='en')
        return types.SimpleNamespace(transcribe=transcribe)
    monkeypatch.setattr(module, 'WhisperModel', model)
    result = module.WhisperTranscriber('tiny').transcript('local audio.wav')
    assert result.full_text == 'test speech'
    assert devices == ['cuda', 'cpu']


def test_non_cuda_load_error_preserves_cache_and_is_not_retried(whisper, monkeypatch):
    module, path = whisper
    def broken(**kwargs):
        raise ValueError('invalid model file')
    monkeypatch.setattr(module, 'WhisperModel', broken)
    with pytest.raises(ValueError, match='invalid model'):
        module.WhisperTranscriber('tiny')
    assert (path / 'model.bin').exists()


def test_missing_tokenizer_fails_without_silent_network_fetch(whisper):
    module, path = whisper
    (path / 'tokenizer.json').unlink()
    with pytest.raises(RuntimeError, match='tokenizer.json'):
        module.WhisperTranscriber('tiny')
    assert (path / 'model.bin').exists()


def test_partial_model_is_not_reported_offline_ready(whisper):
    module, path = whisper
    assert not module.whisper_model_files_missing(path)
    (path / 'config.json').write_text('')
    assert module.whisper_model_files_missing(path) == ['config.json']


def test_transcription_error_is_propagated_instead_of_returning_none(whisper, monkeypatch):
    module, _ = whisper
    transcriber = module.WhisperTranscriber('tiny', device='cpu')
    def broken(file):
        raise ValueError('audio is invalid')
    transcriber.model.transcribe = broken
    with pytest.raises(RuntimeError, match='audio is invalid'):
        transcriber.transcript('broken.wav')
