import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from fork_build import prepare_fork, verify_metadata
from compare_matrix import compare
from test_compare_matrix import fixture


class ForkPreparationTests(unittest.TestCase):
    def test_default_capture_is_accepted_by_history_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);binary=root/'target/release/zola';binary.parent.mkdir(parents=True);binary.write_bytes(b'engine');(root/'Cargo.lock').write_text('locked')
            def command(*args):
                if args[:2]==('rustc','-Vv'):return 'compiler'
                if args[:2]==('git','rev-parse'):return 'commit'
                if args[:2]==('git','status'):return ''
                return 'version'
            with patch('fork_build.ROOT',root),patch('fork_build.subprocess.run') as build,patch('fork_build.subprocess.check_output',return_value=b'Cargo.lock\0'),patch('fork_build.command',side_effect=command):
                metadata=prepare_fork(binary)
            self.assertEqual(build.call_args.args[0],['cargo','build','--locked','--release'])
            self.assertIn('source_sha256',metadata);self.assertIn('build_environment',metadata)
            current=fixture();current['fork_build']=metadata;current['binary_sha256']=metadata['binary_sha256']
            self.assertEqual(compare(current,copy.deepcopy(current))['status'],'compatible_no_regression_flag')

    def test_stale_binary_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            binary=Path(temp)/'zola';binary.write_bytes(b'new')
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                verify_metadata(binary,{'binary_sha256':'stale','toolchain':'compiler','features':'default','profile':'release','lock_sha256':'lock'})

    def test_custom_binary_requires_explicit_attestation(self):
        with self.assertRaisesRegex(ValueError,'requires --fork-build-metadata'):
            prepare_fork(Path('/tmp/arbitrary-prebuilt-zola'))


if __name__=='__main__':unittest.main()
