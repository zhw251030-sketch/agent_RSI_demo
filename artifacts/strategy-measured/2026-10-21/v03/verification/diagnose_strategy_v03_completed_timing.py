"""Read only one completed slot's persisted timings; never execute a task."""
import collections
import hashlib
import json
from pathlib import Path
import statistics

root = Path.cwd()
run = root/'runs/strategy-pair/measured-v03/experiment'
slot = 'r1-evaluation-P-eval-1-fixed'
bound_path = run/'bound-sessions'/f'{slot}.json'
read = lambda p: json.loads(p.read_bytes())
bound = read(bound_path)
assert bound['slot_id'] == slot and len(bound['evaluations']) == 63
refs = {ref['path']:ref for ref in bound['evaluations']}
before = {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in refs}
assert before == {name:ref['sha256'] for name,ref in refs.items()}
values = [read(root/ref['path']) for ref in bound['evaluations']]
assert all(value['candidate_id'] == slot and value['task_role']=='evaluation' for value in values)
events, started, completed = [], None, None
for path in sorted((run/'events').glob('*.json')):
    event = read(path)
    if event.get('slot_id') == slot and event['kind']=='session_started':
        started = event['monotonic_ns']
    if event['kind']=='measurement_recorded' and event.get('receipt',{}).get('path') in refs:
        events.append(event)
    if event.get('slot_id') == slot and event['kind']=='slot_completed':
        completed = event['monotonic_ns']
        break  # Never inspect any later or still-running slot.
assert completed is not None and len(events)==63
elapsed = [value['elapsed_seconds'] for value in values]
sandbox = [sum(execution['elapsed_seconds'] for execution in value['executions']) for value in values]
intervals = [(later['monotonic_ns']-earlier['monotonic_ns'])/1e9 for earlier,later in zip(events,events[1:])]
def summary(values):
    return dict(count=len(values),minimum=min(values),median=statistics.median(values),
        mean=statistics.mean(values),maximum=max(values),sum=sum(values))
report = dict(scope='Persisted timing analysis of completed r1-evaluation-P-eval-1-fixed only; no candidate/model execution.',
    slot_id=slot, measurements=len(values), statuses=dict(collections.Counter(v['status'] for v in values)),
    exception_types=dict(collections.Counter(v.get('exception_type') for v in values)),
    measured_result_elapsed_seconds=summary(elapsed),sandbox_elapsed_seconds=summary(sandbox),
    host_inside_result_elapsed_minus_sandbox_seconds=summary([a-b for a,b in zip(elapsed,sandbox)]),
    consecutive_measurement_event_intervals_seconds=summary(intervals),
    event_interval_minus_later_result_elapsed_seconds=summary([gap-duration for gap,duration in zip(intervals,elapsed[1:])]),
    first_to_last_measurement_seconds=(events[-1]['monotonic_ns']-events[0]['monotonic_ns'])/1e9,
    session_started_to_slot_completed_seconds=(completed-started)/1e9,
    sandbox_statuses=dict(collections.Counter(e['status'] for v in values for e in v['executions'])),
    val_records=sum('validator' in value for value in values),
    static_gate_verifications_per_task=4,static_selection_replays_per_task=8,
    static_basis='Scheduler.execute.authorize; RoleExecutor.evaluate._authorize before timer; second _authorize after timer; prepare_task._authorize. Each gate verifies r1 and r2 via bind_selection.',
    limitation='No profiler or new gate execution. Timing subtraction distinguishes sandbox and host work; it cannot attribute exact CPU time to individual hash or parsing functions.')
assert before == {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in refs}
report['completed_measurement_files_unchanged']=True
target=root/'tmp/strategy-v03-completed-slot-timing.json'
assert not target.exists()
target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
