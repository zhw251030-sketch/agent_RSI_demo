import json
import sys
import unittest

from rsi_eval.planning_trace import CandidateTrace, sanitize_trace


class CandidateTraceTests(unittest.TestCase):
    def run_owned_fixture(self, source, limit=20000):
        # Only tiny hand-written test fixtures execute in-process here.
        scope = {}
        exec(compile(source, 'candidate.py', 'exec'), scope)
        trace = CandidateTrace(event_limit=limit)
        previous = sys.gettrace()
        with trace:
            scope['get_plan']()
        self.assertIs(sys.gettrace(), previous)
        return trace.snapshot()

    def test_records_candidate_lines_and_return_shapes_without_values(self):
        result = self.run_owned_fixture("def helper():\n    return None\ndef get_plan():\n    secret='PRIVATE VALUE'\n    helper()\n    return ['private action']\n")
        self.assertFalse(result['truncated'])
        self.assertFalse(result['interrupted'])
        helper = next(v for v in result['functions'] if v['name'] == 'helper')
        self.assertEqual(helper['call_events'], 1)
        self.assertEqual(helper['none_return_events'], 1)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('private action', json.dumps(result))
        self.assertTrue(all(1 <= row['line'] <= 6 for row in result['lines']))

    def test_trace_is_bounded_and_marks_incomplete_observation(self):
        result = self.run_owned_fixture("def get_plan():\n    for i in range(1000):\n        pass\n    return []\n", limit=20)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(result['events_seen'], 20)
        self.assertFalse(result['interrupted'])

    def test_detects_candidate_disabling_trace(self):
        result = self.run_owned_fixture("import sys\ndef get_plan():\n    sys.settrace(None)\n    return []\n")
        self.assertTrue(result['interrupted'])

    def test_restore_after_disabling_is_not_a_completeness_guarantee(self):
        result = self.run_owned_fixture('import sys\ndef get_plan():\n    hook=sys.gettrace()\n    sys.settrace(None)\n    hidden=1\n    sys.settrace(hook)\n    return []\n')
        self.assertFalse(result['interrupted'])
        self.assertIn('Missing hits do not prove nonexecution', result['interpretation_limits'])

    def test_generator_return_event_is_not_labeled_a_final_return(self):
        result = self.run_owned_fixture('def helper():\n    yield None\ndef get_plan():\n    list(helper())\n    return []\n')
        helper = next(v for v in result['functions'] if v['name'] == 'helper')
        self.assertEqual(helper['call_events'], 2)
        self.assertEqual(helper['none_return_events'], 2)
        self.assertIn('suspension/resumption', result['interpretation_limits'])

    def test_exception_is_counted_without_claiming_normal_return(self):
        scope = {}
        exec(compile("def get_plan():\n    raise ValueError('private')\n", 'candidate.py', 'exec'), scope)
        trace = CandidateTrace()
        with self.assertRaises(ValueError), trace:
            scope['get_plan']()
        result = trace.snapshot()
        self.assertEqual(result['functions'][0]['exception_events'], 1)
        self.assertNotIn('private', json.dumps(result))

    def test_ignores_frames_from_other_files(self):
        trace = CandidateTrace()
        with trace:
            sum(range(20))
        self.assertEqual(trace.snapshot()['lines'], [])
        self.assertEqual(trace.snapshot()['functions'], [])

    def test_host_sanitizer_rejects_arbitrary_fields_and_invalid_counts(self):
        result = self.run_owned_fixture('def get_plan():\n    return []\n')
        self.assertEqual(sanitize_trace(result), result)
        result['private'] = 'do not expose'
        self.assertIsNone(sanitize_trace(result))
        result.pop('private')
        result['lines'][0]['hits'] = -1
        self.assertIsNone(sanitize_trace(result))


if __name__ == '__main__':
    unittest.main()
