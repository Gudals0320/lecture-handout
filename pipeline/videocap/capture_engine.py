"""Local, full-resolution slide candidate capture and non-destructive export.

Detection deliberately retains R001's frame-difference defaults: every frame,
threshold 80, a 7x7 elliptical dilation, 0.06 percent changed pixels, and a
capture 85 frames after the first change. The first and final decoded frames
are always included on a completed run. No model or network is used here.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import cv2
import numpy as np


DETECTION = {
    "name": "frame_difference",
    "pixel_threshold": 80,
    "dilation_shape": "ellipse",
    "dilation_size": [7, 7],
    "minimum_changed_percent": 0.06,
    "capture_delay_frames": 85,
    "sample_every_frames": 1,
    "include_first_and_final": True,
}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _run_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _positive_number(value, default=0.0):
    try:
        if isinstance(value, str) and "/" in value:
            numerator, denominator = value.split("/", 1)
            result = float(numerator) / float(denominator)
        else:
            result = float(value)
        return result if math.isfinite(result) and result > 0 else default
    except (ValueError, TypeError, ZeroDivisionError):
        return default


def _open_video(video_path):
    # Windows sandbox may deny strict final-path handle queries while allowing
    # normal file reads. Existence and decoding are checked explicitly below.
    path = Path(video_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Video is not a file: {path}")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise ValueError(f"Cannot decode this video: {path}")
    return path, capture


def probe_video(video_path, ffprobe_exe=None):
    """Read metadata; use ffprobe when supplied and OpenCV as a fallback."""
    path, capture = _open_video(video_path)
    try:
        cv_meta = {
            "fps": _positive_number(capture.get(cv2.CAP_PROP_FPS)),
            "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "frame_count": int(_positive_number(capture.get(cv2.CAP_PROP_FRAME_COUNT))),
        }
    finally:
        capture.release()
    stream, container = {}, {}
    if ffprobe_exe:
        try:
            result = subprocess.run(
                [str(ffprobe_exe), "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration,start_time:format=duration",
                 "-of", "json", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=True, timeout=60, **_run_options(),
            )
            info = json.loads(result.stdout)
            stream = next(iter(info.get("streams", [])), {})
            container = info.get("format", {})
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    fps = _positive_number(stream.get("avg_frame_rate")) or cv_meta["fps"]
    fps = fps or _positive_number(stream.get("r_frame_rate"))
    if not fps:
        raise ValueError("The video has no usable frame rate.")
    count = int(_positive_number(stream.get("nb_frames"))) or cv_meta["frame_count"]
    duration = _positive_number(stream.get("duration"))
    duration = duration or (count / fps if count else _positive_number(container.get("duration")))
    count = count or int(round(duration * fps))
    try:
        start_time = float(stream.get("start_time", 0))
        if not math.isfinite(start_time):
            start_time = 0.0
    except (TypeError, ValueError):
        start_time = 0.0
    return {
        "duration": duration, "fps": fps,
        "width": cv_meta["width"] or int(stream.get("width", 0)),
        "height": cv_meta["height"] or int(stream.get("height", 0)),
        "frame_count": count, "start_time": start_time,
        "metadata_backend": "ffprobe" if stream else "opencv",
    }


def _inside(root, relative):
    root = Path(root).expanduser().resolve()
    rel = Path(relative)
    if rel.is_absolute():
        raise ValueError("Session file paths must be relative.")
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f"Path escapes the session directory: {relative}")
    return path


def _cancelled(cancel_event):
    return cancel_event is not None and cancel_event.is_set()


def _progress(callback, stage, frame, total, progress):
    if callback:
        callback({"stage": stage, "frame": frame, "total": total,
                  "progress": min(1.0, max(0.0, float(progress)))})


def _source_hash(path, cancel_event, callback, total_frames):
    digest = hashlib.sha256()
    total = max(path.stat().st_size, 1)
    processed = 0
    last_report = 0.0
    _progress(callback, "hashing", 0, total_frames, 0)
    with path.open("rb") as handle:
        while True:
            if _cancelled(cancel_event):
                return None
            chunk = handle.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            processed += len(chunk)
            now = time.monotonic()
            if now - last_report >= 0.15:
                _progress(callback, "hashing", 0, total_frames, processed / total)
                last_report = now
    return digest.hexdigest()


def _dhash(frame):
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).reshape(-1)
    number = 0
    for bit in bits:
        number = (number << 1) | int(bit)
    return f"{number:016x}"


def _write_png(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise OSError(f"Could not encode image: {path.name}")
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(encoded.tobytes())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _save_candidate(session_dir, frame, index, seconds):
    candidate_id = f"f{index:09d}"
    relative = f"frames/{candidate_id}.png"
    _write_png(_inside(session_dir, relative), frame)
    return {"id": candidate_id, "frame_index": index, "time": float(seconds),
            "file": relative, "dhash": _dhash(frame)}


def _frame_time(capture, index, fps):
    seconds = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
    return float(seconds) if math.isfinite(seconds) and (seconds > 0 or index == 0) else index / fps


def extract_candidates(video_path, session_dir, ffprobe_exe=None,
                       cancel_event=None, on_progress=None, on_candidate=None):
    """Decode every frame, emitting saved candidates and cancellable progress.

    Callbacks run synchronously in the caller's thread. Cancellation returns a
    usable partial result, without fabricating a final frame. A canceled hash
    is represented by source.sha256=None. Existing session files are retained.
    """
    path = Path(video_path).expanduser().resolve()
    source = {**probe_video(path, ffprobe_exe), "path": str(path), "sha256": None}
    total, fps = source["frame_count"], source["fps"]
    candidates, seen = [], set()
    result = {"source": source, "candidates": candidates, "complete": False,
              "detection": copy.deepcopy(DETECTION), "decoded_frame_count": 0}
    source["sha256"] = _source_hash(path, cancel_event, on_progress, total)
    if _cancelled(cancel_event):
        _progress(on_progress, "cancelled", 0, total, 0)
        return result
    session = Path(session_dir).expanduser().resolve()
    session.mkdir(parents=True, exist_ok=True)
    _, capture = _open_video(path)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    previous, last_frame, last_index, last_seconds = None, None, -1, 0.0
    pending, elapsed = False, 0
    last_report = 0.0

    def save(frame, index, seconds):
        if index not in seen:
            candidate = _save_candidate(session, frame, index, seconds)
            seen.add(index)
            candidates.append(candidate)
            if on_candidate:
                on_candidate(copy.deepcopy(candidate))

    _progress(on_progress, "extracting", 0, total, 0)
    try:
        while not _cancelled(cancel_event):
            ok, frame = capture.read()
            if not ok:
                result["complete"] = last_index >= 0
                break
            index = last_index + 1
            seconds = _frame_time(capture, index, fps)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if previous is None:
                save(frame, index, seconds)
            else:
                difference = cv2.absdiff(gray, previous)
                _, difference = cv2.threshold(difference, 80, 255, cv2.THRESH_BINARY)
                difference = cv2.dilate(difference, kernel)
                changed_percent = cv2.countNonZero(difference) / float(gray.size) * 100
                if changed_percent >= 0.06 and not pending:
                    pending = True
                elif pending:
                    elapsed += 1
                if elapsed >= 85:
                    pending, elapsed = False, 0
                    save(frame, index, seconds)
            previous = gray
            last_frame, last_index, last_seconds = frame, index, seconds
            result["decoded_frame_count"] = index + 1
            now = time.monotonic()
            if now - last_report >= 0.15:
                _progress(on_progress, "extracting", index + 1, total,
                          (index + 1) / total if total else 0)
                last_report = now
        if result["complete"]:
            save(last_frame, last_index, last_seconds)
    finally:
        capture.release()
    if last_index < 0 and not _cancelled(cancel_event):
        raise ValueError("The video opened but contained no decodable frames.")
    stage = "complete" if result["complete"] else "cancelled"
    _progress(on_progress, stage, last_index + 1, total,
              1 if result["complete"] else ((last_index + 1) / total if total else 0))
    return result


def _nearest_timestamp_index(video_path, seconds, ffprobe_exe):
    """Use presentation timestamps for VFR input, if ffprobe is available."""
    if not ffprobe_exe:
        return None
    process = None
    try:
        process = subprocess.Popen(
            [str(ffprobe_exe), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(video_path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace", **_run_options(),
        )
        first, best, best_distance, index = None, None, math.inf, 0
        for line in process.stdout:
            value = line.strip().split(",", 1)[0]
            if not value:
                continue
            timestamp = float(value)
            if not math.isfinite(timestamp):
                return None
            if first is None:
                first = timestamp
            relative_time = timestamp - first
            distance = abs(relative_time - seconds)
            # Prefer the later frame for an exact tie, matching round-half-up.
            if distance <= best_distance:
                best, best_distance = (index, relative_time), distance
            if relative_time >= seconds:
                return best
            index += 1
        if process.wait() != 0:
            return None
        return best
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
            if process.stdout:
                process.stdout.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def add_frame(video_path, seconds, session_dir, ffprobe_exe=None):
    """Save the decoded frame nearest the requested source-relative time.

    ffprobe timestamps support variable frame rates. Without ffprobe the
    nearest index uses the reported average FPS. Seeking is checked; an
    inexact OpenCV frame seek falls back to sequential decoding.
    """
    seconds = float(seconds)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Frame time must be a finite, non-negative number.")
    metadata = probe_video(video_path, ffprobe_exe)
    path, capture = _open_video(video_path)
    try:
        nearest = _nearest_timestamp_index(path, seconds, ffprobe_exe)
        target = nearest[0] if nearest else int(math.floor(seconds * metadata["fps"] + 0.5))
        if metadata["frame_count"]:
            target = min(target, metadata["frame_count"] - 1)
        capture.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = capture.read()
        reported = int(round(capture.get(cv2.CAP_PROP_POS_FRAMES))) - 1
        if not ok or reported != target:
            capture.release()
            _, capture = _open_video(path)
            for index in range(target + 1):
                ok, frame = capture.read()
                if not ok:
                    raise ValueError(f"Could not decode frame {target}.")
        actual_time = nearest[1] if nearest else _frame_time(capture, target, metadata["fps"])
        return _save_candidate(session_dir, frame, target, actual_time)
    finally:
        capture.release()


def _read_image(path):
    pixels = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if pixels is None:
        raise ValueError(f"Cannot decode candidate image: {path.name}")
    return pixels


EXPORT_FILENAME_FORMAT = 'lecture_sequence_video_time_v2'


def lecture_filename_title(source):
    raw = Path(source['path']).stem if source.get('path') else source.get('title', 'lecture')
    raw = re.sub(r'\s+', '+', str(raw))
    raw = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', raw).strip('. ')
    return raw or 'lecture'


def filename_budget(folder):
    # Keep both the filename component and full path friendly to Windows apps.
    budget = min(180, 240 - len(str(Path(folder).resolve()).encode('utf-16-le'))//2 - 1)
    if budget < 32:
        raise ValueError('출력 폴더 경로가 너무 깁니다. 더 짧은 경로를 선택하세요.')
    return budget


def export_filename(sequence, seconds, title=None, max_units=180):
    seconds = float(seconds)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Candidate timestamp must be finite and nonnegative.')
    hours, remainder = divmod(int(seconds), 3600)
    minutes, second = divmod(remainder, 60)
    stamp = f'{minutes:02d}m{second:02d}s'
    if hours:
        stamp = f'{hours:02d}h' + stamp
    suffix = f'{sequence:04d}_{stamp}.png'
    if title is None:
        return suffix
    title = lecture_filename_title({'title': title})
    available = max_units - len(suffix) - 1
    if available < 8:
        raise ValueError('강의명을 넣을 파일명 공간이 부족합니다.')
    if len(title.encode('utf-16-le'))//2 > available:
        short_hash = hashlib.sha256(title.encode('utf-8')).hexdigest()[:6]
        title = title.encode('utf-16-le')[:(available-7)*2].decode('utf-16-le', errors='ignore') + '~' + short_hash
    return f'{title}_{suffix}'


def export_candidates(session_dir, candidates, selected_ids, export_parent,
                      source, metrics=None):
    """Copy the selected images into a new export directory plus a manifest.

    PNG inputs are copied byte-for-byte; other supported images are decoded
    and saved as lossless PNG, with that conversion recorded. The caller's
    candidate/source objects and all session files are left unchanged.
    """
    candidate_records = copy.deepcopy(list(candidates))
    by_id = {}
    for candidate in candidate_records:
        candidate_id = candidate["id"]
        if candidate_id in by_id:
            raise ValueError(f"Duplicate candidate ID: {candidate_id}")
        by_id[candidate_id] = candidate
    chosen = set(selected_ids)
    if not chosen:
        raise ValueError("Select at least one candidate to export.")
    missing = chosen - by_id.keys()
    if missing:
        raise ValueError(f"Unknown selected candidate IDs: {sorted(missing)}")
    selected = sorted((by_id[item] for item in chosen),
                      key=lambda item: (item["frame_index"], item["id"]))
    parent = Path(export_parent).expanduser().resolve()
    title = lecture_filename_title(source)
    budget = filename_budget(parent / 'slides-20000101-000000-00000000')
    filenames = [export_filename(i, c['time'], title, budget) for i, c in enumerate(selected, 1)]
    paths = []
    for candidate in selected:
        path = _inside(session_dir, candidate["file"])
        if not path.is_file():
            raise FileNotFoundError(f"Candidate image is missing: {candidate['file']}")
        _read_image(path)  # Validate before creating any export directory.
        paths.append(path)
    parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    while True:
        destination = parent / f"slides-{timestamp}-{uuid.uuid4().hex[:8]}"
        try:
            destination.mkdir()
            break
        except FileExistsError:
            continue
    incomplete = destination / ".incomplete"
    incomplete.write_text("Export is incomplete until manifest.json has been written.\n", encoding="utf-8")
    exports = []
    for sequence, (candidate, source_path) in enumerate(zip(selected, paths), 1):
        filename = filenames[sequence-1]
        target = _inside(destination, filename)
        pixels = _read_image(source_path)
        with source_path.open("rb") as handle:
            is_png = handle.read(8) == _PNG_SIGNATURE
        if is_png:
            shutil.copyfile(source_path, target)
            conversion = "copied_png"
        else:
            _write_png(target, pixels)
            conversion = "decoded_pixels_to_png"
        exports.append({
            "sequence": sequence, "candidate_id": candidate["id"],
            "frame_index": candidate["frame_index"], "time": candidate["time"],
            "file": filename, "source_file": candidate["file"],
            "conversion": conversion, "width": pixels.shape[1], "height": pixels.shape[0],
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        })
    manifest = {
        "schema_version": 1, "filename_format": EXPORT_FILENAME_FORMAT,
        "lecture_title": title,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": copy.deepcopy(source), "candidates": candidate_records,
        "selected_ids": [item["id"] for item in selected], "exports": exports,
        "metrics": copy.deepcopy(metrics),
    }
    manifest_path = _inside(destination, "manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    incomplete.unlink()
    return destination
