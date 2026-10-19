"""Operator CLI for the development-only executor; does not call an LLM."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rsi_eval.executor import evaluate_candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family', choices=['planning', 'symbolic'], required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--n-params', type=int, default=3)
    parser.add_argument('--parent-id')
    parser.add_argument('--strategy-version', default='manual-fixture-v0')
    args = parser.parse_args()
    if args.candidate.stat().st_size > 65536:
        parser.error('Candidate source exceeds 64 KiB')
    result = evaluate_candidate(args.family, args.task, args.candidate.read_text(encoding='utf-8'),
                                n_params=args.n_params, parent_id=args.parent_id,
                                strategy_version=args.strategy_version)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
