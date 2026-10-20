"""Offline contract tests for bounded whole-input replacement."""
import copy
import hashlib
import importlib.util
import json
import unittest


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def record(index, source, incumbent=None, *, failed=False):
    candidate_id = 'planning-' + str(index).zfill(3)
    incumbent = incumbent or (candidate_id, source)
    return {
        'candidate_id': candidate_id, 'source': source,
        'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
        'n_params': 0, 'status': 'evaluated', 'parent_id': None if index == 0 else 'planning-000',
        'origin': 'hand_authored_initial' if index == 0 else 'model_proposed',
        'rationale': 'revise directed move',
        'metrics': {'total_successes': 0 if failed else 1, 'total_tasks': 10},
        'results': [{'task_id': 'spannerlearning/seed0/problem0',
                     'status': 'candidate_error' if failed else 'task_failure',
                     'error_kind': 'python_exception' if failed else 'invalid_plan',
                     'candidate_line': 12,
                     'diagnostics': {'version': 'diagnostics-v0.1',
                         'task_id': 'spannerlearning/seed0/problem0',
                         'candidate_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
                         'scope': 'public_prompt',
                         'evidence_ids': ['spannerlearning/seed0/problem0:trace',
                                          'spannerlearning/seed0/problem0:plan_replay'],
                         'trace': {'lines': [{'line': 1, 'hits': 1000}] * 10000},
                         'plan_replay': {'status': 'precondition_failure',
                             'missing_preconditions': [['link', 'a', 'b']]}}}],
        'selection': {'accepted': incumbent[0] == candidate_id,
                      'incumbent_id': incumbent[0], 'incumbent_source': incumbent[1],
                      'instruction': 'Revise the selected incumbent next.'},
        'generated_candidates_used': index, 'generated_candidates_remaining': 3 - index,
    }


class StatePacketTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.find_spec('rsi_eval.state_packet')
        self.assertIsNotNone(spec, 'Whole-input state packet implementation is missing')
        from rsi_eval import state_packet
        self.module = state_packet
        self.records = [record(0, '# baseline\ndef solve(task):\n    return []\n')]

    def build(self, **updates):
        args = dict(session_id='run:planning_A', task_text='固定任务与接口。',
                    public_examples=[{'task_id': 'public-0', 'objects': ['a', 'b']}],
                    records=self.records, evidence=[], audits=[], checks_visible=False)
        args.update(updates)
        return self.module.build_state_packet(**args)

    def test_replaces_arbitrarily_long_old_history_without_duplicate_source(self):
        source = self.records[0]['source']
        self.records += [record(i, '# rejected ' + str(i), ('planning-000', source), failed=True)
                         for i in range(1, 4)]
        packet = self.build()
        old = [{'role': 'system', 'content': [{'type': 'text', 'text': 'system'}]},
               {'role': 'developer', 'content': 'fixed policy'}]
        old += [{'role': role, 'content': source * 3000} for role in
                ('user', 'assistant', 'tool', 'reasoning')] * 8
        new = self.module.replace_messages(old, packet)
        self.assertEqual([message['role'] for message in new], ['system', 'developer', 'user'])
        self.assertEqual(json.loads(new[-1]['content']), packet)
        self.assertEqual(new[-1]['content'].count(json.dumps(source)[1:-1]), 1)
        self.assertLess(len(new[-1]['content'].encode('utf-8')), 10000)
        new[0]['content'][0]['text'] = 'changed'
        self.assertEqual(old[0]['content'][0]['text'], 'system')

    def test_failed_latest_feedback_survives_while_older_incumbent_is_retained(self):
        source = self.records[0]['source']
        self.records.append(record(1, 'raise RuntimeError()', ('planning-000', source), failed=True))
        packet = self.build()
        self.assertEqual(packet['incumbent']['candidate_id'], 'planning-000')
        self.assertEqual(packet['incumbent']['source'], source)
        self.assertEqual(packet['latest_candidate']['candidate_id'], 'planning-001')
        self.assertEqual(packet['latest_candidate']['results'][0]['status'], 'candidate_error')
        self.assertEqual(packet['latest_candidate']['results'][0]['error_kind'], 'python_exception')
        self.assertFalse(packet['latest_candidate']['accepted'])
        self.assertEqual(packet['generated_candidates_remaining'], 2)
        self.assertEqual(packet['selection_instruction'], 'Revise the selected incumbent next.')

    def test_all_four_candidates_have_compact_source_free_history(self):
        self.records += [record(i, '# candidate ' + str(i)) for i in range(1, 4)]
        packet = self.build()
        self.assertEqual([row['candidate_id'] for row in packet['history']],
                         ['planning-000', 'planning-001', 'planning-002', 'planning-003'])
        self.assertEqual(packet['history'][1]['score'], {'total_successes': 1, 'total_tasks': 10})
        for row in packet['history']:
            self.assertNotIn('source', row)
            self.assertNotIn('rationale', row)
            self.assertEqual(len(row['source_sha256']), 64)

    def test_host_diagnostics_retained_and_candidate_trace_removed(self):
        packet = self.build()
        diagnostic = packet['latest_candidate']['results'][0]['diagnostics']
        self.assertEqual(diagnostic['plan_replay']['missing_preconditions'], [['link', 'a', 'b']])
        self.assertNotIn('trace', diagnostic)
        self.assertEqual(diagnostic['evidence_ids'], ['spannerlearning/seed0/problem0:plan_replay'])
        self.assertTrue(packet['metadata']['omitted_trace'])
        self.assertEqual(packet['metadata']['persisted_files'], ['candidates.json', 'diagnostics.json'])
        self.assertEqual(packet['metadata']['records_sha256'], digest(self.records))

    def test_symbolic_residuals_and_nonzero_parameter_count_retained(self):
        self.records[0]['n_params'] = 3
        self.records[0]['metrics'] = {'mse': 0.2, 'nmse': 0.1}
        diagnostic = self.records[0]['results'][0]['diagnostics']
        diagnostic.pop('plan_replay')
        diagnostic['residuals'] = {'status': 'ok', 'bias': -0.01, 'standardized_bias': 0.02,
                                   'standardized_bias_reason': None, 'inputs': []}
        packet = self.build(public_examples=[])
        self.assertEqual(packet['incumbent']['n_params'], 3)
        self.assertEqual(packet['latest_candidate']['results'][0]['diagnostics']['residuals']['bias'], -0.01)
        self.assertEqual(packet['history'][0]['score'], {'mse': 0.2, 'nmse': 0.1})

    def test_real_controller_records_need_no_top_level_source(self):
        del self.records[0]['source']
        packet = self.build()
        self.assertEqual(packet['incumbent']['source'], self.records[0]['selection']['incumbent_source'])

    def test_explicit_incumbent_candidate_id_alias_supported(self):
        selected = self.records[0]['selection']
        selected['incumbent_candidate_id'] = selected.pop('incumbent_id')
        self.assertEqual(self.build()['incumbent']['candidate_id'], 'planning-000')

    def test_baseline_without_selection_uses_verified_baseline_source(self):
        del self.records[0]['selection']
        self.assertEqual(self.build()['incumbent']['source'], self.records[0]['source'])

    def test_source_hash_mismatch_and_disagreement_fail_closed(self):
        for mutate in ('hash', 'source'):
            records = copy.deepcopy(self.records)
            if mutate == 'hash':
                records[0]['source_sha256'] = '0' * 64
            else:
                records[0]['source'] += 'tampered'
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.build(records=records)

    def test_missing_or_unknown_incumbent_source_fails_closed(self):
        records = copy.deepcopy(self.records)
        del records[0]['source']
        del records[0]['selection']['incumbent_source']
        with self.assertRaises(ValueError): self.build(records=records)
        self.records[0]['selection']['incumbent_id'] = 'unknown'
        with self.assertRaises(ValueError): self.build()

    def test_source_limit_counts_utf8_bytes_and_never_truncates(self):
        self.records = [record(0, '中' * 6)]
        self.assertEqual(self.build(max_source_bytes=18)['incumbent']['source'], '中' * 6)
        with self.assertRaises(ValueError): self.build(max_source_bytes=17)
        self.records = [record(0, 'x' * 16385)]
        with self.assertRaises(ValueError): self.build()

    def test_rationale_is_bounded_and_not_silently_truncated(self):
        self.records[0]['rationale'] = '中' * 2000
        self.assertEqual(len(self.build()['latest_candidate']['rationale']), 2000)
        self.records[0]['rationale'] += 'x'
        with self.assertRaises(ValueError): self.build()

    def test_hidden_audits_have_no_values_hash_or_size_sidechannel(self):
        first = [{'outcome': 'contradicted', 'reason': 'PRIVATE_REASON', 'actual': 17}]
        second = [{'outcome': 'supported', 'reason': 'DIFFERENT_PRIVATE_REASON', 'actual': 999}] * 3
        packet = self.build(audits=first)
        self.assertEqual(packet, self.build(audits=second))
        serialized = json.dumps(packet)
        for secret in ('PRIVATE_REASON', 'contradicted', 'actual', 'audits_sha256'):
            self.assertNotIn(secret, serialized)
        self.assertNotIn('audits', packet)

    def test_visible_audits_are_preserved_with_digest_and_detached(self):
        audits = [{'candidate_id': 'planning-000', 'claim_results': [{'outcome': 'contradicted',
                    'reason': 'direction differs', 'actual': False}]}]
        packet = self.build(audits=audits, checks_visible=True)
        self.assertEqual(packet['audits'], audits)
        self.assertEqual(packet['metadata']['audits_sha256'], digest(audits))
        packet['audits'][0]['claim_results'][0]['actual'] = True
        self.assertFalse(audits[0]['claim_results'][0]['actual'])

    def test_evidence_is_preserved_and_hashed_without_mutating_input(self):
        evidence = [{'binding': {'candidate_id': 'planning-000', 'scope': 'public_prompt'},
                     'scalars': {'score': 0.1}, 'facts': {'link': [['a', 'b']]}}]
        packet = self.build(evidence=evidence)
        self.assertEqual(packet['evidence'], evidence)
        self.assertEqual(packet['metadata']['evidence_sha256'], digest(evidence))
        packet['evidence'][0]['facts']['link'][0][0] = 'changed'
        self.assertEqual(evidence[0]['facts']['link'][0][0], 'a')

    def test_fixed_context_is_preserved_exactly(self):
        text = '中\nquote " backslash \\ and tab\t'
        examples = [{'objects': ['甲', '乙'], 'goal': [['at', '甲']]}]
        packet = self.build(task_text=text, public_examples=examples)
        self.assertEqual(packet['task_text'], text)
        self.assertEqual(packet['public_examples'], examples)

    def test_limits_and_invalid_json_values_fail_closed(self):
        bad_inputs = [{'records': []}, {'records': self.records * 5},
                      {'evidence': [{}] * 7}, {'audits': [{}] * 4, 'checks_visible': True},
                      {'public_examples': [{}, {}, {}]}, {'task_text': 'x' * 32769},
                      {'evidence': [{'scalars': {'x': float('nan')}}]},
                      {'evidence': [{'scalars': {'x': float('inf')}}]},
                      {'evidence': [{'facts': {'x': ['y'] * 257}}]},
                      {'max_source_bytes': True}, {'checks_visible': 'false'}]
        for updates in bad_inputs:
            with self.subTest(updates=str(updates)[:60]), self.assertRaises(ValueError):
                self.build(**updates)

    def test_payload_bytes_match_budget_canonical_utf8_with_json_escaping(self):
        payload = self.module.wire_payload('中', [{'role': 'user', 'content': '"\\\n'}], None, None, 4)
        expected = '{"max_output_tokens":4,"messages":[{"content":"\\"\\\\\\n","role":"user"}],"model":"中","tool_choice":null,"tools":null}'
        self.assertEqual(self.module.payload_bytes(payload), len(expected.encode('utf-8')))
        self.assertEqual(payload, json.loads(expected))
        with self.assertRaises(ValueError): self.module.payload_bytes({'x': float('nan')})

    def test_wire_payload_and_messages_are_copied_without_mutation(self):
        messages = [{'role': 'user', 'content': 'hello'}]
        tools = [{'type': 'function', 'function': {'name': 'submit_candidate'}}]
        payload = self.module.wire_payload('model', messages, tools, 'auto', 4096)
        payload['messages'][0]['content'] = 'changed'
        payload['tools'][0]['function']['name'] = 'changed'
        self.assertEqual(messages[0]['content'], 'hello')
        self.assertEqual(tools[0]['function']['name'], 'submit_candidate')


if __name__ == '__main__':
    unittest.main()
