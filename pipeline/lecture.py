"""Command-line entry point for one named lecture; no run/latest/history layer."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import assemble as a
from pipeline import publish
from pipeline import transcribe


def initialize(name):
    path = Path(name)
    a.require(path.name == name and name not in {'.','..'} and not any(c in name for c in '<>:"/\\|?*'), 'Use one lecture folder name.')
    base = (a.ROOT/'lectures').resolve()
    lecture = (base/name).resolve()
    a.require(lecture.parent == base, 'Lecture path leaves lectures/.')
    for directory in ['input','work','output']:
        a.safe_path(lecture, directory).mkdir(parents=True, exist_ok=True)
    return lecture


def prepare(lecture, renderer=None, ffprobe=None):
    """Prepare deterministic artifacts; return remaining AI refinement/mapping work."""
    inventory = a.inspect_lecture(lecture)
    a.write_json(a.metadata(lecture, 'inventory.json'), inventory)
    tasks, generated = [], []
    transcript = lecture/'work/transcript.md'
    if not transcript.exists():
        md_inputs = list((lecture/'input').glob('*.md'))
        if len(md_inputs) == 1 and not inventory['raw_transcripts']:
            a.require(not a.LINK.search(md_inputs[0].read_bytes()), 'Input Markdown is already illustrated; review it before reuse.')
            a.atomic_write(transcript, md_inputs[0].read_bytes())
        elif not inventory['raw_transcripts'] and not md_inputs and (inventory['audio'] or inventory['videos']):
            tasks.append({'stage':'transcribe','media':inventory['audio'] or inventory['videos'],
                          'instructions':'docs/transcription.md',
                          'command':'lecture.py transcribe <lecture> --media <file> --provider whisper|soniox',
                          'or':'drop an exported TXT in input/ (provider external)','output':'work/transcribe/'})
        else:
            tasks.append({'stage':'refine_transcript','prompt':'prompts/audioscript-refiner-1.5.3.md',
                          'inputs':inventory['raw_transcripts'] or [a.relative(lecture,p) for p in md_inputs],
                          'output':'work/transcript.md'})
    for pdf in inventory['pdfs']:
        generated.append(a.extract_pdf(lecture, pdf['pdf'], 2400, None, renderer))
    for video in inventory['videos']:
        from pipeline.videocap.bridge import capture
        generated.append(capture(lecture, video, ffprobe=ffprobe))
    tasks.append({'stage':'review_and_map','instructions':'docs/matching.md','output':'work/mapping.json'})
    report = {'lecture':lecture.name,'prepared':generated,'remaining_content_work':tasks}
    a.write_json(a.metadata(lecture,'prepare.json'),report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ['init','inspect','prepare','transcribe','capture','extract-pdf','contact-sheet','apply','verify']:
        p = sub.add_parser(command)
        p.add_argument('lecture', help='Folder name under lectures/')
        if command == 'inspect': p.add_argument('--output', action='store_true', help='Save work/inventory.json')
        if command == 'transcribe':
            p.add_argument('--media', help='Audio or video under input/ (not needed for --provider external)')
            p.add_argument('--provider', choices=list(transcribe.PROVIDERS), default='whisper')
            p.add_argument('--language', help='ISO code such as ko or en; default lets the recognizer detect it')
            p.add_argument('--model', default='large-v3-turbo', help='faster-whisper model name or path')
            p.add_argument('--device', default='auto', help='faster-whisper device: auto, cpu, cuda')
            p.add_argument('--compute-type', default='default', help='faster-whisper compute type, e.g. int8, float16')
            p.add_argument('--no-pdf-terms', action='store_true', help='Soniox: do not send PDF vocabulary as context')
            p.add_argument('--ffmpeg', help='ffmpeg executable; default: LECTURE_FFMPEG or PATH')
            p.add_argument('--api-key', help='Soniox key; default: SONIOX_API_KEY')
        if command in {'prepare','extract-pdf'}: p.add_argument('--renderer')
        if command in {'prepare','capture'}: p.add_argument('--ffprobe')
        if command == 'capture':
            p.add_argument('--video', required=True)
            p.add_argument('--threshold', type=int, default=8)
        if command == 'extract-pdf':
            p.add_argument('--pdf', required=True)
            p.add_argument('--width', type=int, default=2400)
            p.add_argument('--prefix')
        if command == 'contact-sheet':
            p.add_argument('--source', required=True)
            p.add_argument('--columns', type=int, default=3)
            p.add_argument('--per-sheet', type=int, default=12)
        if command == 'apply': p.add_argument('--plan', default='work/mapping.json')
    args = parser.parse_args()
    lecture = initialize(args.lecture) if args.command == 'init' else a.lecture_path(args.lecture)
    if args.command == 'init': result = {'lecture':lecture.name,'folders':['input','work','output']}
    elif args.command == 'inspect':
        result = a.inspect_lecture(lecture)
        if args.output: a.write_json(a.metadata(lecture,'inventory.json'),result)
    elif args.command == 'prepare': result = prepare(lecture,args.renderer,args.ffprobe)
    elif args.command == 'transcribe':
        def progress(info): print(json.dumps(info,ensure_ascii=False), file=sys.stderr, flush=True)
        result = transcribe.transcribe(lecture,args.media,args.provider,args.language,args.model,args.device,
                                       args.compute_type,not args.no_pdf_terms,args.ffmpeg,args.api_key,progress)
    elif args.command == 'capture':
        from pipeline.videocap.bridge import capture
        def progress(info): print(f"{info['stage']}: {info['progress']:.0%}", file=sys.stderr, flush=True)
        result = capture(lecture,args.video,args.threshold,args.ffprobe,progress)
    elif args.command == 'extract-pdf': result = a.extract_pdf(lecture,args.pdf,args.width,args.prefix,args.renderer)
    elif args.command == 'contact-sheet': result = a.contact_sheet(lecture,args.source,args.columns,args.per_sheet)
    elif args.command == 'apply': result = publish.apply(lecture,args.plan)
    else: result = publish.verify(lecture)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try: main()
    except (ValueError,OSError,ImportError) as error:
        print(f'ERROR: {error}',file=sys.stderr)
        sys.exit(1)
