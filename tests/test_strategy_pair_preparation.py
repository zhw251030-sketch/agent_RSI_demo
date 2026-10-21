import importlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

try:
    prep = importlib.import_module('rsi_eval.strategy_pair_preparation')
except ModuleNotFoundError as error:
    if error.name != 'rsi_eval.strategy_pair_preparation':
        raise
    prep = None
ROOT = Path(__file__).resolve().parents[1]


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(prep, 'New immutable strategy preparation is missing')

    def test_prior_inputs_are_verified_without_expanding_old_runtime(self):
        result = prep.verify_prior_inputs(ROOT)
        self.assertEqual(result['old_runtime_files'], 236)
        self.assertEqual(result['learning_transitions'], 24)
        self.assertEqual(result['update_packet_bytes'], 81393)

    def test_new_freeze_is_additive_and_never_overwrites(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            output = Path(directory)/'preparation'
            result = prep.prepare(ROOT, output, allow_dirty=True)
            self.assertFalse(result['execution_ready'])
            self.assertEqual(result['research_activity']['model_requests'], 0)
            self.assertEqual(result, prep.verify(ROOT, output))
            with self.assertRaises(FileExistsError):
                prep.prepare(ROOT, output, allow_dirty=True)

    def test_frozen_output_extra_file_or_changed_byte_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            output=Path(directory)/'preparation'
            prep.prepare(ROOT,output,allow_dirty=True)
            extra=output/'extra.json';extra.write_text('{}')
            with self.assertRaisesRegex(ValueError,'files'):
                prep.verify(ROOT,output)
            extra.unlink()
            path=output/'update-packet.json';path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'hash'):
                prep.verify(ROOT,output)

    def test_changed_pinned_legacy_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            archive=ROOT/prep.PRIOR_ARCHIVE
            shutil.copytree(archive,root/prep.PRIOR_ARCHIVE)
            info=json.loads((archive/'preparation/preparation.json').read_bytes())
            for name in info['runtime_files_sha256']:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/name,target)
            target=root/'rsi_eval/strategy_binding.py'
            target.write_bytes(target.read_bytes()+b'\n# changed\n')
            with self.assertRaisesRegex(ValueError,'runtime'):
                prep.verify_prior_inputs(root)

    def test_rehashed_learning_packet_is_rejected_against_prior_inputs(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            output=Path(directory)/'preparation'
            prep.prepare(ROOT,output,allow_dirty=True)
            path=output/'update-packet.json'
            packet=json.loads(path.read_bytes());packet['task_text']='Changed learning instruction'
            path.write_bytes(prep.canonical(packet)+b'\n')
            manifest=json.loads((output/'manifest.json').read_bytes())
            manifest['files'][path.name]=prep.sha(path.read_bytes())
            (output/'manifest.json').write_bytes(prep.canonical(manifest)+b'\n')
            with self.assertRaisesRegex(ValueError,'pinned prior'):
                prep.verify(ROOT,output)

    def test_public_model_settings_are_bounded_without_loading_credentials(self):
        result=prep.model_settings(ROOT)
        self.assertEqual(result['effective']['timeout'],180)
        self.assertEqual(result['effective']['max_output_tokens'],8192)
        self.assertEqual(result['effective']['num_retries'],0)
        self.assertNotIn('api_key',result['effective'])


if __name__ == '__main__':
    unittest.main()
