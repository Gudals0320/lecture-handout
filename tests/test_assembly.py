import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PIL import Image
from pypdf import PdfWriter
from pipeline import assemble as a, publish
from pipeline.lecture import prepare

class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='.lecture-test-',dir=Path(__file__).parent)
        self.root=Path(self.tmp.name).resolve();self.old=a.ROOT;a.ROOT=self.root
        self.lecture=self.root/'lectures/test-lecture'
        for d in ['input','work','output']:(self.lecture/d).mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(80,50),'red').save(self.lecture/'input/a.png')
        Image.new('RGB',(80,50),'blue').save(self.lecture/'input/b.png')
        self.base=b'## Same\r\n\r\nBody $x^2$.\r\n\r\n```python\r\n## fake\r\n```\r\n\r\n## Same\r\n\r\n[00:01:00-00:03:00]\r\nSecond.\r\n'
        (self.lecture/'work/transcript.md').write_bytes(self.base)
    def tearDown(self):
        a.ROOT=self.old
        self.assertTrue(self.root.is_relative_to(Path(__file__).resolve().parent));self.tmp.cleanup()
    def mapping(self,items=None,section=1,coverage=None):
        base=(self.lecture/'work/transcript.md').read_bytes();heading=a.headings(base)[section-1]['heading']
        plan={'version':2,'lecture':self.lecture.name,'pdf_coverage':coverage or [],'documents':[{'markdown':'work/transcript.md','expected_sha256':a.digest(base),'sections':[{'section':section,'heading':heading,'images':items if items is not None else [{'source':'input/a.png','alt':'Example','reason':'Matches the example'}]}]}]}
        a.write_json(self.lecture/'work/mapping.json',plan);return plan
    def output(self):return self.lecture/'output/test-lecture.md'
    def test_preservation_duplicate_headings_and_noop(self):
        self.mapping(section=2);publish.apply(self.lecture)
        out=self.output().read_bytes();self.assertEqual(a.strip_blocks(out),self.base)
        self.assertEqual(len(a.headings(self.base)),2)
        self.assertEqual(publish.apply(self.lecture)['status'],'already_applied')
        self.assertEqual(self.output().read_bytes(),out)
        self.assertEqual((self.lecture/'work/transcript.md').read_bytes(),self.base)
    def test_changed_mapping_replaces_images(self):
        self.mapping();publish.apply(self.lecture)
        self.mapping([{'source':'input/b.png','alt':'New','reason':'New example'}]);publish.apply(self.lecture)
        out=self.output().read_bytes();self.assertEqual(len(a.LINK.findall(out)),1)
        self.assertIn(b'images/b.png',out);self.assertEqual(a.strip_blocks(out),self.base)
    def test_inline_placement_preserves_body_and_noop(self):
        self.base=b'## Topic\r\n\r\nIntroduction.\r\n\r\nSecond slide example.\r\n\r\nConclusion.\r\n'
        (self.lecture/'work/transcript.md').write_bytes(self.base)
        self.mapping([{'source':'input/a.png','alt':'First','reason':'Overview'},
                      {'source':'input/b.png','alt':'Second','reason':'Example','before_paragraph':'Second slide example.'}])
        publish.apply(self.lecture);out=self.output().read_bytes()
        self.assertEqual(a.strip_blocks(out),self.base)
        self.assertLess(out.index(b'Introduction.'),out.index(b'images/b.png'))
        self.assertLess(out.index(b'images/b.png'),out.index(b'Second slide example.'))
        self.assertEqual(len(a.BLOCK.findall(out)),2)
        self.assertEqual(publish.apply(self.lecture)['status'],'already_applied')
        self.assertEqual(self.output().read_bytes(),out)
    def test_invalid_inline_anchor_preserves_output(self):
        self.mapping();publish.apply(self.lecture);out=self.output().read_bytes()
        self.mapping([{'source':'input/b.png','alt':'Example','reason':'Example','before_paragraph':'Missing paragraph.'}])
        with self.assertRaisesRegex(ValueError,'exactly once'):publish.apply(self.lecture)
        self.assertEqual(self.output().read_bytes(),out)
    def test_inline_final_paragraph_without_newline(self):
        base=b'## Topic\n\nIntroduction.\n\nLast paragraph.'
        (self.lecture/'work/transcript.md').write_bytes(base)
        self.mapping([{'source':'input/a.png','alt':'Last','reason':'Closing','before_paragraph':'Last paragraph.'}])
        publish.apply(self.lecture)
        self.assertEqual(a.strip_blocks(self.output().read_bytes()),base)
        self.assertEqual(publish.verify(self.lecture)['validation'],'passed')
    def test_after_paragraph_places_images_at_section_end(self):
        base=b'## Topic\n\nIntroduction.\n\nClosing remarks.\n\n## Next\n\nMore.\n\n## Last\n\nFinal words.\n'
        (self.lecture/'work/transcript.md').write_bytes(base)
        plan=self.mapping([{'source':'input/a.png','alt':'Closing','reason':'Closing slide','after_paragraph':'Closing remarks.'}])
        plan['documents'][0]['sections'].append({'section':3,'heading':'## Last','images':[
            {'source':'input/b.png','alt':'Final','reason':'Final slide','after_paragraph':'Final words.'}]})
        a.write_json(self.lecture/'work/mapping.json',plan)
        publish.apply(self.lecture);out=self.output().read_bytes()
        self.assertEqual(a.strip_blocks(out),base)
        self.assertLess(out.index(b'Closing remarks.'),out.index(b'images/a.png'))
        self.assertLess(out.index(b'images/a.png'),out.index(b'## Next'))
        self.assertTrue(out.rstrip().endswith(b'<!-- lecture-images:end section=3 -->'))
        self.assertEqual(publish.verify(self.lecture)['validation'],'passed')
    def test_collision_keeps_existing_output(self):
        self.mapping();publish.apply(self.lecture);out=self.output().read_bytes()
        self.mapping([{'source':'input/b.png','name':'a.png','alt':'Collision','reason':'Example'}])
        with self.assertRaisesRegex(ValueError,'collision'):publish.apply(self.lecture)
        self.assertEqual(self.output().read_bytes(),out)
    def test_transcript_edit_after_mapping_is_not_overwritten(self):
        self.mapping();new=self.base+b'User note\r\n';(self.lecture/'work/transcript.md').write_bytes(new)
        with self.assertRaisesRegex(ValueError,'changed after review'):publish.apply(self.lecture)
        self.assertEqual((self.lecture/'work/transcript.md').read_bytes(),new);self.assertFalse(self.output().exists())
    def test_output_user_edits_are_not_overwritten(self):
        self.mapping();publish.apply(self.lecture);changed=self.output().read_bytes()+b'User note'
        self.output().write_bytes(changed)
        self.mapping([{'source':'input/b.png','alt':'New','reason':'Changed example'}])
        with self.assertRaisesRegex(ValueError,'Output was edited'):publish.apply(self.lecture)
        self.assertEqual(self.output().read_bytes(),changed)
    def test_path_cannot_leave_lecture(self):
        with self.assertRaises(ValueError):a.safe_path(self.lecture,'../another/input/a.png')
        with self.assertRaises(ValueError):a.lecture_path('../test-lecture')
        self.assertEqual(a.lecture_path('test-lecture'),self.lecture)
    def test_bom_and_corrupt_markers(self):
        original=b'\xef\xbb\xbf'+self.base;(self.lecture/'work/transcript.md').write_bytes(original)
        self.mapping();publish.apply(self.lecture);self.assertEqual(a.strip_blocks(self.output().read_bytes()),original)
        with self.assertRaises(ValueError):a.strip_blocks(b'<!-- lecture-images:start section=1 -->\n')
    def test_pdf_render_cache_and_missing_page_guard(self):
        writer=PdfWriter();writer.add_blank_page(width=360,height=200);writer.add_blank_page(width=360,height=200)
        pdf=self.lecture/'input/lecture.pdf'
        with pdf.open('wb') as f:writer.write(f)
        source_hash=a.file_hash(pdf);export=a.extract_pdf(self.lecture,'input/lecture.pdf',480,'fixture',None)
        self.assertEqual(a.extract_pdf(self.lecture,'input/lecture.pdf',480,'fixture',None)['status'],'reused')
        items=[{'source':export['pages'][0]['image'],'alt':'Page 1','reason':'First page'}]
        coverage=[{'pdf':'input/lecture.pdf','mode':'all'}];self.mapping(items,coverage=coverage)
        with self.assertRaisesRegex(ValueError,'Unlinked PDF pages'):publish.apply(self.lecture)
        self.assertFalse(self.output().exists())
        items.append({'source':export['pages'][1]['image'],'alt':'Page 2','reason':'Second page'})
        self.mapping(items,coverage=coverage);self.assertEqual(publish.apply(self.lecture)['linked_pdf_pages'],2)
        self.assertEqual(a.file_hash(pdf),source_hash)
        self.assertEqual(a.contact_sheet(self.lecture,'work/pdf-pages',2,12)['image_count'],2)
    def test_state_commit_failure_restores_previous_output(self):
        self.mapping();publish.apply(self.lecture);previous=self.output().read_bytes()
        self.mapping([{'source':'input/b.png','alt':'New','reason':'New example'}])
        with patch.object(a,'write_json',side_effect=OSError('state failed')):
            with self.assertRaises(OSError):publish.apply(self.lecture)
        self.assertEqual(self.output().read_bytes(),previous)
    def test_verify_detects_image_changes(self):
        self.mapping();publish.apply(self.lecture)
        (self.lecture/'output/images/a.png').write_bytes((self.lecture/'input/b.png').read_bytes())
        with self.assertRaisesRegex(ValueError,'Linked image changed'):publish.verify(self.lecture)
    def test_prepare_reports_refinement_without_fabricating_markdown(self):
        (self.lecture/'work/transcript.md').unlink();(self.lecture/'input/raw.txt').write_text('raw speech',encoding='utf-8')
        report=prepare(self.lecture)
        self.assertEqual(report['remaining_content_work'][0]['stage'],'refine_transcript')
        self.assertFalse((self.lecture/'work/transcript.md').exists());self.assertFalse(self.output().exists())
    def test_imported_output_transitions_to_managed_without_duplicate_images(self):
        self.mapping()
        output=self.output()
        manual=self.base.replace(b'## Same\r\n',b'## Same\r\n\r\n![Example](./images/a.png)\r\n',1)
        (self.lecture/'output/images').mkdir()
        image=self.lecture/'output/images/a.png';image.write_bytes((self.lecture/'input/a.png').read_bytes())
        output.write_bytes(manual)
        state={'version':2,'lecture':self.lecture.name,'plan_sha256':None,'pdf_coverage':[],
            'documents':{'output/test-lecture.md':{'mode':'imported','source_markdown':'work/transcript.md',
                'output_sha256':a.digest(manual),'body_sha256':a.digest(self.base),'image_count':1,
                'references':[{'section':1,'image':'output/images/a.png'}]}},
            'assets':{'output/images/a.png':{'source':'input/a.png','sha256':a.file_hash(image),'pdf_page':None}}}
        a.write_json(self.lecture/'work/state.json',state)
        publish.verify(self.lecture);publish.apply(self.lecture)
        self.assertEqual(a.strip_blocks(output.read_bytes()),self.base)
        self.assertEqual(len(a.LINK.findall(output.read_bytes())),1)
        self.assertEqual(a.read_json(self.lecture/'work/state.json')['documents']['output/test-lecture.md']['mode'],'managed')

if __name__=='__main__':unittest.main()
