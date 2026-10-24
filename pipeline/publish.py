"""Build a portable output from immutable input and a reviewed work/mapping.json."""
import re
import shutil
from pathlib import Path
from . import assemble as a


def legacy_body(data):
    return re.sub(rb'(?m)^!\[[^\]]*\]\(\./images/[^)]+\)\r?\n\r?\n', b'', data)


def apply(lecture, plan_name='work/mapping.json'):
    plan_path = a.safe_path(lecture, plan_name)
    plan = a.read_json(plan_path)
    a.require(plan and plan.get('version') == 2 and plan.get('lecture') == lecture.name, 'Invalid mapping version or lecture.')
    state_path = a.metadata(lecture, 'state.json')
    previous = a.read_json(state_path, {})
    plan_hash = a.file_hash(plan_path)
    if previous.get('plan_sha256') == plan_hash:
        verify(lecture)
        return {'status': 'already_applied', **verify(lecture)}
    exports = a.read_json(a.metadata(lecture, 'pdf_exports.json'), {})
    pdf_images = {p['image']: (key, p['page']) for key, e in exports.items() for p in e['pages']}
    documents, assets, updates, pages_used = {}, {}, [], set()
    a.require(plan.get('documents'), 'Mapping has no documents.')
    for document in plan['documents']:
        source = a.safe_path(lecture, document['markdown'])
        a.require(source.is_file() and source.suffix.lower() == '.md' and
                  source.is_relative_to(lecture/'work'), 'Use a refined Markdown under work/.')
        base = source.read_bytes()
        a.require(a.digest(base) == document['expected_sha256'], 'Transcript changed after review; inspect and remap.')
        a.require(not a.LINK.search(base) and b'<!-- lecture-images:' not in base, 'Transcript must not contain assembled images.')
        output_name = document.get('output', f'output/{lecture.name}.md')
        output = a.safe_path(lecture, output_name)
        a.require(output.parent == lecture/'output' and output.suffix.lower() == '.md', 'Output Markdown must be directly under output/.')
        key = a.relative(lecture, output)
        a.require(key not in documents, 'Duplicate output document.')
        old = previous.get('documents', {}).get(key)
        if output.exists():
            a.require(old and a.file_hash(output) == old['output_sha256'], 'Output was edited or is unmanaged; preserve and review it first.')
        before = output.read_bytes() if output.exists() else None
        hs = a.headings(base)
        newline = b'\r\n' if b'\r\n' in base else b'\n'
        sections, insertions, references = set(), {}, []
        for section in document['sections']:
            number = section['section']
            a.require(type(number) is int and 1 <= number <= len(hs) and number not in sections, 'Invalid or duplicate H2 number.')
            sections.add(number)
            heading = hs[number-1]
            a.require(section['heading'] == heading['heading'], 'H2 title differs from the reviewed mapping.')
            links = []
            groups = {}
            for item in section['images']:
                image = a.safe_path(lecture, item['source'])
                a.require(image.is_file() and image.suffix.lower() in a.IMAGE_EXTENSIONS, f'Image missing: {image}')
                a.validate_image(image)
                name = item.get('name', image.name)
                a.require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', name) and
                          Path(name).suffix.lower() == image.suffix.lower(), 'Use a short ASCII image name with the original extension.')
                alt, reason = item['alt'], item['reason']
                a.require(alt.strip() and reason.strip() and not any(c in alt for c in '\r\n[]'), 'Supply an alt and a content-based reason.')
                destination = a.safe_path(lecture, f'output/images/{name}')
                digest = a.file_hash(image)
                a.require(not destination.exists() or a.file_hash(destination) == digest, f'Image collision: {name}')
                image_key = a.relative(lecture, destination)
                page = pdf_images.get(a.relative(lecture, image))
                if not page:
                    page = previous.get('assets', {}).get(a.relative(lecture, image), {}).get('pdf_page')
                if page:
                    page = tuple(page)
                    export_page = next(p for p in exports[page[0]]['pages'] if p['page'] == page[1])
                    a.require(digest == export_page['sha256'], 'PDF page image was modified.')
                    pages_used.add(page)
                if image_key in assets:
                    a.require(assets[image_key]['sha256'] == digest and assets[image_key]['pdf_page'] == page,
                              'Different sources/pages need distinct destination names.')
                assets[image_key] = {'source': a.relative(lecture, image), 'sha256': digest, 'pdf_page': page}
                offset = heading['end']
                if 'before_paragraph' in item or 'after_paragraph' in item:
                    after = 'after_paragraph' in item
                    a.require(not (after and 'before_paragraph' in item), 'Use either before_paragraph or after_paragraph.')
                    anchor = item['after_paragraph' if after else 'before_paragraph'].encode('utf-8')
                    end = hs[number]['start'] if number < len(hs) else len(base)
                    body = base[heading['end']:end]
                    a.require(anchor and body.count(anchor) == 1, 'Paragraph anchor must occur exactly once in its H2.')
                    offset = heading['end'] + body.index(anchor)
                    a.require(base[offset-2*len(newline):offset] == newline*2 and
                              (offset+len(anchor) == len(base) or
                               base[offset+len(anchor):offset+len(anchor)+len(newline)] == newline),
                              'Anchor must be a complete paragraph at a paragraph boundary.')
                    if after:
                        # After the paragraph and its blank line, e.g. closing slides at the end of an H2.
                        offset += len(anchor) + len(newline)
                        a.require(offset <= end, 'Paragraph after anchor must end with a newline.')
                        if base[offset:offset+len(newline)] == newline:
                            offset += len(newline)
                references.append({'section': number, 'image': image_key, 'reason': reason, 'body_offset': offset})
                link = f'![{alt}](./images/{name})'.encode('utf-8')
                a.require(link not in links, 'Duplicate image within the same section.')
                links.append(link)
                groups.setdefault(offset, []).append(link)
            for offset, group in groups.items():
                a.require(base[heading['end']-1:heading['end']] == b'\n', 'H2 has no terminating newline.')
                insertions[offset] = (f'<!-- lecture-images:start section={number} -->'.encode() + newline + newline +
                    (newline+newline).join(group) + newline+newline + f'<!-- lecture-images:end section={number} -->'.encode() + newline)
        updated = base
        for offset, block in sorted(insertions.items(), reverse=True):
            updated = updated[:offset] + block + updated[offset:]
        a.require(a.strip_blocks(updated) == base, 'Original transcript changed during assembly.')
        documents[key] = {'mode': 'managed', 'source_markdown': a.relative(lecture, source),
                          'source_sha256': a.digest(base), 'output_sha256': a.digest(updated),
                          'body_sha256': a.digest(base), 'image_count': len(references), 'references': references}
        updates.append((output, before, updated))
    a.require(set(previous.get('documents', {})).issubset(documents), 'A refresh must include all existing output documents.')
    policies = a.check_coverage(lecture, plan.get('pdf_coverage', []), exports, pages_used)
    state = {'version': 2, 'lecture': lecture.name, 'plan_sha256': plan_hash, 'documents': documents,
             'assets': assets, 'pdf_coverage': policies}
    # Preserve all inputs, including the MP4/TXT, even if they are not directly linked.
    state['input_hashes'] = {a.relative(lecture, p): a.file_hash(p) for p in (lecture/'input').rglob('*') if p.is_file()}
    for output, before, updated in updates:
        if before is not None:
            backup = a.metadata(lecture, f'backups/{a.digest(output.name.encode())[:8]}-{a.digest(before)[:12]}.md')
            if not backup.exists():
                a.atomic_write(backup, before)
    a.safe_path(lecture, 'output/images').mkdir(parents=True, exist_ok=True)
    for key, asset in assets.items():
        destination = a.safe_path(lecture, key)
        if not destination.exists():
            shutil.copy2(a.safe_path(lecture, asset['source']), destination)
        a.require(a.file_hash(destination) == asset['sha256'], 'Image copy failed verification.')
    written = []
    try:
        for output, before, updated in updates:
            a.require((output.read_bytes() if output.exists() else None) == before, 'Output changed during publication.')
            written.append((output, before))
            if before != updated:
                a.atomic_write(output, updated)
        # State is the completion marker; restore outputs if committing it fails.
        a.write_json(state_path, state)
    except Exception:
        for output, before in written:
            if before is None:
                output.unlink(missing_ok=True)
            else:
                a.atomic_write(output, before)
        raise
    return {'status': 'applied', **verify(lecture)}


