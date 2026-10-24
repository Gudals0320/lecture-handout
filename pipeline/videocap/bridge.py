"""Headless VideoCap-compatible extraction with cached representative exports."""
from pathlib import Path
import threading
from .. import assemble as a
from . import capture_engine as engine


def representative_ids(candidates, threshold=8):
    a.require(type(threshold) is int and 0 <= threshold <= 64, 'dHash threshold must be 0..64.')
    selected, previous = [], None
    for candidate in candidates:
        try:
            joined = previous is not None and (int(previous['dhash'], 16) ^ int(candidate['dhash'], 16)).bit_count() <= threshold
        except (ValueError, KeyError):
            joined = False
        if joined:
            selected[-1] = candidate['id']
        else:
            selected.append(candidate['id'])
        previous = candidate
    return selected


def capture(lecture, video_name, threshold=8, ffprobe=None, progress=None, cancel=None):
    video = a.safe_path(lecture, video_name)
    a.require(video.is_relative_to(lecture/'input') and video.is_file(), 'Select a video under input/.')
    a.require(video.suffix.lower() in {'.mp4', '.mkv', '.mov', '.avi', '.webm'}, 'Unsupported video format.')
    a.require(type(threshold) is int and 0 <= threshold <= 64, 'dHash threshold must be 0..64.')
    source_hash = a.file_hash(video)
    engine_hash = a.file_hash(Path(engine.__file__))
    session = a.metadata(lecture, f'capture/video-{source_hash[:16]}-dh{threshold}')
    session.mkdir(parents=True, exist_ok=True)
    result_path = session/'extraction.json'
    result = a.read_json(result_path)
    if result and result.get('complete') and result.get('engine_sha256') == engine_hash and result['source']['sha256'] == source_hash:
        for candidate in result['candidates']:
            image = a.safe_path(lecture, a.relative(lecture, session/candidate['file']))
            a.require(image.is_file() and a.file_hash(image) == candidate['sha256'], 'Cached capture candidate changed.')
    else:
        a.require(not result or not result.get('complete'), 'Extraction engine changed; review the existing cache before replacing it.')
        result = engine.extract_candidates(video, session, ffprobe, cancel or threading.Event(), progress)
        result['engine_sha256'] = engine_hash
        for candidate in result['candidates']:
            candidate['sha256'] = a.file_hash(session/candidate['file'])
        a.write_json(result_path, result)
        a.require(result['complete'], 'Capture was interrupted; candidates retained, no complete export published.')
    selected = representative_ids(result['candidates'], threshold)
    receipt_path = session/'capture.json'
    receipt = a.read_json(receipt_path)
    if receipt and receipt['source_sha256'] == source_hash and receipt['selected_ids'] == selected:
        manifest_path = a.safe_path(lecture, receipt['manifest'])
        if manifest_path.is_file() and not (manifest_path.parent/'.incomplete').exists():
            manifest = a.read_json(manifest_path)
            if all((manifest_path.parent/e['file']).is_file() and a.file_hash(manifest_path.parent/e['file']) == e['sha256'] for e in manifest['exports']):
                return {'status': 'reused', **receipt}
    # The native exporter preserves its manifest/schema and uses a fresh directory.
    # Only the cache receipt is replaced; no earlier image directory is deleted.
    exported = engine.export_candidates(session, result['candidates'], selected, session/'representatives', result['source'],
        {'candidate_count':len(result['candidates']), 'selected_count':len(selected),
         'automatic_policy':'dhash_last_v1', 'grouping_threshold':threshold, 'extraction_complete':True})
    receipt = {'video':a.relative(lecture, video), 'source_sha256':source_hash,
               'candidate_count':len(result['candidates']), 'representative_count':len(selected),
               'grouping_threshold':threshold, 'selected_ids':selected,
               'manifest':a.relative(lecture, exported/'manifest.json'),
               'candidates':a.relative(lecture, result_path)}
    a.write_json(receipt_path, receipt)
    return {'status':'captured', **receipt}
