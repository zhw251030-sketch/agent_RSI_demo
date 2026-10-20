import copy
import tempfile
from pathlib import Path
import unittest

from scripts.analyze_decision_replay import validate_execution, validate_candidate
from scripts.run_decision_replay import COUNTS, read, write


class DecisionAuditTests(unittest.TestCase):
    def test_execution_counts_bind_actual_events_and_reservations(self):
        counts={k:0 for k in COUNTS};counts.update(sandbox_calls=2,new_candidate_executions=1,fit_calls=1,predict_calls=1)
        event={'label':'S-r1-hidden:oscillator1','reserved':2,'counts':counts,'complete':True}
        ledger={'max_sandbox_calls':96,'reserved_sandbox_calls':2,'events':[event]}
        summary={'actual':counts,'reserved_sandbox_calls':2,'accounting_complete':True}
        validate_execution(ledger,summary,counts,[('S-r1-hidden:oscillator1',2,counts)])
        for change in ('label','reserved','counts','complete'):
            bad=copy.deepcopy(ledger)
            bad['events'][0][change]={'label':'other','reserved':1,'counts':dict(counts,sandbox_calls=1),'complete':False}[change]
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_execution(bad,summary,counts,[('S-r1-hidden:oscillator1',2,counts)])

    def test_execution_count_swapping_between_events_rejected(self):
        first={k:0 for k in COUNTS};first.update(sandbox_calls=1,new_candidate_executions=1,host_validations=1)
        second=dict(first,val_calls=1)
        events=[dict(label='a',reserved=1,counts=second,complete=True),dict(label='b',reserved=1,counts=first,complete=True)]
        total={k:first[k]+second[k] for k in COUNTS}
        ledger=dict(max_sandbox_calls=96,reserved_sandbox_calls=2,events=events)
        summary=dict(actual=total,reserved_sandbox_calls=2,accounting_complete=True)
        with self.assertRaises(ValueError):validate_execution(ledger,summary,total,[('a',1,first),('b',1,second)])

    def test_incomplete_or_boolean_execution_accounting_rejected(self):
        zero={k:0 for k in COUNTS}
        base={'max_sandbox_calls':96,'reserved_sandbox_calls':0,'events':[]}
        summary={'actual':zero,'reserved_sandbox_calls':0,'accounting_complete':True}
        validate_execution(base,summary,zero,[])
        for change in ({'max_sandbox_calls':95},{'reserved_sandbox_calls':False}):
            with self.assertRaises(ValueError):validate_execution(dict(base,**change),summary,zero,[])

    def make_candidate(self,directory):
        from rsi_eval.two_stage_cases import load_cases
        from rsi_eval.decision_core import DecisionController,STRATEGY
        root=Path(__file__).resolve().parents[1]
        case=next(c for c in load_cases(root) if c['id']=='S-cubic')
        def evaluate(family,task_id,source,**kwargs):
            import hashlib
            return dict(task_id=task_id,family=family,candidate_hash=hashlib.sha256(source.encode()).hexdigest(),
                status='success',metrics={'nmse':case['baseline_results'][0]['metrics']['nmse']},
                parent_id=kwargs['parent_id'],candidate_id=kwargs['candidate_id'],strategy_version=STRATEGY,
                sealed_tasks_executed=0,model_calls=0,executions=[{'phase':'fit'},{'phase':'predict'}])
        c=DecisionController(case,None,root,directory,evaluator=evaluate)
        c.submit(session_id='case',source=case['source'],n_params=case['n_params'],auxiliary={'forecast':{'nmse':0.1}})
        return case,c.candidate

    def test_candidate_cannot_relabel_retained_as_improvement(self):
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d);case,candidate=self.make_candidate(directory)
            validate_candidate(case,candidate,directory)
            bad=copy.deepcopy(candidate);bad['score']['meaningful_improvement']=True
            with self.assertRaisesRegex(ValueError,'score'):validate_candidate(case,bad,directory)

    def test_candidate_metric_and_file_scope_are_cross_checked(self):
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d);case,candidate=self.make_candidate(directory)
            bad=copy.deepcopy(candidate);bad['evaluation_files'][0]='../other.json'
            with self.assertRaisesRegex(ValueError,'path'):validate_candidate(case,bad,directory)
            path=directory/candidate['evaluation_files'][0];record=read(path)
            record['metrics']['nmse']=0;write(path,record)
            with self.assertRaisesRegex(ValueError,'record'):validate_candidate(case,candidate,directory)


if __name__=='__main__':unittest.main()
