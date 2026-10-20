"""Read-only audit rejects coherent-looking changes to recorded probe labels."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'artifacts/intervention-probes/2026-10-21/v01'
NEGATIVE_CASES = {
    'planning_joint_label': 'Change the planning verdict, reason and next scope in summary and sidecar together.',
    'normalized_action_token': 'Change an action token in the normalized plan in both records, preserving the original.',
    'patch_source': 'Append an unrelated source change to the saved format patch.',
    'symbolic_delta': 'Change the saved NMSE delta and its verdict/scope together without changing component scores.',
    'symbolic_epsilon': 'Change the probe engineering threshold in both records.',
    'symbolic_parent': 'Change the executor parent binding in both records.',
    'symbolic_hash': 'Change the executor candidate hash in both records.',
    'symbolic_dimension': 'Change the fitted parameter dimension in both records.',
    'execution_counts': 'Increase probe, summary and budget counts together while retaining execution phase lists.',
    'frozen_file_missing': 'Remove one required module from the freeze hash map.',
    'frozen_git_hash': 'Replace a frozen module hash with a digest inconsistent with its Git object.',
    'next_edit_scope': 'Broaden a supported planning action scope in both records.'}


def archive_hashes(directory):
    return {p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


def mutate_copy(directory, name):
    """Mutate only a disposable copied archive; never the historical source."""
    if directory.resolve() == ARCHIVE.resolve():
        raise ValueError('Cannot mutate the real archive')
    def read(relative):
        return json.loads((directory/relative).read_bytes())
    def write(relative, value):
        (directory/relative).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                                  allow_nan=False)+'\n', encoding='utf-8')
    summary=read('summary.json')
    planning=summary['planning'][0]['results'][0]
    symbolic=summary['symbolic'][0]['result']
    if name == 'planning_joint_label':
        planning.update(verdict='contradicted',reason='edge_normalization_insufficient_on_this_plan')
        planning['next_edit_scope']['action']='formatting_not_sufficient_check_semantics'
    elif name == 'normalized_action_token':
        action=planning['normalization']['normalized'][0]
        planning['normalization']['normalized'][0]=action.replace('(', '(changed_', 1)
    elif name == 'patch_source':
        with (directory/'format-patch/candidate.py').open('ab') as stream:
            stream.write(b'\nAUDIT_UNRELATED_CHANGE = True\n')
    elif name == 'symbolic_delta':
        symbolic.update(delta_nmse=0.0,verdict='contradicted',reason='removal_loss_below_threshold')
        symbolic['next_edit_scope']['action']='consider_evaluated_term_removal'
    elif name == 'symbolic_epsilon':
        symbolic['epsilon'] *= 2
    elif name == 'symbolic_parent':
        symbolic['variants'][0]['result']['parent_id']='0'*64
    elif name == 'symbolic_hash':
        symbolic['variants'][0]['result']['candidate_hash']='0'*64
    elif name == 'symbolic_dimension':
        symbolic['variants'][0]['result']['fitting']['n_params'] += 1
    elif name == 'execution_counts':
        symbolic['executions']['sandbox_calls'] += 1
        symbolic['sandbox_executions'] += 1
        summary['counts']['sandbox_calls'] += 1
        summary['budget']['actual'] += 1
        summary['budget']['reserved'] += 1
    elif name in ('frozen_file_missing', 'frozen_git_hash'):
        freeze=read('freeze.json')
        if name == 'frozen_file_missing':
            del freeze['runtime_files_sha256']['rsi_eval/planning_probe.py']
        else:
            freeze['runtime_files_sha256']['rsi_eval/planning_probe.py']='0'*64
        write('freeze.json',freeze)
    elif name == 'next_edit_scope':
        planning['next_edit_scope']['scope']='all_planning_tasks'
    else:
        raise ValueError('Unknown negative case')
    write('summary.json',summary)
    write('planning/'+summary['planning'][0]['id']+'/public-0.json',planning)
    write('symbolic/'+summary['symbolic'][0]['id']+'/probe.json',symbolic)


def negative_case_result(name):
    module=importlib.import_module('scripts.analyze_intervention_probes')
    with tempfile.TemporaryDirectory(prefix='intervention-negative-') as tmp:
        directory=Path(tmp)/'archive-copy'
        shutil.copytree(ARCHIVE,directory)
        mutate_copy(directory,name)
        try:
            module.audit(ROOT,directory)
        except ValueError as exc:
            return {'case':name,'mutation':NEGATIVE_CASES[name],
                    'rejected':True,'exception_type':type(exc).__name__,'reason':str(exc)}
    return {'case':name,'mutation':NEGATIVE_CASES[name],'rejected':False,
            'exception_type':None,'reason':'Audit unexpectedly accepted mutation'}


class InterventionAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.m=importlib.import_module('scripts.analyze_intervention_probes')

    def test_scope_follows_verdict_without_claiming_generalization(self):
        for family,verdict,action in (
            ('planning','supported','consider_format_patch_under_AST_contract'),
            ('planning','contradicted','formatting_not_sufficient_check_semantics'),
            ('symbolic','supported','retain_selected_term_under_fixed_train_protocol'),
            ('symbolic','contradicted','consider_evaluated_term_removal'),
            ('symbolic','unknown','no_term_value_decision')):
            with self.subTest(family=family,verdict=verdict):
                result=self.m.expected_scope(family,{'verdict':verdict,'task_id':'p0'})
                self.assertEqual(result['action'],action)
                self.assertIn('held_out_generalization',result['excludes'])

    def test_planning_verdict_is_derived_from_both_recorded_checks(self):
        raw={'validation':{'status':'invalid_output'},'replay':{'status':'invalid_output'}}
        normalized={'validation':{'status':'success'},'replay':{'status':'valid'}}
        self.assertEqual(self.m.planning_verdict(raw,normalized,True),
                         ('supported','edge_normalization_sufficient_on_this_plan'))
        normalized['validation']['status']='task_failure';normalized['replay']['status']='goal_unsatisfied'
        self.assertEqual(self.m.planning_verdict(raw,normalized,True)[0],'contradicted')
        raw['validation']['status']='success';raw['replay']['status']='valid'
        self.assertEqual(self.m.planning_verdict(raw,normalized,True)[0],'unknown')

    def test_symbolic_threshold_negative_delta_and_boundary_are_distinct(self):
        self.assertEqual(self.m.symbolic_verdict(2e-5,1e-5,1e-10)[0],'supported')
        self.assertEqual(self.m.symbolic_verdict(1e-7,1e-5,1e-10)[0],'contradicted')
        self.assertEqual(self.m.symbolic_verdict(1e-5,1e-5,1e-10)[1],'threshold_boundary')
        self.assertEqual(self.m.symbolic_verdict(-1e-4,1e-5,1e-10)[1],'nested_fit_inconsistent')

    def test_validator_replay_disagreement_and_fake_validator_are_rejected(self):
        good={'validation':{'status':'success','plan_length':1,'validator':{'status':'valid'}},
              'replay':{'status':'valid','plan_length':1,'executed_actions':1,
                        'first_failed_action':None,'unsatisfied_goals':[]}}
        self.m.check_validation(good,['(walk a b c)'])
        for value in ('goal_unsatisfied','invalid_output'):
            bad=copy.deepcopy(good);bad['replay']['status']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.m.check_validation(bad,['(walk a b c)'])
        bad=copy.deepcopy(good);bad['validation']['validator']['status']='invalid'
        with self.assertRaises(ValueError):self.m.check_validation(bad,['(walk a b c)'])

    def test_success_with_unexecuted_actions_is_rejected(self):
        observation={'validation':{'status':'success','plan_length':2,'validator':{'status':'valid'}},
            'replay':{'status':'valid','plan_length':2,'executed_actions':1,
                      'first_failed_action':None,'unsatisfied_goals':[]}}
        with self.assertRaises(ValueError):self.m.check_validation(observation,['(a b)','(c d)'])

    def test_metrics_require_matching_normalization_and_finite_numbers(self):
        self.assertEqual(self.m.metric_pair({'mse':0.2,'nmse':0.1}), (0.2,0.1))
        for metrics in ({'mse':float('nan'),'nmse':0.1},{'mse':0.0,'nmse':0.1},
                        {'mse':0.1,'nmse':True},{'mse':-1,'nmse':-1}):
            with self.subTest(metrics=metrics),self.assertRaises(ValueError):
                self.m.metric_pair(metrics)

    def test_json_reader_rejects_duplicates_nonfinite_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'record.json'
            for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1e999}'):
                p.write_bytes(raw)
                with self.assertRaises(ValueError):self.m.read(root,'record.json')
            with self.assertRaises(ValueError):self.m.read(root,'../record.json')

    def test_complete_budget_cannot_exceed_reserved_or_limit(self):
        counts={k:0 for k in self.m.COUNT_KEYS};counts['sandbox_calls']=8
        good={'maximum':40,'reserved':12,'actual':8}
        self.m.check_budget(good,counts,12,40)
        for bad in ({'maximum':40,'reserved':7,'actual':8},
                    {'maximum':40,'reserved':12,'actual':7},
                    {'maximum':41,'reserved':12,'actual':8}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                self.m.check_budget(bad,counts,12,40)


class RealInterventionArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=archive_hashes(ARCHIVE)
        if not cls.original:
            raise AssertionError('The real intervention archive is missing')

    @classmethod
    def tearDownClass(cls):
        if archive_hashes(ARCHIVE) != cls.original:
            raise AssertionError('The real archive changed during read-only regression tests')

    def test_real_archive_matches_manifest_and_passes_read_only_audit(self):
        module=importlib.import_module('scripts.analyze_intervention_probes')
        manifest=json.loads((ARCHIVE/'manifest.json').read_bytes())
        self.assertEqual(manifest['raw_file_count'],31)
        for name,digest in manifest['raw_files'].items():
            self.assertEqual(self.original[name],digest,name)
        result=module.audit(ROOT,ARCHIVE)
        self.assertEqual(result['status'],'verified_complete')
        self.assertEqual(result['runtime_commit'],'b1f4f81752fc9a162a030c4055a24f80f43733c4')
        self.assertEqual(result['candidate_executions_by_auditor'],0)
        self.assertEqual(result['model_calls'],0)
        self.assertEqual(result['sealed_data_reads'],0)


def _negative_test(name):
    def test(self):
        result=negative_case_result(name)
        self.assertTrue(result['rejected'],result)
        self.assertTrue(result['reason'])
    return test


for _name in NEGATIVE_CASES:
    setattr(RealInterventionArchiveTests,'test_reject_'+_name,_negative_test(_name))


if __name__=='__main__':unittest.main()