def verify(lecture):
    state = a.read_json(a.metadata(lecture, 'state.json'))
    a.require(state and state.get('lecture') == lecture.name, 'No validated state for this lecture.')
    used = set()
    for key, record in state['documents'].items():
        output = a.safe_path(lecture, key)
        data = output.read_bytes()
        a.require(a.digest(data) == record['output_sha256'], f'Output changed: {key}')
        base = legacy_body(data) if record.get('mode') == 'imported' else a.strip_blocks(data)
        source = a.safe_path(lecture, record['source_markdown'])
        a.require(source.read_bytes() == base and a.digest(base) == record['body_sha256'], 'Output body differs from refined transcript.')
        links = a.LINK.findall(data)
        a.require(len(links) == record['image_count'], 'Output image count differs from mapping.')
        actual = [a.relative(lecture, (output.parent/p.decode()).resolve()) for p in links]
        a.require(sorted(actual) == sorted(r['image'] for r in record['references']), 'Output image references changed.')
        expected_sections = {r['section'] for r in record['references']}
        positioned = all('body_offset' in r for r in record['references'])
        if record.get('mode') != 'imported':
            expected_count = len({r['body_offset'] for r in record['references']}) if positioned else len(expected_sections)
            a.require(len(a.BLOCK.findall(data)) == expected_count, 'Managed block count differs.')
            if positioned:
                removed = 0
                base_hs = a.headings(base)
                for block in a.BLOCK.finditer(data):
                    offset = block.start() - removed
                    number = int(block.group(1))
                    refs = [r for r in record['references'] if r['body_offset'] == offset]
                    a.require(refs and all(r['section'] == number for r in refs), 'Image block moved from its reviewed position.')
                    h = base_hs[number-1]
                    end = base_hs[number]['start'] if number < len(base_hs) else len(base)
                    a.require(h['end'] <= offset <= end, 'Image block is outside its H2.')
                    block_images = [a.relative(lecture, (output.parent/p.decode()).resolve()) for p in a.LINK.findall(block.group())]
                    a.require(block_images == [r['image'] for r in refs], 'Image order or position differs from mapping.')
                    removed += block.end() - block.start()
        hs = a.headings(data)
        for i, heading in enumerate(hs):
            end = hs[i+1]['start'] if i+1 < len(hs) else len(data)
            section = data[heading['end']:end]
            if record.get('mode') == 'imported':
                section = section.lstrip(b'\r\n')
                count = 0
                for line in section.splitlines():
                    if not line.strip(): continue
                    if a.LINK.fullmatch(line): count += 1
                    else: break
                a.require(count == sum(r['section'] == heading['section'] for r in record['references']), 'Imported images are not immediately below their H2.')
            elif not positioned and heading['section'] in expected_sections:
                match = a.BLOCK.match(data, heading['end'])
                a.require(match and int(match.group(1)) == heading['section'], 'Image block is not immediately below its H2.')
    for key, asset in state['assets'].items():
        destination, source = a.safe_path(lecture, key), a.safe_path(lecture, asset['source'])
        a.require(destination.is_file() and a.file_hash(destination) == asset['sha256'], f'Linked image changed: {key}')
        a.require(source.is_file() and a.file_hash(source) == asset['sha256'], f'Source image changed: {asset["source"]}')
        a.validate_image(destination)
        if asset.get('pdf_page'): used.add(tuple(asset['pdf_page']))
    for key, digest in state.get('input_hashes', {}).items():
        a.require(a.file_hash(a.safe_path(lecture, key)) == digest, f'Input changed since validation: {key}')
    for policy in state['pdf_coverage']:
        a.require(a.file_hash(a.safe_path(lecture, policy['pdf'])) == policy['sha256'], 'Source PDF changed.')
    a.check_coverage(lecture, state['pdf_coverage'], a.read_json(a.metadata(lecture, 'pdf_exports.json'), {}), used)
    report = {'lecture': lecture.name, 'documents': {k:v['image_count'] for k,v in state['documents'].items()},
              'unique_images': len(state['assets']), 'linked_pdf_pages': len(used), 'validation': 'passed'}
    a.write_json(a.metadata(lecture, 'validation.json'), report)
    return report
