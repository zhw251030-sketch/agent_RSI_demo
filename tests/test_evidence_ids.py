"""Exact, session-scoped evidence handles preserve existing checker semantics."""

import copy
import importlib
import importlib.util
import json
import math
import unittest
from unittest.mock import patch

from rsi_eval import evidence_checks


class EvidenceIdTests(unittest.TestCase):
    def setUp(self):
        if importlib.util.find_spec('rsi_eval.evidence_ids') is None:
            self.fail('The trusted short evidence registry is not implemented')
        self.module = importlib.import_module('rsi_eval.evidence_ids')
        self.binding = {'session_id': 'session-1', 'candidate_id': 'parent',
                        'candidate_sha256': 'a' * 64, 'task_id': 'task-1',
                        'version': 'evidence-v0.1', 'scope': 'development'}
        self.snapshot = {'binding': copy.deepcopy(self.binding),
                         'scalars': {'loss': 0.5, 'unavailable': None},
                         'facts': {'edges': [['from', 'a', 'b']], 'empty': []}}

    def registry(self, snapshots=None, session_id='session-1'):
        return self.module.EvidenceRegistry(
            [self.snapshot] if snapshots is None else snapshots, session_id=session_id)

    def identifier(self, registry, key='loss', candidate_id='parent'):
        return next(entry['evidence_id'] for entry in registry.entries()
                    if entry['key'] == key and entry['candidate_id'] == candidate_id)

    def claim(self, registry, key='loss', op='eq', value=0.5):
        return {'evidence_id': self.identifier(registry, key), 'op': op, 'value': value}

    def prediction(self, registry, key='loss'):
        return {'evidence_id': self.identifier(registry, key),
                'direction': 'decrease', 'min_delta': 0.1}

    def test_compact_scalar_is_expanded_to_exact_full_reference(self):
        registry = self.registry()
        result = registry.expand_claim(self.claim(registry))
        self.assertEqual(result, {'status': 'resolved', 'value': {
            'kind': 'scalar', 'reference': {**self.binding, 'key': 'loss'},
            'op': 'eq', 'value': 0.5}})
        report = registry.check_claim(self.claim(registry))
        self.assertEqual(report['status'], 'supported')
        self.assertEqual(report['actual'], 0.5)
        self.assertEqual(report['reference'], {**self.binding, 'key': 'loss'})

    def test_fact_kind_comes_from_registry_and_keeps_edge_direction(self):
        registry = self.registry()
        forward = self.claim(registry, 'edges', 'contains', ['from', 'a', 'b'])
        reverse = self.claim(registry, 'edges', 'contains', ['from', 'b', 'a'])
        self.assertEqual(registry.expand_claim(forward)['value']['kind'], 'fact')
        self.assertEqual(registry.check_claim(forward)['status'], 'supported')
        self.assertEqual(registry.check_claim(reverse)['status'], 'contradicted')
        self.assertEqual(registry.check_claim(self.claim(
            registry, 'empty', 'not_contains', ['from', 'a', 'b']))['status'], 'supported')

    def test_prediction_registration_survives_explicit_child_check(self):
        registry = self.registry()
        prediction = self.prediction(registry)
        self.assertEqual(registry.expand_prediction(prediction), {'status': 'resolved', 'value': {
            'reference': {**self.binding, 'key': 'loss'},
            'direction': 'decrease', 'min_delta': 0.1}})
        registered = registry.register_prediction(prediction)
        self.assertEqual(registered['reason'], 'prediction_registered')
        self.assertEqual(registered['before'], 0.5)
        child = copy.deepcopy(self.snapshot)
        child['binding'].update(candidate_id='child', candidate_sha256='b' * 64)
        child['scalars']['loss'] = 0.44
        report = evidence_checks.check_prediction(registered, [child])
        self.assertEqual(report['status'], 'contradicted')
        self.assertAlmostEqual(report['actual'], 0.06)

    def test_unknown_valid_id_is_unavailable_without_fuzzy_lookup(self):
        registry = self.registry()
        unknown = 'e_' + '0' * 16
        claim = {**self.claim(registry), 'evidence_id': unknown}
        prediction = {**self.prediction(registry), 'evidence_id': unknown}
        for result in [registry.expand_claim(claim), registry.check_claim(claim),
                       registry.expand_prediction(prediction), registry.register_prediction(prediction)]:
            self.assertEqual(result, {'status': 'unavailable', 'reason': 'reference_not_found'})

    def test_omitted_parent_is_stale_even_if_it_was_previously_visible(self):
        original = self.registry()
        old_claim = self.claim(original)
        child = copy.deepcopy(self.snapshot)
        child['binding'].update(candidate_id='child', candidate_sha256='b' * 64)
        newer = self.registry([child])
        self.assertEqual(newer.check_claim(old_claim)['status'], 'unavailable')

    def test_cross_session_identifier_cannot_resolve(self):
        original = self.registry()
        other = copy.deepcopy(self.snapshot)
        other['binding']['session_id'] = 'session-2'
        registry = self.registry([other], session_id='session-2')
        self.assertEqual(registry.check_claim(self.claim(original))['status'], 'unavailable')
        self.assertNotEqual(self.identifier(original), self.identifier(registry))

    def test_each_binding_field_changes_identity(self):
        original_id = self.identifier(self.registry())
        for key, value in [('candidate_id', 'different'), ('candidate_sha256', 'b' * 64),
                           ('task_id', 'other-task'), ('scope', 'other-scope')]:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.snapshot)
                changed['binding'][key] = value
                registry = self.registry([changed])
                identifier = self.identifier(registry, candidate_id=changed['binding']['candidate_id'])
                self.assertNotEqual(original_id, identifier)
                self.assertEqual(registry.check_claim({
                    'evidence_id': original_id, 'op': 'eq', 'value': 0.5})['status'], 'unavailable')

    def test_ordering_does_not_change_handles_or_display_order(self):
        other = copy.deepcopy(self.snapshot)
        other['binding'].update(task_id='other-task')
        first = self.registry([self.snapshot, other])
        reordered = copy.deepcopy(self.snapshot)
        reordered['binding'] = dict(reversed(list(reordered['binding'].items())))
        reordered['scalars'] = dict(reversed(list(reordered['scalars'].items())))
        reordered['facts'] = dict(reversed(list(reordered['facts'].items())))
        second = self.registry([other, reordered])
        self.assertEqual(first.entries(), second.entries())
        self.assertEqual(first.export_manifest(), second.export_manifest())
        for entry in first.entries():
            self.assertRegex(entry['evidence_id'], r'^e_[0-9a-f]{16}$')

    def test_display_omits_binding_secrets_but_archive_preserves_them(self):
        registry = self.registry()
        entries = registry.entries()
        self.assertEqual(len(entries), 4)
        for entry in entries:
            self.assertEqual(set(entry), {'evidence_id', 'candidate_id', 'task_id',
                                         'scope', 'key', 'kind', 'value'})
        serialized = json.dumps(entries)
        self.assertNotIn('session-1', serialized)
        self.assertNotIn('a' * 64, serialized)
        manifest = registry.export_manifest()
        self.assertEqual(manifest['version'], 'evidence-ids-v0.1')
        self.assertEqual(manifest['session_id'], 'session-1')
        self.assertEqual(manifest['entries'][self.identifier(registry)], {
            'reference': {**self.binding, 'key': 'loss'}, 'kind': 'scalar', 'value': 0.5})

    def test_registry_and_all_exported_objects_are_defensive_copies(self):
        registry = self.registry()
        claim = self.claim(registry)
        self.snapshot['scalars']['loss'] = 9.0
        self.snapshot['facts']['edges'][0][1] = 'mutated'
        view = registry.entries()
        for entry in view:
            if entry['key'] == 'loss':
                entry['value'] = 8.0
            if entry['key'] == 'edges':
                entry['value'][0][1] = 'mutated'
        manifest = registry.export_manifest()
        manifest['entries'][claim['evidence_id']]['reference']['task_id'] = 'mutated'
        expanded = registry.expand_claim(claim)
        expanded['value']['reference']['task_id'] = 'mutated'
        self.assertEqual(registry.check_claim(claim)['actual'], 0.5)
        self.assertEqual(registry.check_claim(self.claim(
            registry, 'edges', 'contains', ['from', 'a', 'b']))['status'], 'supported')

    def test_none_and_fact_predictions_keep_existing_unavailability_semantics(self):
        registry = self.registry()
        self.assertEqual(registry.check_claim(self.claim(registry, 'unavailable'))['reason'],
                         'value_unavailable')
        self.assertEqual(registry.register_prediction(self.prediction(
            registry, 'unavailable'))['reason'], 'value_unavailable')
        self.assertEqual(registry.register_prediction(self.prediction(
            registry, 'edges'))['reason'], 'key_missing')

    def test_compact_schema_never_repairs_or_ignores_extra_fields(self):
        registry = self.registry()
        valid = self.claim(registry)
        cases = [None, [], {**valid, 'reference': {**self.binding, 'key': 'loss'}},
                 {**valid, 'kind': 'scalar'}, {k: v for k, v in valid.items() if k != 'value'},
                 {**valid, 'op': 'approximately'}, {**valid, 'value': '0.5'},
                 {**valid, 'value': True}, {**valid, 'value': math.nan},
                 {**valid, 'value': math.inf}, {**valid, 'value': 10 ** 400},
                 {**valid, 'op': 'contains', 'value': ['from', 'a', 'b']},
                 self.claim(registry, 'edges', 'eq', 0.5),
                 self.claim(registry, 'edges', 'contains', []),
                 self.claim(registry, 'edges', 'contains', ['from', 1])]
        for value in cases:
            with self.subTest(value_type=type(value).__name__):
                self.assertEqual(registry.expand_claim(value),
                                 {'status': 'schema_invalid', 'reason': 'claim_schema_invalid'})

    def test_compact_prediction_schema_is_closed_and_numeric(self):
        registry = self.registry()
        valid = self.prediction(registry)
        cases = [None, [], {**valid, 'reference': {}},
                 {k: v for k, v in valid.items() if k != 'direction'},
                 {**valid, 'direction': 'unchanged'}]
        cases += [{**valid, 'min_delta': value}
                  for value in [-0.1, True, math.nan, math.inf, '0.1', 10 ** 400]]
        for value in cases:
            self.assertEqual(registry.expand_prediction(value),
                             {'status': 'schema_invalid', 'reason': 'prediction_schema_invalid'})

    def test_bad_ids_and_oversize_data_are_not_normalized_or_echoed(self):
        registry = self.registry()
        valid = self.claim(registry)
        identifier = valid['evidence_id']
        for bad in [None, True, 1, [], identifier.upper(), ' ' + identifier,
                    identifier + ' ', identifier[:-1], 'sensitive-' * 100000]:
            result = registry.expand_claim({**valid, 'evidence_id': bad})
            self.assertEqual(result['status'], 'schema_invalid')
            self.assertLess(len(json.dumps(result)), 200)
            self.assertNotIn('sensitive', json.dumps(result))
        result = registry.expand_claim({**valid, 'private': 'sensitive-' * 100000})
        self.assertNotIn('sensitive', json.dumps(result))

    def test_duplicate_bindings_fail_closed_even_when_values_agree(self):
        with self.assertRaises(ValueError):
            self.registry([self.snapshot, copy.deepcopy(self.snapshot)])

    def test_scalar_fact_key_collision_fails_before_model_display(self):
        self.snapshot['facts']['loss'] = [['from', 'a', 'b']]
        with self.assertRaises(ValueError):
            self.registry()

    def test_hash_collision_is_detected_without_overwriting_an_entry(self):
        # A real 64-bit-prefix collision is prohibitively costly to generate;
        # replace only the digest boundary and exercise production insertion.
        with patch.object(self.module, '_reference_id', return_value='e_' + '0' * 16):
            with self.assertRaisesRegex(ValueError, 'collision'):
                self.registry()

    def test_conflicting_hashes_for_one_candidate_fail_closed(self):
        changed = copy.deepcopy(self.snapshot)
        changed['binding'].update(task_id='task-2', candidate_sha256='b' * 64)
        with self.assertRaises(ValueError):
            self.registry([self.snapshot, changed])

    def test_invalid_snapshot_mixed_session_and_version_fail_closed(self):
        for field, value in [('session_id', 'other'), ('version', 'evidence-v0.2'),
                             ('candidate_sha256', 'invalid')]:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.snapshot)
                changed['binding'][field] = value
                with self.assertRaises(ValueError):
                    self.registry([changed])
        for snapshots in [None, {}, [self.snapshot] * 129,
                          [{**self.snapshot, 'private': 'secret'}],
                          [{**self.snapshot, 'scalars': {'loss': True}}]]:
            with self.assertRaises(ValueError):
                self.module.EvidenceRegistry(snapshots, session_id='session-1')
        for session in ['', None, 1, 'x' * 129]:
            with self.assertRaises(ValueError):
                self.registry(session_id=session)

    def test_empty_explicit_registry_has_no_implicit_evidence(self):
        registry = self.registry([])
        self.assertEqual(registry.entries(), [])
        self.assertEqual(registry.export_manifest()['entries'], {})
        self.assertEqual(registry.check_claim({'evidence_id': 'e_' + '0' * 16,
            'op': 'eq', 'value': 0.5})['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
