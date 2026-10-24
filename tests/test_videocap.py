from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cv2
import numpy as np
from pipeline import assemble as a
from pipeline.videocap import bridge


class VideoCapTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='.capture-test-',dir=Path(__file__).parent)
        self.root=Path(self.tmp.name).resolve();self.old=a.ROOT;a.ROOT=self.root
        self.lecture=self.root/'lectures/capture-test'
        (self.lecture/'input').mkdir(parents=True)
        self.video=self.lecture/'input/강의 영상.mp4'
        writer=cv2.VideoWriter(str(self.video),cv2.VideoWriter_fourcc(*'mp4v'),30,(320,180))
        self.assertTrue(writer.isOpened())
        for i in range(260):
            frame=np.full((180,320,3),255,dtype=np.uint8)
            if i<100:cv2.rectangle(frame,(20,30),(130,140),(0,0,0),-1)
            else:cv2.rectangle(frame,(190,30),(300,140),(0,0,0),-1)
            writer.write(frame)
        writer.release()
    def tearDown(self):
        a.ROOT=self.old
        self.assertTrue(self.root.is_relative_to(Path(__file__).resolve().parent));self.tmp.cleanup()
    def test_adjacent_dhash_groups_keep_last(self):
        candidates=[{'id':str(i),'dhash':value} for i,value in enumerate(['0','7f','ffff','ffff'])]
        self.assertEqual(bridge.representative_ids(candidates,8),['1','3'])
    def test_real_mp4_export_preserves_native_manifest_and_reuses_candidates(self):
        original=a.file_hash(self.video)
        result=bridge.capture(self.lecture,'input/강의 영상.mp4')
        self.assertEqual(result['status'],'captured');self.assertGreaterEqual(result['candidate_count'],2)
        manifest_path=a.safe_path(self.lecture,result['manifest']);manifest=a.read_json(manifest_path)
        self.assertEqual(manifest['filename_format'],bridge.engine.EXPORT_FILENAME_FORMAT)
        self.assertEqual(manifest['source']['sha256'],original)
        candidate_root=a.safe_path(self.lecture,result['candidates']).parent
        for export in manifest['exports']:
            self.assertEqual(a.file_hash(candidate_root/export['source_file']),a.file_hash(manifest_path.parent/export['file']))
        with patch.object(bridge.engine,'extract_candidates',side_effect=AssertionError('must not decode twice')):
            self.assertEqual(bridge.capture(self.lecture,'input/강의 영상.mp4')['status'],'reused')
        self.assertEqual(a.file_hash(self.video),original)
    def test_interrupted_capture_does_not_publish_complete_export(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaisesRegex(ValueError,'interrupted'):
            bridge.capture(self.lecture,'input/강의 영상.mp4',cancel=cancel)
        self.assertFalse(list((self.lecture/'work').rglob('manifest.json')))


if __name__=='__main__':unittest.main()
