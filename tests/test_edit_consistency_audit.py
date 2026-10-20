import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.analyze_edit_consistency import (ARCHIVE, CONFIG, ROOT, analyze,
    check_evidence, check_annotation, deployment_verdict, verify_archive)
from rsi_eval.decision_cases import load_cases


class EditConsistencyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / CONFIG).read_text(encoding='utf-8'))
        cls.cases = {c['id']: c for c in load_cases(ROOT)}

    def test_all_sixteen_records_and_no_candidate_or_network_execution(self):
        with patch('rsi_eval.executor.evaluate_candidate', side_effect=AssertionError('execution')), \
             patch('rsi_eval.sandbox.run_candidate', side_effect=AssertionError('sandbox')), \
             patch('socket.socket.connect', side_effect=AssertionError('network')):
            report = analyze(ROOT)
        self.assertEqual(len(report['rows']), 16)
        self.assertEqual(report['main_claim_counts'], {'supported': 14, 'unknown': 2})
        self.assertEqual(report['explicit_bytes_claim_counts'], {'supported': 5, 'contradicted': 1})
        self.assertEqual(report['new_activity'], dict(model_calls=0, candidate_executions=0,
            task_evaluations=0, probe_executions=0, strategy_updates=0, model_weight_updates=0))
        rows = {r['session_id']: r for r in report['rows']}
        self.assertEqual(rows['P-format-r1-checked']['main_claim']['verdict']['status'], 'supported')
        self.assertEqual(rows['P-format-r1-checked']['deployment_assumptions'][0]['verdict']['status'], 'contradicted')
        self.assertEqual(rows['P-empty-r2-hidden']['explicit_bytes_claim']['status'], 'contradicted')

    def test_evidence_rejects_quote_position_path_hash_and_pointer_changes(self):
        evidence = self.config['rows'][0]['main_claim']['evidence']
        check_evidence(ROOT, evidence, self.config['rows'][0]['session_id'])
        for key, value in [('quote', 'invented'), ('start_character', 1),
                           ('file', '../auth.json'), ('file_sha256', '0' * 64),
                           ('json_pointer', '/auxiliary')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_evidence(ROOT, dict(evidence, **{key: value}), self.config['rows'][0]['session_id'])

    def test_symbolic_target_and_parameter_annotation_are_bound(self):
        row = next(r for r in self.config['rows'] if r['session_id'] == 'S-x5-r1-checked')
        candidate = json.loads((ROOT / ARCHIVE / 'sessions' / row['session_id'] / 'candidate.json').read_text())
        check_annotation(ROOT, row, self.cases['S-x5'], candidate)
        for key, value in [('parameter_index', 3), ('basis', 'v**3'), ('result_n_params', 5)]:
            bad = copy.deepcopy(row); bad['main_claim']['target'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_annotation(ROOT, bad, self.cases['S-x5'], candidate)
        bad = copy.deepcopy(row); bad['n_params_claimed_at_submission'] = 5
        with self.assertRaises(ValueError): check_annotation(ROOT, bad, self.cases['S-x5'], candidate)

    def test_archive_manifest_tampering_is_rejected_before_other_reads(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / ARCHIVE
            target.mkdir(parents=True)
            (target / 'manifest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'manifest'): verify_archive(Path(d))

    def test_deployment_contract_requires_pinned_runtime_and_known_claim(self):
        pins = self.config['deployment_contract']['runtime_files_sha256']
        self.assertEqual(deployment_verdict(ROOT, 'final_host_normalization', pins)['status'], 'contradicted')
        self.assertEqual(deployment_verdict(ROOT, 'arbitrary_semantics', pins)['status'], 'unknown')
        bad = dict(pins); bad['rsi_eval/planning.py'] = '0' * 64
        with self.assertRaises(ValueError): deployment_verdict(ROOT, 'final_host_normalization', bad)


if __name__ == '__main__': unittest.main()
