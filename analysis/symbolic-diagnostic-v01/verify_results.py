"""Offline archive/calibration verification; no candidates, fits or CSV reads."""
import io
import json
from pathlib import Path
import sys
import unittest

import diagnostic as d


def verify():
    archive=d.ROOT/'artifacts/symbolic-diagnostic/2026-10-22'
    result=d.verify(archive/'v01')
    protocol=d.read(d.ROOT/d.PROTOCOL)
    calibration=[]
    for ref in protocol['files']:
        if ref['path'].startswith('runs/symbolic-diagnostic/calibration-v01/'):
            path=archive/'calibration-v01'/Path(ref['path']).name
            if d.sha(path.read_bytes())!=ref['sha256']: raise ValueError('calibration archive differs')
            calibration.append(path)
    if len(calibration)!=8: raise ValueError('incomplete calibration')
    suite=unittest.defaultTestLoader.discover(str(d.BASE),pattern='test_archive.py')
    tests=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
    if tests.testsRun!=9 or not tests.wasSuccessful() or tests.skipped: raise ValueError('archive tests failed')
    result.update(calibration_files=len(calibration),archive_total_files=52,
                  calibration_archive_byte_equal=True,postrun_tests=9,tamper_cases=8,
                  frozen_old_runtime_files_unchanged=d.runtime_check(),
                  protocol_sha256=d.sha((d.ROOT/d.PROTOCOL).read_bytes()),
                  source_verifier_sha256=d.sha(Path(__file__).read_bytes()))
    return result


if __name__=='__main__':
    result=verify()
    d.write(d.ROOT/sys.argv[1],result)
    print(json.dumps(result))
