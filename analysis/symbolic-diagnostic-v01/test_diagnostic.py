import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('diagnostic', BASE/'diagnostic.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class DiagnosticTests(unittest.TestCase):
    def test_closed_train_allowlist(self):
        for task in ('oscillator1', 'stressstrain/test_id', '../stressstrain', 'bactgrow/test_ood'):
            with self.assertRaises(ValueError): d.allowed_task(task)
        self.assertEqual(d.allowed_task('bactgrow'), 'bactgrow')

    def test_write_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'receipt.json'
            d.write(path, {'a': 1})
            with self.assertRaises(FileExistsError): d.write(path, {'a': 2})
            self.assertEqual(json.loads(path.read_bytes()), {'a': 1})

    def test_finite_json(self):
        with self.assertRaises(ValueError): d.canonical({'bad': float('nan')})

    def test_integrity_rejects_modified_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'a').write_bytes(b'abc')
            records = [{'path':'a', 'sha256':d.sha(b'abc')}]
            d.check_files(root, records)
            (root/'a').write_bytes(b'xyz')
            with self.assertRaises(ValueError): d.check_files(root, records)

    def test_integrity_refuses_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                d.check_files(Path(directory), [{'path':'../a','sha256':'0'*64}])

    def test_stress_mapping(self):
        self.assertEqual(d.effective('stress-original-7', [2,3,4,5,6,7,8]), [8,420,525,1008])
        self.assertEqual(d.effective('stress-direct-4', [1,2,3,4]), [1,2,3,4])

    def test_failed_fit_never_scored(self):
        self.assertFalse(d.fit_succeeded({'status':'completed','result':{'status':'candidate_error','params':[1]}}))

    def test_success_requires_finite_params_and_convergence(self):
        good={'status':'completed','result':{'status':'success','converged':True,'params':[1.0]}}
        self.assertTrue(d.fit_succeeded(good))
        good['result']['params']=[float('inf')]
        self.assertFalse(d.fit_succeeded(good))

    def test_infrastructure_is_distinct_from_candidate_failure(self):
        self.assertTrue(d.infrastructure_failure({'status':'infrastructure_error'}))
        self.assertFalse(d.infrastructure_failure({'status':'completed','result':{'status':'candidate_error'}}))
        self.assertFalse(d.infrastructure_failure({'status':'timeout'}))

    def test_complete_order_is_predefined(self):
        self.assertEqual(len(d.ORDER), 8)
        self.assertEqual(len(set(d.ORDER)), 8)
        self.assertEqual(d.ORDER[3:7], [f'bact-square-14-drop{i}' for i in range(4)])


if __name__ == '__main__': unittest.main()
