"""Post-run integrity negative cases; no fitting, candidate execution or CSV reads."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import diagnostic as d

ARCHIVE=d.ROOT/'artifacts/symbolic-diagnostic/2026-10-22/v01'


class ArchiveTests(unittest.TestCase):
    def exercise(self, mutate):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'copy'
            shutil.copytree(ARCHIVE,root)
            mutate(root)
            # Rehash the modified archive: the verifier must check semantics too.
            manifest={'files':[{'path':p.relative_to(root).as_posix(),'sha256':d.sha(p.read_bytes())}
                               for p in sorted(root.rglob('*')) if p.is_file() and p.name!='manifest.json']}
            (root/'manifest.json').write_bytes(d.canonical(manifest)+b'\n')
            with self.assertRaises(ValueError): d.verify(root)

    def change(self,root,name,mutate):
        path=root/name
        value=d.read(path)
        mutate(value)
        path.write_bytes(d.canonical(value)+b'\n')

    def test_positive(self):
        self.assertEqual(d.verify(ARCHIVE)['successful_fits'],8)

    def test_forged_protocol(self):
        self.exercise(lambda root:self.change(root,'protocol.json',lambda x:x.update(retries=1)))

    def test_reordered_summary(self):
        self.exercise(lambda root:self.change(root,'summary.json',lambda x:x['rows'].reverse()))

    def test_wrong_source_binding(self):
        self.exercise(lambda root:self.change(root,'01-stress-original-7/reserved.json',lambda x:x.update(source_sha256='0'*64)))

    def test_wrong_task_data(self):
        self.exercise(lambda root:self.change(root,'01-stress-original-7/reserved.json',lambda x:x['provenance'].update(data_sha256='0'*64)))

    def test_wrong_initial_params(self):
        self.exercise(lambda root:self.change(root,'01-stress-original-7/reserved.json',lambda x:x.update(initial_params=[0.0]*7)))

    def test_short_predictions(self):
        self.exercise(lambda root:self.change(root,'01-stress-original-7/predict.json',lambda x:x['result']['predictions'].pop()))

    def test_forged_optimizer(self):
        self.exercise(lambda root:self.change(root,'01-stress-original-7/fit.json',lambda x:x['result']['diagnostics'].update(nfev=99)))

    def test_forged_score_and_summary(self):
        def mutate(root):
            self.change(root,'01-stress-original-7/result.json',lambda x:x['metrics'].update(nmse=0.0))
            self.change(root,'summary.json',lambda x:x['rows'][0]['metrics'].update(nmse=0.0))
        self.exercise(mutate)


if __name__=='__main__': unittest.main()
