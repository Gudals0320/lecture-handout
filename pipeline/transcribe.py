"""Speech-to-text stage with interchangeable sources.

Three ways to obtain a raw transcript for a lecture:
  external  the user exports a timestamped TXT elsewhere (Clova Note, Otter, ...)
            and drops it in input/; nothing runs here except a check.
  whisper   local faster-whisper; no network, the model is downloaded once.
  soniox    Soniox async API with an API key from the environment.

Every provider writes the same shape under work/transcribe/: a title line,
then blocks of one HH:MM:SS line followed by the sentences spoken from that
time. This is the layout the refinement prompt already expects, so the agent
step that follows does not care where the text came from.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import assemble as a

AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.flac', '.ogg', '.aac', '.opus', '.wma'}
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.mov', '.avi', '.webm'}
PROVIDERS = ('external', 'whisper', 'soniox')
BLOCK_SECONDS = 45          # start a new timestamp block after this much speech
GAP_MS = 700                # token gap that ends a Soniox segment
SONIOX_API = 'https://api.soniox.com'
SONIOX_MODEL = 'stt-async-v5'
MAX_TERMS = 300


def format_time(ms):
    seconds = max(0, int(ms)) // 1000
    return f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'


def render_transcript(title, source_line, segments):
    """Group segments into timestamp blocks; one block per BLOCK_SECONDS of speech."""
    lines = [title, source_line, '']
    block_start = None
    for segment in segments:
        text = re.sub(r'\s+', ' ', segment['text']).strip()
        if not text:
            continue
        if block_start is None or segment['start_ms'] - block_start >= BLOCK_SECONDS * 1000:
            if block_start is not None:
                lines.append('')
            block_start = segment['start_ms']
            lines.append(format_time(block_start))
        lines.append(text)
    lines.append('')
    return '\n'.join(lines)


def media_path(lecture, name):
    path = a.safe_path(lecture, name)
    a.require(path.is_relative_to(lecture / 'input') and path.is_file(), 'Select an audio or video file under input/.')
    a.require(path.suffix.lower() in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS, f'Unsupported media type: {path.suffix}')
    return path


def tool_path(explicit, env_name, binary):
    if explicit:
        path = Path(explicit).resolve()
        a.require(path.is_file(), f'{binary} not found: {path}')
        return str(path)
    candidate = os.environ.get(env_name)
    if candidate and Path(candidate).is_file():
        return candidate
    return shutil.which(binary)


def extract_audio(lecture, media, ffmpeg=None):
    """Convert video (or heavy audio) to a small mono MP3 so uploads and decoding stay cheap."""
    ffmpeg = tool_path(ffmpeg, 'LECTURE_FFMPEG', 'ffmpeg')
    if media.suffix.lower() in AUDIO_EXTENSIONS and not ffmpeg:
        return media
    a.require(ffmpeg, 'ffmpeg is required to extract audio from video; install it or set LECTURE_FFMPEG.')
    target = a.metadata(lecture, f'transcribe/{media.stem}-{a.file_hash(media)[:8]}.mp3')
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix('.partial.mp3')
    command = [ffmpeg, '-y', '-loglevel', 'error', '-i', str(media), '-vn', '-ac', '1', '-ar', '16000',
               '-c:a', 'libmp3lame', '-b:a', '64k', str(partial)]
    result = subprocess.run(command, capture_output=True, text=True)
    a.require(result.returncode == 0 and partial.is_file(), f'ffmpeg failed: {result.stderr.strip()[:300]}')
    partial.replace(target)
    return target


def terms_from_pdfs(lecture, limit=MAX_TERMS):
    """Latin-script vocabulary from the lecture PDFs; helps STT with domain words."""
    counts = {}
    for pdf in a.input_files(lecture, {'.pdf'}):
        for page in a.pdf_reader(pdf).pages:
            for word in re.findall(r'[A-Za-z][A-Za-z0-9+#.\-]{2,}', page.extract_text() or ''):
                word = word.strip('.-')
                if len(word) >= 3 and not word.isdigit():
                    counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, count in ranked if count >= 2][:limit]


def whisper_segments(audio, model='large-v3-turbo', device='auto', compute_type='default', language=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise ValueError('faster-whisper is not installed: pip install faster-whisper') from error
    engine = WhisperModel(model, device=device, compute_type=compute_type)
    segments, info = engine.transcribe(str(audio), language=language, vad_filter=True, beam_size=5)
    result = [{'start_ms': int(s.start * 1000), 'end_ms': int(s.end * 1000), 'text': s.text} for s in segments]
    return result, {'model': model, 'device': device, 'compute_type': compute_type,
                    'language': getattr(info, 'language', language)}


def group_tokens(tokens, gap_ms=GAP_MS, max_ms=30_000):
    """Soniox returns word tokens; join them into sentence-like segments."""
    segments = []
    for token in tokens:
        text = token.get('text', '')
        start, end = token.get('start_ms'), token.get('end_ms')
        if start is None:
            if segments:
                segments[-1]['text'] += text
            continue
        current = segments[-1] if segments else None
        split = (current is None or start - current['end_ms'] > gap_ms or start - current['start_ms'] > max_ms
                 or current['text'].rstrip().endswith(('.', '?', '!')))
        if split:
            segments.append({'start_ms': start, 'end_ms': end if end is not None else start, 'text': text})
        else:
            current['text'] += text
            current['end_ms'] = end if end is not None else current['end_ms']
    for segment in segments:
        segment['text'] = segment['text'].strip()
    return [s for s in segments if s['text']]


def soniox_segments(audio, api_key, language=None, terms=(), poll_every=3.0, max_wait=1800.0, http=None):
    if http is None:
        try:
            import httpx
        except ImportError as error:
            raise ValueError('httpx is not installed: pip install httpx') from error
        http = httpx.Client(base_url=SONIOX_API, headers={'Authorization': f'Bearer {api_key}'}, timeout=120.0)

    def call(method, path, **kwargs):
        response = http.request(method, path, **kwargs)
        a.require(response.status_code < 400, f'Soniox {method} {path} -> {response.status_code}: {response.text[:300]}')
        return response.json()

    with audio.open('rb') as handle:
        file_id = call('POST', '/v1/files', files={'file': (audio.name, handle)})['id']
    transcription_id = None
    try:
        payload = {'model': SONIOX_MODEL, 'file_id': file_id}
        if language:
            payload['language_hints'] = [language]
        if terms:
            payload['context'] = {'terms': list(terms)}
        transcription_id = call('POST', '/v1/transcriptions', json=payload)['id']
        deadline = time.monotonic() + max_wait
        while True:
            status = call('GET', f'/v1/transcriptions/{transcription_id}')
            if status.get('status') == 'completed':
                break
            a.require(status.get('status') != 'error', f"Soniox transcription failed: {status.get('error_message')}")
            a.require(time.monotonic() < deadline, f'Soniox transcription not done after {max_wait:.0f}s')
            time.sleep(poll_every)
        raw = call('GET', f'/v1/transcriptions/{transcription_id}/transcript')
    finally:
        cleanup = ([f'/v1/transcriptions/{transcription_id}'] if transcription_id else []) + [f'/v1/files/{file_id}']
        for path in cleanup:
            try:
                http.delete(path)
            except Exception:  # best effort; nothing of the lecture should stay remote
                pass
    return group_tokens(raw.get('tokens', [])), {'model': SONIOX_MODEL, 'language': language, 'terms': len(terms)}


def external_check(lecture):
    transcripts = [a.relative(lecture, p) for p in a.input_files(lecture, {'.txt'})]
    a.require(transcripts, 'No raw transcript TXT in input/. Export one from your transcription app, '
                           'or run transcribe with --provider whisper or soniox.')
    report = []
    for name in transcripts:
        text = a.safe_path(lecture, name).read_text(encoding='utf-8-sig', errors='replace')
        stamps = re.findall(r'(?m)^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*$', text)
        report.append({'transcript': name, 'timestamp_lines': len(stamps), 'characters': len(text)})
    return {'status': 'external', 'provider': 'external', 'transcripts': report}


def transcribe(lecture, media_name=None, provider='whisper', language=None, model='large-v3-turbo', device='auto',
               compute_type='default', pdf_terms=True, ffmpeg=None, api_key=None, progress=None):
    a.require(provider in PROVIDERS, f'Provider must be one of {", ".join(PROVIDERS)}.')
    if provider == 'external':
        return external_check(lecture)
    a.require(media_name, 'Pass --media with an audio or video file under input/.')
    media = media_path(lecture, media_name)
    source_hash = a.file_hash(media)
    options = {'provider': provider, 'language': language}
    if provider == 'whisper':
        options.update(model=model, device=device, compute_type=compute_type)
    else:
        options.update(model=SONIOX_MODEL, pdf_terms=pdf_terms)
    output = a.metadata(lecture, f'transcribe/{media.stem}.{provider}.txt')
    receipt_path = output.with_suffix('.json')
    receipt = a.read_json(receipt_path)
    if (receipt and receipt.get('source_sha256') == source_hash and receipt.get('options') == options
            and output.is_file() and a.file_hash(output) == receipt.get('transcript_sha256')):
        return {'status': 'reused', **receipt}
    if progress:
        progress({'stage': 'audio', 'media': media.name})
    audio = extract_audio(lecture, media, ffmpeg)
    if progress:
        progress({'stage': provider, 'audio': audio.name})
    if provider == 'whisper':
        segments, info = whisper_segments(audio, model, device, compute_type, language)
    else:
        key = api_key or os.environ.get('SONIOX_API_KEY')
        a.require(key, 'Set SONIOX_API_KEY in the environment (or pass --api-key).')
        terms = terms_from_pdfs(lecture) if pdf_terms else []
        segments, info = soniox_segments(audio, key, language, terms)
    a.require(segments, 'The recognizer returned no speech.')
    source_line = f'{provider} / {info.get("model")} / {format_time(segments[-1]["end_ms"])}'
    output.parent.mkdir(parents=True, exist_ok=True)
    a.atomic_write(output, render_transcript(media.stem, source_line, segments).encode('utf-8'))
    receipt = {'media': a.relative(lecture, media), 'source_sha256': source_hash, 'options': options, 'info': info,
               'segments': len(segments), 'transcript': a.relative(lecture, output),
               'transcript_sha256': a.file_hash(output)}
    a.write_json(receipt_path, receipt)
    return {'status': 'transcribed', **receipt}
