import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from build_runtime import build, checked


class BundleTests(unittest.TestCase):
    def test_hashes_and_existing_destination_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'bundle'
            manifest = build(target)
            self.assertFalse(manifest['installable'])
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256((target / name).read_bytes()).hexdigest(), digest)
            runtime = json.loads((target / 'runtime/RUNTIME.json').read_text())
            self.assertEqual(set(runtime['files']) | {'RUNTIME.json'},
                             {p.name for p in (target / 'runtime').iterdir()})
            with self.assertRaisesRegex(ValueError, 'preserved'):
                build(target)
            self.assertEqual(manifest, json.loads((target / 'MANIFEST.json').read_text()))

    def test_changed_source_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'source.py').write_text('pass\n')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                checked(root, 'source.py', '0' * 64)
            (root / 'link.py').symlink_to(root / 'source.py')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                checked(root, 'link.py', hashlib.sha256(b'pass\n').hexdigest())
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                checked(root, '../source.py', '0' * 64)


if __name__ == '__main__':
    unittest.main()
