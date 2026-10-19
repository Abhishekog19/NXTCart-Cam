"""Reference-conditioned payload tests; no network or paid API usage."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from ml.ai_backend import VLMBackend
from ml.verifier import Verdict
from test_verify import FakeHTTP


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(42)
        self.crops = [rng.integers(0, 256, (160, 160, 3), dtype=np.uint8) for _ in range(6)]
        folder = self.root / 'expected'
        folder.mkdir()
        for i in range(4):
            cv2.imwrite(str(folder / f'{i:03}.jpg'), self.crops[i])
        (self.root / 'other').mkdir()
        (self.root / 'other' / '001.jpg').write_bytes(b'not an image')

    def backend(self, **kwargs):
        return VLMBackend(api_key='test', references_dir=str(self.root), **kwargs)

    def test_references_and_live_views_single_request(self):
        http = FakeHTTP(reply='{"matches":true,"confident":true,"reason":"same packaging"}')
        with patch.dict('sys.modules', {'requests': http}):
            backend = self.backend()
            result = backend.verify('expected', self.crops)
        self.assertEqual(result.verdict, Verdict.MATCH)
        self.assertEqual(len(http.calls), 1)
        parts = http.calls[0]['json']['messages'][1]['content']
        labels = [p['text'] for p in parts if p['type'] == 'text']
        self.assertEqual(sum(p['type'] == 'image_url' for p in parts), 5)
        self.assertEqual(sum(s.startswith('REFERENCE') for s in labels), 2)
        self.assertEqual(sum(s.startswith('OBSERVED') for s in labels), 3)
        self.assertEqual(backend.stats[0].reference_images_sent, 2)
        self.assertEqual(backend.stats[0].images_sent, 5)
        images = [p['image_url']['url'] for p in parts if p['type'] == 'image_url']
        self.assertNotEqual(images[0], images[-1])

    def test_missing_corrupt_and_traversal_fail_without_request(self):
        http = FakeHTTP()
        with patch.dict('sys.modules', {'requests': http}):
            for sku in ('missing', 'other', '../expected', str(self.root)):
                with self.subTest(sku=sku):
                    self.assertEqual(self.backend().verify(sku, self.crops).verdict, Verdict.UNAVAILABLE)
        self.assertEqual(http.calls, [])

    def test_reference_limit_and_curated_selection(self):
        path = self.root / 'expected' / 'ai_reference_front.jpg'
        cv2.imwrite(str(path), self.crops[4])
        parts = self.backend(max_references=1)._reference_parts('expected')
        from ml.ai_backend import _encode_crop
        expected = _encode_crop(cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_2))
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[1]['image_url']['url'], expected)
        for value in (0, 4, True):
            with self.assertRaises(ValueError):
                self.backend(max_references=value)

    def test_uncertain_answer_does_not_accept(self):
        http = FakeHTTP(reply='{"matches":true,"confident":false,"reason":"size obscured"}')
        with patch.dict('sys.modules', {'requests': http}):
            self.assertFalse(self.backend().verify('expected', self.crops).accepted)


if __name__ == '__main__':
    unittest.main()
