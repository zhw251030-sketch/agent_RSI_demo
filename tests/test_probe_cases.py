"""Probe inputs retain archived bytes and never load task or sealed data."""
import hashlib
import importlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[1]


class ProbeCasesTests(unittest.TestCase):
    def setUp(self):
        self.m=importlib.import_module('rsi_eval.probe_cases')

    def test_five_cases_preserve_source_bytes_and_exact_requested_identities(self):
        bundle=self.m.load_cases(ROOT)
        self.assertEqual([c['id'] for c in bundle['planning']],
            ['p2-P-H002-checked','p1-P-A002-checked','p2-P-H002-self'])
        self.assertEqual([c['id'] for c in bundle['symbolic']],
            ['p1-S-poly5-self','p2-S-odd4-checked'])
        for case in bundle['planning']+bundle['symbolic']:
            raw=(ROOT/case['source_path']).read_bytes()
            self.assertEqual(case['source'].encode('utf-8'),raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),case['source_sha256'])
            self.assertNotIn('metrics',case)
            self.assertNotIn('results',case)
            self.assertNotIn('score',case)

    def test_symbolic_parent_bytes_parameter_counts_and_remove_index_are_pinned(self):
        cases=self.m.load_cases(ROOT)['symbolic']
        self.assertEqual([(c['n_params'],c['parent_n_params'],c['remove_param_index'])
                          for c in cases],[(6,5,5),(5,4,4)])
        for case in cases:
            raw=(ROOT/case['parent_path']).read_bytes()
            self.assertEqual(case['parent_source'].encode('utf-8'),raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),case['parent_sha256'])
            self.assertEqual(case['task_id'],'oscillator1')
            self.assertEqual(case['scope'],'train')

    def test_scope_is_exact_two_public_and_original_ten_development_ids(self):
        b=self.m.load_cases(ROOT)
        self.assertEqual(b['public_tasks'],[f'spannerlearning/seed0/problem{i}' for i in range(2)])
        self.assertEqual(b['development_tasks'],[f'spannerlearning/seed0/problem{i}' for i in range(10)])
        for case in b['planning']:
            self.assertEqual(case['task_ids'],b['public_tasks'])

    def _copy_inputs(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        out=Path(tmp.name)
        for rel in self.m.load_cases(ROOT)['provenance']['source_files']:
            dest=out/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/rel,dest)
        return out

    def test_minimal_input_copy_loads_without_any_task_dataset_or_runtime(self):
        out=self._copy_inputs()
        self.assertFalse((out/'data').exists())
        self.assertFalse((out/'vendor').exists())
        self.assertFalse((out/'.task-runtime').exists())
        self.assertEqual(self.m.load_cases(out),self.m.load_cases(ROOT))

    def test_source_parent_trajectory_manifest_and_task_config_tampering_are_rejected(self):
        bundle=self.m.load_cases(ROOT)
        paths=[bundle['planning'][0]['source_path'],bundle['symbolic'][0]['parent_path'],
            bundle['planning'][0]['provenance']['candidates_path'],
            bundle['provenance']['archive_manifest_path'],
            bundle['provenance']['planning_config_path'],bundle['provenance']['base_config_path']]
        for rel in paths:
            with self.subTest(path=rel):
                out=self._copy_inputs();p=out/rel;p.write_bytes(p.read_bytes()+b'\n')
                with self.assertRaises(ValueError):self.m.load_cases(out)

    def test_unreturned_planning_parent_is_also_verified(self):
        b=self.m.load_cases(ROOT);rel=b['planning'][0]['provenance']['parent_source_path']
        out=self._copy_inputs();(out/rel).write_bytes(b'changed')
        with self.assertRaises(ValueError):self.m.load_cases(out)

    def test_missing_source_rejected(self):
        out=self._copy_inputs();b=self.m.load_cases(out)
        (out/b['planning'][0]['source_path']).unlink()
        with self.assertRaises(ValueError):self.m.load_cases(out)

    def test_only_pinned_metadata_and_archived_source_files_are_read(self):
        expected=set(self.m.load_cases(ROOT)['provenance']['source_files'])
        real=Path.read_bytes;seen=[]
        def read(path):
            rel=path.relative_to(ROOT).as_posix();seen.append(rel)
            self.assertIn(rel,expected)
            return real(path)
        with patch.object(Path,'read_bytes',read):self.m.load_cases(ROOT)
        self.assertEqual(set(seen),expected)

    def test_diagnostics_or_model_calls_are_not_required(self):
        out=self._copy_inputs()
        for module in ('rsi_eval.executor','rsi_eval.sandbox','rsi_eval.pilot_agent'):
            with patch.dict('sys.modules',{module:None}):
                self.assertEqual(len(self.m.load_cases(out)['planning']),3)

    def test_returned_objects_do_not_mutate_future_loads(self):
        first=self.m.load_cases(ROOT)
        first['planning'][0]['source']='changed'
        first['public_tasks'].clear()
        first['provenance']['source_files'].clear()
        second=self.m.load_cases(ROOT)
        self.assertNotEqual(second['planning'][0]['source'],'changed')
        self.assertEqual(len(second['public_tasks']),2)


if __name__=='__main__':unittest.main()
