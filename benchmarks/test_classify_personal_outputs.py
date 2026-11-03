import tempfile
import unittest
from pathlib import Path

from classify_personal_outputs import classify


class ClassificationTests(unittest.TestCase):
    def test_only_absent_localized_copy_with_identical_bytes_is_proven(self):
        with tempfile.TemporaryDirectory() as tmp:
            official, fork = Path(tmp)/'official', Path(tmp)/'fork'
            (official/'en').mkdir(parents=True)
            fork.mkdir()
            (official/'en/a.png').write_bytes(b'actual image bytes')
            (fork/'a.png').write_bytes(b'actual image bytes')
            result = classify(official, fork, ['en/a.png', 'index.html'])
            self.assertEqual(list(result['classified']), ['en/a.png'])
            self.assertEqual(result['unclassified_paths'], ['index.html'])
            (fork/'a.png').write_bytes(b'other image bytes')
            self.assertEqual(classify(official, fork, ['en/a.png'])['classified'], {})
            (fork/'a.png').write_bytes(b'actual image bytes')
            (fork/'en').mkdir()
            (fork/'en/a.png').write_bytes(b'changed localized bytes')
            self.assertEqual(classify(official, fork, ['en/a.png'])['classified'], {})
