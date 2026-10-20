"""Verify future task-role metadata, optionally training-file integrity only."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rsi_eval.strategy_partition import read_json, validate_manifest, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--manifest', default='configs/tasks/strategy-partition-v0.1.json')
    parser.add_argument('--verify-data', action='store_true',
                        help='Hash training files and normalize training PDDL; never open test data.')
    parser.add_argument('--output', help='Create a JSON report; different existing bytes are refused.')
    args = parser.parse_args()
    try:
        document = read_json(args.root, args.manifest)
        result = validate_manifest(args.root, document, verify_data=args.verify_data)
        if args.output:
            write_json(args.root, args.output, result)
    except (ValueError, OSError) as exc:
        parser.exit(1, 'Partition verification failed: ' + str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
