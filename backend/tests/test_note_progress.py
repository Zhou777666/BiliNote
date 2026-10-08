"""Exercise the real summary/status methods without downloader/LLM dependencies."""
import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def note_methods(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    namespace = {'json': json, 'NOTE_OUTPUT_DIR': tmp_path, 'logger': logging.getLogger(__name__),
                 'GPTSource': lambda **kwargs: SimpleNamespace(**kwargs)}
    exec(compile((backend / 'app/enmus/task_status_enums.py').read_text(encoding='utf-8'), 'task_status', 'exec'), namespace)
    tree = ast.parse((backend / 'app/services/note.py').read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'NoteGenerator')
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in ('_summarize_text', '_update_status', '_transcribe_audio')]
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), 'note_methods', 'exec'), namespace)
    generator = namespace['NoteGenerator']()
    generator._handle_exception = lambda task, exc: generator._update_status(task, namespace['TaskStatus'].FAILED, str(exc))
    return generator, namespace['TaskStatus']


@pytest.mark.parametrize('task', ['sample-uuid', 'task_with_underscores'])
@pytest.mark.parametrize('fail', [False, True])
def test_summary_updates_the_same_status_file_polled_by_frontend(note_methods, tmp_path, task, fail):
    generator, Status = note_methods
    generator._update_status(task, Status.TRANSCRIBING)
    status_file = tmp_path / f'{task}.status.json'
    def summarize(source):
        assert json.loads(status_file.read_text())['status'] == 'SUMMARIZING'
        assert source.checkpoint_key == f'{task}_markdown'
        if fail:
            raise RuntimeError('summary network interrupted')
        return 'generated note'
    args = dict(audio_meta=SimpleNamespace(title='title', raw_info={}), transcript=SimpleNamespace(segments=[]),
                gpt=SimpleNamespace(summarize=summarize), markdown_cache_file=tmp_path/f'{task}_markdown.md',
                link=False, screenshot=False, formats=[], style=None, extras=None, video_img_urls=[])
    if fail:
        with pytest.raises(RuntimeError, match='network interrupted'):
            generator._summarize_text(**args)
        assert json.loads(status_file.read_text())['status'] == 'FAILED'
    else:
        assert generator._summarize_text(**args) == 'generated note'
    assert not (tmp_path / f'{task}_markdown.status.json').exists()


def test_model_initialization_failure_is_recorded_on_the_real_task(note_methods, tmp_path):
    generator, Status = note_methods
    generator.transcriber = None
    def unavailable():
        raise RuntimeError('local model missing')
    generator._init_transcriber = unavailable
    with pytest.raises(RuntimeError, match='local model missing'):
        generator._transcribe_audio('audio.wav', tmp_path/'task_with_underscores_transcript.json', Status.TRANSCRIBING)
    state = json.loads((tmp_path/'task_with_underscores.status.json').read_text())
    assert state['status'] == 'FAILED' and 'local model missing' in state['message']
