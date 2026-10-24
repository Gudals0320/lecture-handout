import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import assemble as a, transcribe as t
from pipeline.lecture import prepare


class FakeSegment:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class FakeWhisperModel:
    calls = []

    def __init__(self, model, device, compute_type):
        FakeWhisperModel.calls.append((model, device, compute_type))

    def transcribe(self, path, language=None, vad_filter=True, beam_size=5):
        info = types.SimpleNamespace(language=language or 'ko')
        return iter([FakeSegment(0.0, 2.5, ' 첫 문장. '), FakeSegment(3.0, 5.0, '둘째 문장'),
                     FakeSegment(50.0, 52.0, 'new block')]), info


class TranscribeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.lecture-test-', dir=Path(__file__).parent)
        self.root = Path(self.tmp.name).resolve()
        self.old = a.ROOT
        a.ROOT = self.root
        self.lecture = self.root / 'lectures/test-lecture'
        for d in ['input', 'work', 'output']:
            (self.lecture / d).mkdir(parents=True, exist_ok=True)
        FakeWhisperModel.calls = []

    def tearDown(self):
        a.ROOT = self.old
        self.tmp.cleanup()

    def test_render_groups_segments_into_timestamp_blocks(self):
        segments = [{'start_ms': 0, 'end_ms': 2000, 'text': ' a  b '}, {'start_ms': 10_000, 'end_ms': 11_000, 'text': 'c'},
                    {'start_ms': 46_000, 'end_ms': 47_000, 'text': 'd'}, {'start_ms': 3_700_000, 'end_ms': 3_701_000, 'text': 'e'}]
        text = t.render_transcript('Title', 'src', segments)
        self.assertEqual(text, 'Title\nsrc\n\n00:00:00\na b\nc\n\n00:00:46\nd\n\n01:01:40\ne\n')

    def test_group_tokens_splits_on_gap_and_sentence_end(self):
        tokens = [{'text': 'Hello', 'start_ms': 0, 'end_ms': 300}, {'text': ' world.', 'start_ms': 320, 'end_ms': 600},
                  {'text': ' Next', 'start_ms': 700, 'end_ms': 900}, {'text': ' far', 'start_ms': 5000, 'end_ms': 5200},
                  {'text': '!', 'start_ms': None, 'end_ms': None}]
        self.assertEqual(t.group_tokens(tokens), [
            {'start_ms': 0, 'end_ms': 600, 'text': 'Hello world.'},
            {'start_ms': 700, 'end_ms': 900, 'text': 'Next'},
            {'start_ms': 5000, 'end_ms': 5200, 'text': 'far!'}])

    def test_whisper_provider_writes_transcript_and_reuses_cache(self):
        (self.lecture / 'input/talk.mp3').write_bytes(b'not really audio')
        fake = types.ModuleType('faster_whisper')
        fake.WhisperModel = FakeWhisperModel
        with patch.dict(sys.modules, {'faster_whisper': fake}), patch.object(t, 'tool_path', return_value=None):
            first = t.transcribe(self.lecture, 'input/talk.mp3', 'whisper', language='ko', model='small', device='cpu')
            second = t.transcribe(self.lecture, 'input/talk.mp3', 'whisper', language='ko', model='small', device='cpu')
            third = t.transcribe(self.lecture, 'input/talk.mp3', 'whisper', language='ko', model='tiny', device='cpu')
        self.assertEqual(first['status'], 'transcribed')
        self.assertEqual(second['status'], 'reused')
        self.assertEqual(third['status'], 'transcribed')
        self.assertEqual(FakeWhisperModel.calls, [('small', 'cpu', 'default'), ('tiny', 'cpu', 'default')])
        text = (self.lecture / 'work/transcribe/talk.whisper.txt').read_text(encoding='utf-8')
        self.assertIn('\n00:00:00\n첫 문장.\n둘째 문장\n\n00:00:50\nnew block\n', text)
        inventory = a.inspect_lecture(self.lecture)
        self.assertEqual(inventory['audio'], ['input/talk.mp3'])
        self.assertEqual(inventory['raw_transcripts'], ['work/transcribe/talk.whisper.txt'])

    def test_external_provider_reports_timestamped_txt(self):
        with self.assertRaises(ValueError):
            t.transcribe(self.lecture, provider='external')
        (self.lecture / 'input/export.txt').write_text('제목\n\n00:01\n문장.\n\n01:02:03\n문장.\n', encoding='utf-8')
        result = t.transcribe(self.lecture, provider='external')
        self.assertEqual(result['transcripts'][0]['timestamp_lines'], 2)

    def test_prepare_requests_transcription_when_only_media_exists(self):
        (self.lecture / 'input/talk.m4a').write_bytes(b'x')
        report = prepare(self.lecture)
        stages = [task['stage'] for task in report['remaining_content_work']]
        self.assertEqual(stages, ['transcribe', 'review_and_map'])
        self.assertEqual(report['remaining_content_work'][0]['media'], ['input/talk.m4a'])

    def test_soniox_rejects_missing_key(self):
        (self.lecture / 'input/talk.mp3').write_bytes(b'x')
        with patch.dict('os.environ', {}, clear=True), patch.object(t, 'tool_path', return_value=None):
            with self.assertRaises(ValueError):
                t.transcribe(self.lecture, 'input/talk.mp3', 'soniox')


if __name__ == '__main__':
    unittest.main()
