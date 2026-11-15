import unittest

from scripts.check_publication import inspect


class PublicationTest(unittest.TestCase):
    def test_reject_private_artifacts_and_binaries(self):
        for path in ('private/data.json', 'runs/result.json', 'examples/weights.gguf', '.env'):
            self.assertIsNotNone(inspect(path, b'{}'))
        self.assertIsNotNone(inspect('examples/demo.json', b'\xff'))

    def test_detect_secret_like_material_without_committing_real_credentials(self):
        for value in ('gh' + 'p_' + 'a' * 36, 's' + 'k-' + 'x' * 30,
                      'https://' + 'user:password@host.example',
                      '/' + 'home/' + 'someone/' + 'private'):
            self.assertIsNotNone(inspect('examples/demo.json', value.encode()))

    def test_public_source_allowed(self):
        self.assertIsNone(inspect('keel_arena/results.py', b'"""Public source."""'))
