"""Bounded candidate-process observations; these never determine host scores.

Only source-line hits and return shapes are collected, not locals or values.
Python return events following exceptions can also carry None. Candidate code
can interfere with tracing, so this is debugging evidence, not an attestation.
"""
import sys
import json
import re

LIMITATIONS = ('Only the get_plan call phase is traced. Call/return events include generator '
              'or coroutine suspension/resumption. Interrupted checks hook mismatch at exit only; '
              'candidate code can suppress or forge observations. Missing hits do not prove nonexecution.')


class CandidateTrace:
    def __init__(self, event_limit=20000, item_limit=128):
        if type(event_limit) is not int or not 1 <= event_limit <= 20000:
            raise ValueError('invalid trace event limit')
        if type(item_limit) is not int or not 1 <= item_limit <= 128:
            raise ValueError('invalid trace item limit')
        self.event_limit, self.item_limit = event_limit, item_limit
        self.events = 0
        self.truncated = False
        self.interrupted = False
        self.lines, self.functions = {}, {}
        self.previous = None

    def __enter__(self):
        self.previous = sys.gettrace()
        sys.settrace(self)
        return self

    def __exit__(self, *args):
        self.interrupted = sys.gettrace() is not self and not self.truncated
        sys.settrace(self.previous)

    def __call__(self, frame, event, arg):
        if frame.f_code.co_filename != 'candidate.py':
            return None
        if self.events >= self.event_limit:
            self.truncated = True
            sys.settrace(None)
            return None
        self.events += 1
        if event == 'line':
            line = frame.f_lineno
            if line in self.lines or len(self.lines) < self.item_limit:
                self.lines[line] = self.lines.get(line, 0) + 1
            else:
                self.truncated = True
        if event in ('call', 'return', 'exception'):
            key = (frame.f_code.co_firstlineno, frame.f_code.co_name[:80])
            if key not in self.functions and len(self.functions) >= self.item_limit:
                self.truncated = True
                return self
            record = self.functions.setdefault(key, {
                'first_line': key[0], 'name': key[1], 'call_events': 0,
                'return_events': 0, 'none_return_events': 0,
                'exception_events': 0, 'return_types': {}, 'container_length_min': None,
                'container_length_max': None})
            if event == 'call':
                record['call_events'] += 1
            elif event == 'exception':
                record['exception_events'] += 1
            else:
                record['return_events'] += 1
                kind = type(arg)
                label = ('none' if arg is None else kind.__name__
                         if kind in (list, tuple, dict, set, bool, int, float, str) else 'other')
                record['return_types'][label] = record['return_types'].get(label, 0) + 1
                if arg is None:
                    record['none_return_events'] += 1
                if kind in (list, tuple, dict, set):
                    length = len(arg)
                    previous = record['container_length_min']
                    record['container_length_min'] = length if previous is None else min(previous, length)
                    previous = record['container_length_max']
                    record['container_length_max'] = length if previous is None else max(previous, length)
        return self

    def snapshot(self):
        return {'events_seen': self.events, 'event_limit': self.event_limit,
                'truncated': self.truncated, 'interrupted': self.interrupted,
                'provenance': 'candidate_process_trace_not_trusted_score',
                'interpretation_limits': LIMITATIONS,
                'none_return_caveat': 'None return events can follow exceptions; inspect exception_events.',
                'lines': [{'line': line, 'hits': hits} for line, hits in sorted(self.lines.items())],
                'functions': [self.functions[key] for key in sorted(self.functions)]}


def sanitize_trace(value):
    """Validate fixed host-visible shape; never pass arbitrary candidate fields."""
    expected = {'events_seen', 'event_limit', 'truncated', 'interrupted', 'provenance',
                'none_return_caveat', 'interpretation_limits', 'lines', 'functions'}
    def integer(number, high=20000):
        return type(number) is int and 0 <= number <= high
    if type(value) is not dict or set(value) != expected:
        return None
    if (value['provenance'] != 'candidate_process_trace_not_trusted_score'
            or value['interpretation_limits'] != LIMITATIONS
            or value['none_return_caveat'] != 'None return events can follow exceptions; inspect exception_events.'
            or not integer(value['events_seen']) or not integer(value['event_limit'])
            or not 1 <= value['event_limit'] <= 20000 or value['events_seen'] > value['event_limit']
            or type(value['truncated']) is not bool or type(value['interrupted']) is not bool):
        return None
    if (type(value['lines']) is not list or len(value['lines']) > 128
            or type(value['functions']) is not list or len(value['functions']) > 128):
        return None
    for row in value['lines']:
        if (type(row) is not dict or set(row) != {'line', 'hits'}
                or not integer(row['line'], 65536) or row['line'] == 0
                or not integer(row['hits'])):
            return None
    keys = {'first_line', 'name', 'call_events', 'return_events', 'none_return_events',
            'exception_events', 'return_types', 'container_length_min', 'container_length_max'}
    types = {'none', 'list', 'tuple', 'dict', 'set', 'bool', 'int', 'float', 'str', 'other'}
    for row in value['functions']:
        if type(row) is not dict or set(row) != keys:
            return None
        if (type(row['name']) is not str or not re.fullmatch(r'(?:[A-Za-z_]\w{0,79}|<(?:lambda|listcomp|setcomp|dictcomp|genexpr|module)>)', row['name'], re.ASCII)
                or not integer(row['first_line'], 65536) or row['first_line'] == 0
                or any(not integer(row[k]) for k in ('call_events', 'return_events', 'none_return_events', 'exception_events'))
                or type(row['return_types']) is not dict or not set(row['return_types']) <= types
                or any(not integer(n) for n in row['return_types'].values())
                or any(row[k] is not None and not integer(row[k], 1000000)
                       for k in ('container_length_min', 'container_length_max'))):
            return None
    # Copy so caller-side mutation cannot extend the validated dictionary.
    return json.loads(json.dumps(value, allow_nan=False))
