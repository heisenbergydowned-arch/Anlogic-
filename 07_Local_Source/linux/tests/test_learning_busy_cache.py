import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from normal_npu.learning import Learning, save


class BusyCacheTest(unittest.TestCase):
    def test_new_and_atomically_changed_jobs_are_never_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            learning = Learning(root=directory)
            folder = Path(directory)/'jobs'/'a'
            folder.mkdir()
            path = folder/'job.json'
            save(path, {'state': 'COMPLETED', 'report': 'x'*100000})
            self.assertFalse(learning.busy())
            # Unchanged historical payloads must not be read on renewal polls.
            with patch.object(Path, 'read_text', side_effect=AssertionError('historical reread')):
                self.assertFalse(learning.busy())
            save(path, {'state': 'RUNNING', 'report': 'x'*100000})
            self.assertTrue(learning.busy())
            save(path, {'state': 'FAILED'})
            self.assertFalse(learning.busy())
            second = Path(directory)/'jobs'/'b'
            second.mkdir()
            save(second/'job.json', {'state': 'QUEUED'})
            self.assertTrue(learning.busy())
            (second/'job.json').unlink()
            self.assertFalse(learning.busy())

    def test_corrupt_changed_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            learning = Learning(root=directory)
            folder = Path(directory)/'jobs'/'a'
            folder.mkdir()
            path = folder/'job.json'
            save(path, {'state': 'COMPLETED'})
            self.assertFalse(learning.busy())
            path.write_text('{')
            with self.assertRaises(ValueError):
                learning.busy()


if __name__ == '__main__':
    unittest.main()
