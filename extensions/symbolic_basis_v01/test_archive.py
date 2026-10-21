"""Post-calibration semantic tamper tests, with no sandbox or fitting."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from .executor import ROOT, canonical, sha
from .calibrate import verify

ARCHIVE=ROOT/'artifacts/symbolic-basis/2026-10-22/calibration-v01'


class ArchiveTests(unittest.TestCase):
    def change(self,root,name,mutator):
        path=root/name
        value=json.loads(path.read_bytes())
        mutator(value)
        path.write_bytes(canonical(value)+b'\n')

    def rejects(self,mutator):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'archive'
            shutil.copytree(ARCHIVE,root)
            mutator(root)
            files=[dict(path=p.relative_to(root).as_posix(),sha256=sha(p.read_bytes())) for p in sorted(root.rglob('*')) if p.is_file() and p.name!='manifest.json']
            (root/'manifest.json').write_bytes(canonical(dict(files=files))+b'\n')
            with self.assertRaises(ValueError): verify(root)

    def test_positive_replay(self):
        self.assertEqual(verify(ARCHIVE)['score_replays'],10)

    def test_external_protocol_binding(self):
        self.rejects(lambda root:self.change(root,'protocol.json',lambda x:x.update(retries=1)))

    def test_transition_claim_cannot_replace_actual_edit(self):
        def mutate(root):
            self.change(root,'swap-one/transition.json',lambda x:x.update(observed_change='keep'))
            self.change(root,'swap-one/result.json',lambda x:x['transition'].update(observed_change='keep'))
            self.change(root,'summary.json',lambda x:x['rows'][5]['result']['transition'].update(observed_change='keep'))
        self.rejects(mutate)

    def test_reservation_initialization(self):
        self.rejects(lambda root:self.change(root,'affine-1d/reservation.json',lambda x:x.update(initial_params=[0.,0.])))

    def test_guard_request_binding(self):
        self.rejects(lambda root:self.change(root,'overflow-signs/request.json',lambda x:x.update(params=[0.,0.])))

    def test_fit_status_not_inferred_from_score(self):
        self.rejects(lambda root:self.change(root,'affine-1d/fit.json',lambda x:x['result'].update(converged=False)))

    def test_score_recomputed_from_saved_prediction(self):
        def mutate(root):
            self.change(root,'missing-square/result.json',lambda x:x['metrics'].update(nmse=0.))
            self.change(root,'summary.json',lambda x:x['rows'][4]['result']['metrics'].update(nmse=0.))
        self.rejects(mutate)

    def test_zero_variance_does_not_get_invented_metric(self):
        def mutate(root):
            self.change(root,'constant-target/result.json',lambda x:x.update(metrics={'nmse':0.},sse=0.))
            self.change(root,'summary.json',lambda x:x['rows'][7]['result'].update(metrics={'nmse':0.},sse=0.))
        self.rejects(mutate)

    def test_count_replay(self):
        self.rejects(lambda root:self.change(root,'summary.json',lambda x:x.update(synthetic_fit_attempts=11)))

    def test_boolean_coefficient_rejected_even_when_equal_to_one(self):
        def mutate(root):
            def coefficients(x):
                x['params'][0]=True
                x['optimizer_diagnostics']['final_params'][0]=True
            self.change(root,'affine-1d/result.json',coefficients)
            self.change(root,'summary.json',lambda x:coefficients(x['rows'][0]['result']))
            def fit(x):
                x['result']['params'][0]=True
                x['result']['diagnostics']['final_params'][0]=True
            self.change(root,'affine-1d/fit.json',fit)
        self.rejects(mutate)


if __name__=='__main__': unittest.main()
