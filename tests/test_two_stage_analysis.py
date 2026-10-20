import copy
from pathlib import Path
import tempfile
import unittest
from rsi_eval.two_stage_core import RevisionController
from scripts.analyze_two_stage import validate_candidate
from tests.test_two_stage_core import case,registration,sha


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name);self.case=case('symbolic')
        def evaluate(family,task,source,**kw):
            return dict(family=family,task_id=task,candidate_hash=sha(source),
                parent_id=kw['parent_id'],candidate_id=kw['candidate_id'],model_calls=0,sealed_tasks_executed=0,
                status='success',metrics={'nmse':.09},executions=[{'phase':'fit'},{'phase':'predict'}])
        c=RevisionController(self.case,registration(self.case),None,self.directory,self.directory/'session',evaluator=evaluate)
        c.submit('session',self.case['source'],3,'test',{})
        self.candidate=c.candidate;self.session=self.directory/'session'

    def test_valid_candidate_record(self):
        self.assertEqual(validate_candidate(self.case,self.candidate,self.session),self.case['source'])

    def test_changed_source_is_rejected(self):
        (self.session/'candidate.py').write_text('different source',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'source digest'):validate_candidate(self.case,self.candidate,self.session)

    def test_score_edit_and_forecast_tampering_rejected(self):
        for key,value in [('score',{'complete':True}),('edit',{'kind':'unchanged'}),('forecast',{'status':'evaluated'})]:
            altered=copy.deepcopy(self.candidate);altered[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_candidate(self.case,altered,self.session)

    def test_path_escape_and_record_change_rejected(self):
        altered=copy.deepcopy(self.candidate);altered['evaluation_files'][0]='../outside.json'
        with self.assertRaisesRegex(ValueError,'Evaluation path'):validate_candidate(self.case,altered,self.session)
        altered=copy.deepcopy(self.candidate);altered['results'][0]['metrics']['nmse']=0
        with self.assertRaisesRegex(ValueError,'Evaluation byte record'):validate_candidate(self.case,altered,self.session)


if __name__=='__main__':unittest.main()
