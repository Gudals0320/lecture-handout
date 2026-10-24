"""Mechanical helpers; image selection and section matching remain human/agent decisions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
LINK = re.compile(rb'!\[[^\]\r\n]*\]\((\./images/[^)\r\n]+)\)')
BLOCK = re.compile(
    rb'(?m)^<!-- lecture-images:start section=(\d+) -->\r?\n.*?'
    rb'^<!-- lecture-images:end section=\1 -->\r?\n', re.S)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    return digest(path.read_bytes())


def safe_path(run, relative):
    relative = Path(relative)
    require(not relative.is_absolute(), f'Relative run path required: {relative}')
    path = (run / relative).resolve()
    require(path.is_relative_to(run.resolve()), f'Path leaves the selected run: {relative}')
    return path


def lecture_path(value):
    path = Path(value)
    path = (ROOT / 'lectures' / path).resolve() if not path.is_absolute() else path.resolve()
    require(path.parent == (ROOT / 'lectures').resolve(), 'Select one lecture directly inside lectures/.')
    require(path.is_dir(), f'Lecture folder not found: {path}')
    return path


def relative(run, path):
    return path.resolve().relative_to(run.resolve()).as_posix()


def metadata(run, name):
    return safe_path(run, Path('work') / name)


def read_json(path, fallback=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else fallback


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def write_json(path, data):
    atomic_write(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def strip_blocks(data):
    stripped = BLOCK.sub(b'', data)
    require(b'<!-- lecture-images:' not in stripped, 'Damaged or unmatched managed image markers.')
    return stripped


def headings(data):
    """Actual ATX H2 headings, ignoring fenced code blocks; offsets retain original bytes."""
    result, offset, fence = [], 0, None
    for line in data.splitlines(keepends=True):
        bare = line.rstrip(b'\r\n')
        bom_size = 3 if offset == 0 and bare.startswith(b'\xef\xbb\xbf') else 0
        if bom_size:
            bare = bare[bom_size:]
        match = re.match(rb'^ {0,3}(`{3,}|~{3,})(.*)$', bare)
        if match:
            token, rest = match.groups()
            if fence is None:
                fence = token
            elif token[:1] == fence[:1] and len(token) >= len(fence) and not rest.strip():
                fence = None
        elif fence is None and re.match(rb'^ {0,3}##[ \t]+\S', bare):
            result.append({'section': len(result) + 1, 'heading': bare.decode('utf-8'),
                           'start': offset + bom_size, 'end': offset + len(line)})
        offset += len(line)
    return result


def input_files(run, suffixes):
    return sorted(p for p in run.rglob('*') if p.is_file() and p.suffix.lower() in suffixes
                  and not {'output', 'backups', 'previews', 'tmp'}.intersection(p.relative_to(run).parts))


def pdf_reader(path):
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ValueError('pypdf is required. Use the bundled workspace Python/dependencies.') from error
    reader = PdfReader(path)
    require(not reader.is_encrypted or reader.decrypt(''), f'PDF needs a password: {path.name}')
    return reader


def validate_image(path):
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError('Pillow is required. Use the bundled workspace Python/dependencies.') from error
    with Image.open(path) as image:
        size = image.size
        image.verify()
    require(min(size) > 0, f'Empty image: {path}')
    return size


def inspect_lecture(run):
    documents = []
    for path in input_files(run, {'.md'}):
        data = path.read_bytes()
        plain = strip_blocks(data)
        hs = headings(plain)
        for i, heading in enumerate(hs):
            end = hs[i+1]['start'] if i+1 < len(hs) else len(plain)
            section = plain[heading['end']:end].decode('utf-8')
            heading['timestamps'] = re.findall(r'\[\d{2}:\d{2}:\d{2}[^\]\n]*\]', section)
            heading.pop('start'); heading.pop('end')
        documents.append({'markdown': relative(run, path), 'sha256': digest(data),
                          'headings': hs, 'existing_local_images': len(LINK.findall(data)),
                          'managed_blocks': len(BLOCK.findall(data))})
    pdfs = []
    for path in input_files(run, {'.pdf'}):
        reader = pdf_reader(path)
        pdfs.append({'pdf': relative(run, path), 'sha256': file_hash(path),
                     'page_count': len(reader.pages), 'pages': [
                         {'page': i+1, 'text': page.extract_text() or ''}
                         for i, page in enumerate(reader.pages)]})
    manifests = []
    for path in input_files(run, {'.json'}):
        if path.name != 'manifest.json':
            continue
        manifest = read_json(path)
        exports = manifest.get('exports', [])
        manifests.append({'manifest': relative(run, path), 'exports': len(exports),
                          'missing_export_names': [e.get('file') for e in exports
                                                   if not (path.parent / e.get('file', '')).is_file()]})
    assets = [relative(run, p) for p in input_files(run, IMAGE_EXTENSIONS)]
    videos = [relative(run, p) for p in input_files(run, {'.mp4', '.mkv', '.mov', '.avi', '.webm'})]
    audio = [relative(run, p) for p in input_files(run, {'.mp3', '.m4a', '.wav', '.flac', '.ogg', '.aac', '.opus', '.wma'})]
    # Raw transcripts: exported TXT in input/ or TXT produced by the transcribe stage in work/transcribe/.
    transcripts = [relative(run, p) for p in input_files(run, {'.txt'})]
    return {'lecture': run.name, 'documents': documents, 'pdfs': pdfs, 'images': assets, 'manifests': manifests,
            'videos': videos, 'audio': audio, 'raw_transcripts': transcripts}


def renderer_path(explicit):
    if explicit:
        path = Path(explicit).resolve()
        require(path.is_file(), f'Renderer not found: {path}')
        return str(path)
    configured = os.environ.get('LECTURE_PDFTOPPM')
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which('pdftoppm')
    if found:
        return found
    raise ValueError('Poppler pdftoppm not found. Install Poppler and put it on PATH, '
                     'set LECTURE_PDFTOPPM to the executable, or pass --renderer.')


def extract_pdf(run, pdf_name, width, prefix, renderer):
    require(400 <= width <= 10000, 'Width must be between 400 and 10000 pixels.')
    pdf = safe_path(run, pdf_name)
    require(pdf.is_file() and pdf.suffix.lower() == '.pdf', 'Select an existing PDF in this run.')
    source_hash = file_hash(pdf)
    count = len(pdf_reader(pdf).pages)
    require(count > 0, 'PDF has no pages.')
    if prefix is None:
        slug = re.sub(r'[^a-z0-9_-]+', '-', pdf.stem.lower()).strip('-')[:36] or 'lecture'
        prefix = f'pdf-{slug}-{source_hash[:8]}-w{width}'
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}', prefix), 'Use a short ASCII filename prefix.')
    images = safe_path(run, 'work/pdf-pages')
    exports_path = metadata(run, 'pdf_exports.json')
    exports = read_json(exports_path, {})
    key = relative(run, pdf)
    previous = exports.get(key)
    if previous and previous['sha256'] == source_hash and previous['width'] == width and previous['prefix'] == prefix:
        if all(safe_path(run, page['image']).is_file() and
               file_hash(safe_path(run, page['image'])) == page['sha256'] for page in previous['pages']):
            return {'status': 'reused', **previous}
    temporary_root = metadata(run, 'tmp')
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pdf-', dir=temporary_root) as temporary:
        temp = Path(temporary).resolve()
        require(temp.is_relative_to(run.resolve()), 'Extraction directory leaves the run.')
        subprocess.run([renderer_path(renderer), '-scale-to', str(width), '-png', str(pdf), str(temp / 'page')],
                       check=True, capture_output=True)
        pages = []
        for page in range(1, count+1):
            sources = [p for p in temp.glob('page-*.png') if int(p.stem.rsplit('-', 1)[1]) == page]
            require(len(sources) == 1, f'Missing or duplicate rendered PDF page: {page}')
            source = sources[0]
            size = validate_image(source)
            require(max(size) == width, f'Unexpected rendering size on page {page}: {size}')
            destination = safe_path(run, f'work/pdf-pages/{prefix}-p{page:03d}.png')
            image_hash = file_hash(source)
            require(not destination.exists() or file_hash(destination) == image_hash,
                    f'Refusing to overwrite a different image: {destination.name}')
            pages.append({'page': page, 'image': relative(run, destination), 'sha256': image_hash,
                          'width': size[0], 'height': size[1], '_source': str(source)})
        require(len(list(temp.glob('page-*.png'))) == count, 'Unexpected PDF render count.')
        images.mkdir(parents=True, exist_ok=True)
        for page in pages:
            destination = safe_path(run, page['image'])
            if not destination.exists():
                shutil.copy2(page.pop('_source'), destination)
            else:
                page.pop('_source')
    record = {'pdf': key, 'sha256': source_hash, 'page_count': count, 'width': width,
              'prefix': prefix, 'pages': pages}
    exports[key] = record
    write_json(exports_path, exports)
    return {'status': 'rendered', **record}


def contact_sheet(run, source_name, columns, per_sheet):
    from PIL import Image, ImageDraw
    require(1 <= columns <= 4 and 1 <= per_sheet <= 24, 'Invalid contact sheet layout.')
    source = safe_path(run, source_name)
    require(source.is_dir(), 'Contact sheet source must be an image folder in this run.')
    files = input_files(source, IMAGE_EXTENSIONS)
    require(files, 'No images found for contact sheets.')
    output = metadata(run, 'previews')
    output.mkdir(parents=True, exist_ok=True)
    results = []
    source_id = digest(relative(run, source).encode())[:8]
    for batch in range(0, len(files), per_sheet):
        picks = files[batch:batch+per_sheet]
        sheet = Image.new('RGB', (640*columns, 510*((len(picks)+columns-1)//columns)), '#dddddd')
        draw = ImageDraw.Draw(sheet)
        for i, path in enumerate(picks):
            with Image.open(path) as original:
                thumbnail = original.convert('RGB')
            thumbnail.thumbnail((630, 460))
            x, y = i % columns * 640, i // columns * 510
            sheet.paste(thumbnail, (x, y))
            label = f'{batch+i+1}: {path.name}'
            draw.text((x+5, y+465), label[:75], fill='black')
        destination = output / f'{source_id}-sheet-{batch//per_sheet+1:03d}.jpg'
        sheet.save(destination, quality=90)
        results.append(relative(run, destination))
    return {'sheets': results, 'image_count': len(files)}


def check_coverage(run, policies, exports, pages_used):
    pdfs = {relative(run, p): p for p in input_files(run, {'.pdf'})}
    require({p['pdf'] for p in policies} == set(pdfs), 'Declare a coverage policy for every PDF in this run.')
    require(len(policies) == len(pdfs), 'Duplicate PDF coverage policies.')
    checked = []
    for policy in policies:
        key = policy['pdf']
        require(policy['mode'] in {'all', 'selected'}, f'Unknown PDF coverage mode: {key}')
        source_hash = file_hash(pdfs[key])
        count = len(pdf_reader(pdfs[key]).pages)
        if policy['mode'] == 'all':
            require(key in exports and exports[key]['sha256'] == source_hash,
                    f'Render the current PDF before applying all-page coverage: {key}')
            missing = set(range(1, count+1)) - {page for pdf, page in pages_used if pdf == key}
            require(not missing, f'Unlinked PDF pages in {key}: {sorted(missing)}')
        else:
            require(policy.get('reason', '').strip(), f'Explain selected-page policy: {key}')
        checked.append({**policy, 'sha256': source_hash, 'page_count': count})
    return checked

