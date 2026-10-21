"""Behavioral checks for descriptive grouping; no model or candidate execution."""
import unittest
from audit import source_facts, summarize_rows, group_rows, transport_identity


def row(slot, request='same', state='state', tasks=('a',), success=0, nmse=None):
    return dict(slot_id=slot, request_sha256=request, state_id=state,
                task_ids=list(tasks), family='symbolic' if nmse is not None else 'planning',
                successes=success, nmse=nmse, source_sha256=slot, policy_sha256='policy')


class OfflineAuditTests(unittest.TestCase):
    def test_comments_do_not_change_ast(self):
        self.assertEqual(source_facts('x = 1')['ast_sha256'],
                         source_facts('# comment\nx=1\n')['ast_sha256'])

    def test_docstring_is_ignored_only_in_explicit_view(self):
        a=source_facts('def f(x):\n    "old"\n    return x\n')
        b=source_facts('def f(x):\n    "new"\n    return x\n')
        self.assertNotEqual(a.get('ast_sha256'),b.get('ast_sha256'))
        self.assertEqual(a.get('ast_without_docstrings_sha256'),b.get('ast_without_docstrings_sha256'))

    def test_arithmetic_edit_is_not_hidden(self):
        self.assertNotEqual(source_facts('x=1').get('ast_without_docstrings_sha256'),
                            source_facts('x=2').get('ast_without_docstrings_sha256'))

    def test_syntax_error_remains_an_observation(self):
        self.assertEqual(source_facts('def broken(').get('syntax_valid'), False)

    def test_exact_request_repeat_grouping(self):
        groups=group_rows([row('a'),row('b'),row('c',request='changed')])
        self.assertEqual(sorted(g['n_generations'] for g in groups),[1,2])

    def test_identical_input_different_task_sets_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'task'):
            group_rows([row('a'),row('b',tasks=('b',))])

    def test_same_policy_different_request_not_pooled(self):
        self.assertEqual(len(group_rows([row('a',request='x'),row('b',request='y')])),2)

    def test_three_generations_are_not_three_tasks(self):
        out=summarize_rows([row('a',tasks=('a','b'),success=0),
                            row('b',tasks=('a','b'),success=2),
                            row('c',tasks=('a','b'),success=0)])
        self.assertEqual(out.get('n_generations'),3)
        self.assertEqual(out.get('tasks_per_generation'),2)
        self.assertEqual(out.get('successes_range'),[0,2])

    def test_missing_nmse_is_not_zero(self):
        a=row('a',nmse=0.4); b=row('b',nmse=0.6); c=row('c'); c['family']='symbolic'
        out=summarize_rows([a,b,c])
        self.assertEqual(out.get('numeric_nmse_count'),2)
        self.assertEqual(out.get('missing_nmse_count'),1)
        self.assertEqual(out.get('nmse_range'),[0.4,0.6])

    def test_source_is_parsed_without_execution(self):
        out=source_facts('raise RuntimeError("must not execute")')
        self.assertTrue(out.get('syntax_valid'))

    def test_different_evaluator_is_not_pooled(self):
        a=row('a'); b=row('b'); a['evaluation_identity']='x'; b['evaluation_identity']='y'
        with self.assertRaisesRegex(ValueError,'evaluator'):
            group_rows([a,b])

    def test_duplicate_generation_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            group_rows([row('a'),row('a')])

    def test_transport_timeout_is_part_of_identity(self):
        d={'observed':{},'request_sha256':'x','request_file':'requests/a.request.json'}
        t={'request_sha256':'x','request_file':'requests/a.request.json','timeout_seconds':180}
        ref={'sha256':'x','path':'session/requests/a.request.json'}
        self.assertNotEqual(transport_identity(d,t,ref),transport_identity(d,dict(t,timeout_seconds=60),ref))

    def test_transport_wrong_request_binding_is_rejected(self):
        d={'observed':{},'request_sha256':'x','request_file':'requests/a.request.json'}
        t={'request_sha256':'y','request_file':'requests/a.request.json'}
        with self.assertRaisesRegex(ValueError,'request'):
            transport_identity(d,t,{'sha256':'x','path':'session/requests/a.request.json'})

    def test_transport_filenames_do_not_split_identical_settings(self):
        d={'observed':{},'request_sha256':'x','request_file':'requests/a.request.json'}
        t={'request_sha256':'x','request_file':'requests/a.request.json','timeout_seconds':180}
        a=transport_identity(d,t,{'sha256':'x','path':'session/requests/a.request.json'})
        d['request_file']=t['request_file']='requests/b.request.json'
        b=transport_identity(d,t,{'sha256':'x','path':'session/requests/b.request.json'})
        self.assertEqual(a,b)


if __name__=='__main__':
    unittest.main()
