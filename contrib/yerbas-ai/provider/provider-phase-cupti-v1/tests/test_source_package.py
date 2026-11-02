import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from prepare_package import assemble
import install


class PackageTests(unittest.TestCase):
    def test_source_matches_deployment_manifest_except_external_binary(self):
        source = Path(install.__file__).parent
        for name, digest in json.loads((source/'INSTALL-SHA256.json').read_text()).items():
            if name == 'payload/collector.so':
                self.assertFalse((source/name).exists())
            else:
                self.assertEqual(hashlib.sha256((source/name).read_bytes()).hexdigest(), digest)

    def test_bad_collector_cannot_produce_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); collector = root/'collector.so'; collector.write_bytes(b'wrong')
            with self.assertRaises(ValueError):
                assemble(Path(install.__file__).parent, collector, root/'out')
            self.assertFalse((root/'out').exists())

    def test_verified_fixture_assembly_and_existing_destination_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'source'; source.mkdir()
            collector = root/'collector.so'; collector.write_bytes(b'fixture only')
            (source/'INSTALL-SHA256.json').write_text(json.dumps({'payload/collector.so':hashlib.sha256(collector.read_bytes()).hexdigest()}))
            assemble(source, collector, root/'out')
            self.assertEqual((root/'out/payload/collector.so').read_bytes(),collector.read_bytes())
            with self.assertRaises(ValueError):assemble(source, collector, root/'out')

    def test_source_only_installer_fails_closed(self):
        with self.assertRaises(ValueError):install.payload(Path(install.__file__).parent)
