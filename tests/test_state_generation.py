"""Cold-start source storage and task identity separation; no code execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
AVAILABLE = importlib.util.find_spec('rsi_eval.state_generation') is not None
if AVAILABLE:
    from rsi_eval.state_generation import build_inputs, validate_config, GenerationController


class Availability(unittest.TestCase):
    def test_cold_start_module_exists(self):
        self.assertTrue(AVAILABLE, 'Cold-start source generation is not implemented')


@unittest.skipUnless(AVAILABLE, 'implementation not present')
class StateGenerationTests(unittest.TestCase):
    def setUp(self):
        fixture = ROOT / 'artifacts/edit-commitment/2026-10-21/v01/reviews/P-format-self/task-packet.json'
        self.examples = json.loads(fixture.read_text(encoding='utf-8'))['public_examples']
        self.inputs = build_inputs(ROOT, self.examples)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'session'

    def controller(self, index=0):
        return GenerationController(self.inputs['slots'][index], self.output)

    def test_slot_order_roles_dimensions_and_task_allocations(self):
        rows = self.inputs['slots']
        self.assertEqual([x['id'] for x in rows], ['P-select-1', 'S-select-1', 'P-eval-1',
            'S-bact-eval-1', 'P-select-2', 'S-select-2', 'P-eval-2', 'S-stress-eval-1'])
        self.assertEqual([x['input_dimension'] for x in rows], [None, 3, None, 4, None, 3, None, 2])
        self.assertEqual([len(x['task_ids']) for x in rows], [19, 1, 63, 1, 19, 1, 63, 1])
        self.assertEqual(rows[1]['task_ids'], ['oscillator2'])
        self.assertEqual(rows[3]['task_ids'], ['bactgrow'])
        self.assertEqual(rows[7]['task_ids'], ['stressstrain'])

    def test_identical_packets_across_planning_roles_and_symbolic_repeats(self):
        rows = self.inputs['slots']
        self.assertEqual(len({rows[i]['packet_sha256'] for i in (0, 2, 4, 6)}), 1)
        self.assertEqual(rows[1]['packet_sha256'], rows[5]['packet_sha256'])

    def test_prompts_name_the_actual_sdk_submission_tool(self):
        for family in ('planning', 'symbolic'):
            instructions = (ROOT / 'prompts/state-generation' / (family + '.md')).read_text(encoding='utf-8')
            with self.subTest(family=family):
                self.assertIn('submit_candidate', instructions)
                self.assertNotIn('submit_initial_source', instructions)
                packets = [row['packet'] for row in self.inputs['slots'] if row['family'] == family]
                self.assertTrue(all(packet['instructions'] == instructions for packet in packets))

    def test_packet_does_not_expose_host_identifiers_or_symbolic_metadata(self):
        banned_keys = {'role', 'slot_id', 'task_id', 'task_ids', 'source_sha256',
                       'data_sha256', 'evaluation', 'source', 'n_params_result'}
        def walk(value):
            if isinstance(value, dict):
                self.assertFalse(banned_keys & set(value))
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        for row in self.inputs['slots']:
            packet = row['packet']; walk(packet)
            text = json.dumps(packet)
            for forbidden in ('seed0', 'seed1', 'seed2', 'oscillator', 'bactgrow',
                              'stressstrain', 'test_id', 'test_ood', row['id']):
                self.assertNotIn(forbidden, text)
            if row['family'] == 'symbolic':
                self.assertEqual(packet['input_names'], [f'u{i}' for i in range(row['input_dimension'])])
                self.assertNotIn('"temp"', text)
                self.assertNotIn('"pH"', text)

    def test_build_inputs_reads_no_task_data_or_historical_source(self):
        original = Path.read_bytes
        def guarded(path):
            parts = path.relative_to(ROOT).parts
            self.assertNotIn(parts[0], ('data', 'vendor', 'artifacts', 'runs'))
            return original(path)
        with patch.object(Path, 'read_bytes', guarded):
            self.assertEqual(build_inputs(ROOT, self.examples), self.inputs)

    def test_wrong_public_task_content_order_and_excess_fields_refused(self):
        altered = copy.deepcopy(self.examples); altered[0]['goal'] = []
        extra = copy.deepcopy(self.examples); extra[0]['score'] = 10
        for value in (list(reversed(self.examples)), self.examples[:1], altered, extra):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_inputs(ROOT, value)

    def test_config_caps_are_exact_and_no_extra_fields(self):
        config = json.loads((ROOT / 'configs/pilots/state-generation-v0.1.json').read_text())
        self.assertEqual(validate_config(config), config)
        self.assertEqual(config['budgets']['max_requests'], 8)
        self.assertEqual(config['budgets']['max_output_tokens'], 8192)
        for mutate in ('requests', 'output', 'resume', 'extra', 'partition'):
            value = copy.deepcopy(config)
            if mutate == 'requests': value['budgets']['max_requests'] = 9
            elif mutate == 'output': value['budgets']['max_output_tokens'] = 4096
            elif mutate == 'resume': value['resume'] = True
            elif mutate == 'partition': value['partition_sha256'] = '0' * 64
            else: value['future_override'] = True
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): validate_config(value)

    def test_submission_stores_exact_utf8_without_executing_even_invalid_syntax(self):
        c = self.controller()
        source = 'raise RuntimeError("must never execute")\ninvalid python !!!\n# 数学\n'
        result = c.submit(session_id='P-select-1', source=source, n_params=0)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual((self.output / 'source.py').read_bytes(), source.encode('utf-8'))
        self.assertEqual(c.candidate['source_sha256'], hashlib.sha256(source.encode('utf-8')).hexdigest())
        self.assertEqual(c.summary()['candidate_executions'], 0)
        self.assertEqual(c.candidate['status'], 'stored_unexecuted')

    def test_symbolic_parameters_zero_and_sixteen_preserved(self):
        for count in (0, 16):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                c = GenerationController(self.inputs['slots'][1], Path(directory) / 's')
                self.assertEqual(c.submit('S-select-1', 'def equation(*x): pass', count)['status'], 'accepted')
                self.assertEqual(c.candidate['n_params'], count)

    def test_invalid_submit_consumes_the_one_attempt(self):
        c = self.controller()
        self.assertEqual(c.submit('P-select-1', 'pass', 1)['status'], 'invalid_request')
        self.assertIsNone(c.candidate)
        self.assertEqual(c.submit('P-select-1', 'pass', 0)['status'], 'budget_exhausted')
        self.assertFalse((self.output / 'source.py').exists())

    def test_symbolic_bad_parameter_count_types_and_source_size_refused(self):
        cases = [('pass', True), ('pass', -1), ('pass', 17), ('pass', 1.0),
                 (' ', 1), ('数' * 5462, 1), ('\ud800', 1), (None, 1)]
        for source, count in cases:
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                c = GenerationController(self.inputs['slots'][1], Path(directory) / 's')
                self.assertEqual(c.submit('S-select-1', source, count)['status'], 'invalid_request')
                self.assertIsNone(c.candidate)

    def test_session_identity_and_unsupported_fields_refused(self):
        c = self.controller()
        self.assertEqual(c.submit('S-select-1', 'pass', 0)['status'], 'invalid_request')
        with self.assertRaises(TypeError): c.submit('P-select-1', 'pass', 0, rationale='extra')

    def test_duplicate_submission_does_not_change_original_bytes(self):
        c = self.controller(); c.submit('P-select-1', 'pass\n', 0)
        before = {p.name: p.read_bytes() for p in self.output.iterdir() if p.is_file()}
        self.assertEqual(c.submit('P-select-1', 'different', 0)['status'], 'budget_exhausted')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir() if p.is_file()})

    def test_existing_source_is_not_overwritten(self):
        c = self.controller(); (self.output / 'source.py').write_bytes(b'existing')
        with self.assertRaises(FileExistsError): c.submit('P-select-1', 'new', 0)
        self.assertEqual((self.output / 'source.py').read_bytes(), b'existing')

    def test_reinitialization_and_symlink_output_refused(self):
        self.controller()
        with self.assertRaises(FileExistsError): self.controller()
        original = Path.is_symlink
        linked = Path(self.temp.name) / 'linked'
        with patch.object(Path, 'is_symlink', lambda path: path == linked or original(path)):
            with self.assertRaises(ValueError):
                GenerationController(self.inputs['slots'][0], linked / 'session')

    def test_packet_and_summary_are_defensive_copies(self):
        c = self.controller(); packet = c.task_packet(); packet['family'] = 'bad'
        self.assertEqual(c.task_packet()['family'], 'planning')
        c.submit('P-select-1', 'pass', 0)
        c.summary()['candidate']['n_params'] = 12
        self.assertEqual(c.candidate['n_params'], 0)

    def test_controller_rejects_tampered_packet_hash_and_role(self):
        for kind in ('packet', 'role'):
            value = copy.deepcopy(self.inputs['slots'][0])
            if kind == 'packet': value['packet']['source'] = 'leaked'
            else: value['role'] = 'evaluation'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                GenerationController(value, self.output)

    def test_rebound_packet_cannot_expose_task_identifiers_or_original_columns(self):
        from rsi_eval.state_generation import digest
        variants = []
        planning = copy.deepcopy(self.inputs['slots'][0])
        planning['packet']['examples'][0]['task_id'] = 'spannerlearning/seed0/problem0'
        variants.append(planning)
        symbolic = copy.deepcopy(self.inputs['slots'][1])
        symbolic['packet']['input_names'] = ['t', 'x', 'v']
        variants.append(symbolic)
        dimension = copy.deepcopy(self.inputs['slots'][1])
        dimension['packet']['input_dimension'] = 4
        variants.append(dimension)
        interface = copy.deepcopy(self.inputs['slots'][0])
        interface['packet']['interface']['source'] = 'old program'
        variants.append(interface)
        for index, slot in enumerate(variants):
            slot['packet_sha256'] = digest(slot['packet'])
            with self.subTest(family=slot['family']), self.assertRaises(ValueError):
                GenerationController(slot, self.output / str(index))


if __name__ == '__main__':
    unittest.main()
