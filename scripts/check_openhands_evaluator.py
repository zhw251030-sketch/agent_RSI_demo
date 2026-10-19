"""Offline SDK tool -> sandbox -> trusted evaluator roundtrips, no LLM."""
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rsi_eval.openhands_tool import EvaluateCandidateTool, research_agent_tools


def main():
    tools = research_agent_tools()
    assert len(tools) == 1 and tools[0].name == 'EvaluateCandidateTool'
    tool, = EvaluateCandidateTool.create()
    checks = []
    for family, task, file, count in [
        ('planning', 'spannerlearning/seed0/problem0', 'fixtures/planning/collect_then_tighten.py', 0),
        ('symbolic', 'oscillator1', 'fixtures/symbolic/linear.py', 3),
    ]:
        action = tool.action_from_arguments(dict(family=family, task_id=task,
            source=(ROOT / file).read_text(), n_params=count, strategy_version='sdk-offline-acceptance-v0'))
        observation = tool(action)
        checks.append({'family': family, 'passed': observation.feedback['status'] == 'success',
                       'feedback': observation.feedback})
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'sdk_version': importlib.metadata.version('openhands-sdk'),
              'checks': checks, 'passed': all(x['passed'] for x in checks),
              'model_calls': 0, 'agent_rollouts': 0, 'canvas_modified': False,
              'scope': 'Offline custom tool dispatch, not an Agent conversation or method experiment.'}
    directory = ROOT / 'runs/executor-acceptance'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'openhands-tool.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
