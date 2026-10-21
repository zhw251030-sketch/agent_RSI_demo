from pathlib import Path
import io,json,logging,os,platform,sys,time,unittest
root=Path.cwd();sys.path.insert(0,str(root))
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
os.environ['OPENHANDS_SUPPRESS_BANNER']='1'
os.environ['DO_NOT_TRACK']='1'
logging.disable(logging.CRITICAL)
from rsi_eval.strategy_pair_preparation import canonical,runtime_files
names=['strategy_pair_agent','strategy_sdk_contract','strategy_pair_audit','strategy_pair_budget',
       'strategy_pair_cli','strategy_pair_preparation','strategy_pair_run','strategy_pair_simulation',
       'strategy_pair_transport','strategy_learning','strategy_binding','role_executor','goal_alignment']
tests=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_'+name for name in names])
def flatten(suite):
    for test in suite:
        if isinstance(test,unittest.TestSuite):yield from flatten(test)
        else:yield test
unique={test.id():test for test in flatten(tests)}
before=runtime_files(root)
buffer=io.StringIO();start=time.monotonic()
result=unittest.TextTestRunner(stream=buffer,verbosity=1).run(unittest.TestSuite(unique.values()))
after=runtime_files(root);assert before==after,'Runtime changed while tests ran'
report=dict(python=platform.python_version(),platform=sys.platform,tests_run=result.testsRun,
            passed=result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
            skipped=len(result.skipped),failures=len(result.failures),errors=len(result.errors),
            elapsed_seconds=round(time.monotonic()-start,3),test_ids=sorted(unique),
            output=buffer.getvalue(),skipped_tests=[dict(test=t.id(),reason=r) for t,r in result.skipped],
            tested_files_sha256=after)
target=root/('tmp/strategy-successor-tests-'+('server' if sys.platform=='linux' else 'local')+'.json')
target.write_bytes(canonical(report)+b'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('test_ids','tested_files_sha256','output','skipped_tests')},indent=2))
if not result.wasSuccessful():print(buffer.getvalue())
raise SystemExit(0 if result.wasSuccessful() else 1)
