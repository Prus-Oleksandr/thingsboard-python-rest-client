"""Applies the renames found by check_wrappers.py to copies of the wrappers.

Usage: python3 codegen/apply_wrapper_renames.py <calls.json> <package_dir>

<calls.json> is written by `check_wrappers.py --json` for the old wrappers, and
<package_dir> is the new client (e.g. draft/tb_rest_client) holding unmodified
copies of rest_client_*.py. Calls without ERROR findings get the new method and
param names; calls with errors are left untouched for manual review. Imports are
pointed at the single tb_rest_client.api and tb_rest_client.models packages, and
controllers whose class is gone from the new API are no longer created.
"""
import ast
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client_parser import parse_api_dir  # noqa: E402

IMPORT_RENAMES = [(r'tb_rest_client\.api\.api_(ce|pe)\b', 'tb_rest_client.api'),
                  (r'tb_rest_client\.models\.models_(ce|pe)\b', 'tb_rest_client.models')]


def find_call(tree, line, controller, method):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.lineno == line and isinstance(node.func, ast.Attribute) \
                and node.func.attr == method and isinstance(node.func.value, ast.Attribute) \
                and node.func.value.attr == controller:
            return node
    return None


def rewrite(path, entries, api_classes):
    src = open(path).read()
    tree = ast.parse(src)
    lines = [line.encode() for line in src.split('\n')]  # ast columns are utf-8 byte offsets
    edits, deleted, stats = [], set(), collections.Counter()

    def replace(line, col, old, new):
        if lines[line - 1][col:col + len(old.encode())] != old.encode():
            sys.exit('%s:%d: expected %r at column %d' % (path, line, old, col))
        edits.append((line, col, old, new))

    for entry in entries:
        if any(i['severity'] == 'ERROR' for i in entry['issues']):
            stats['left for manual review (errors)'] += 1
            continue
        old_method = entry['old'].split('.')[1]
        new_method = entry['new'].split('.')[1]
        kwarg_renames = {old: new for old, new in entry['kwargs'].items() if new and new != old}
        if new_method == old_method and not kwarg_renames:
            stats['unchanged (already right)'] += 1
            continue
        node = find_call(tree, entry['line'], entry['controller_attr'], old_method)
        if node is None:
            sys.exit('%s:%d: call %s not found, are these unmodified copies of the wrappers?'
                     % (path, entry['line'], entry['old']))
        if new_method != old_method:
            replace(node.func.end_lineno, node.func.end_col_offset - len(old_method.encode()), old_method, new_method)
            # keep continuation lines aligned with the opening parenthesis
            aligned = node.func.end_col_offset + 1
            for line in range(node.func.end_lineno + 1, node.end_lineno + 1):
                if len(lines[line - 1]) - len(lines[line - 1].lstrip(b' ')) == aligned:
                    replace(line, 0, ' ' * aligned, ' ' * (aligned + len(new_method) - len(old_method)))
        for kw in node.keywords:
            if kw.arg in kwarg_renames:
                replace(kw.lineno, kw.col_offset, kw.arg, kwarg_renames[kw.arg])
        stats['rewritten'] += 1

    # self.<attr> = <Class>(self.api_client) for classes gone from the new API
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name) and node.value.func.id.endswith('ControllerApi') \
                and node.value.func.id not in api_classes:
            deleted.update(range(node.lineno, node.end_lineno + 1))
            stats['controller removed: %s' % node.value.func.id] += 1

    for line, col, old, new in sorted(edits, reverse=True):
        lines[line - 1] = lines[line - 1][:col] + new.encode() + lines[line - 1][col + len(old.encode()):]
    text = '\n'.join(line.decode() for i, line in enumerate(lines, 1) if i not in deleted)
    for pattern, repl in IMPORT_RENAMES:
        text, n = re.subn(pattern, repl, text)
        stats['import paths changed'] += n
    # annotations may still name models gone from the new client (check_wrappers.py lists them),
    # so they must not be evaluated at import time
    if 'from __future__ import annotations' not in text:
        text = re.sub(r'^(?=(from|import) )', 'from __future__ import annotations\n\n', text, count=1, flags=re.M)
        stats['lazy annotations added'] += 1
    with open(path, 'w') as f:
        f.write(text)
    return stats


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    calls_path, package_dir = sys.argv[1:]
    api_classes = {op['class'] for op in parse_api_dir(os.path.join(package_dir, 'api'))}
    by_file = collections.defaultdict(list)
    for entry in json.load(open(calls_path))['calls']:
        by_file[entry['file']].append(entry)
    for f, entries in sorted(by_file.items()):
        stats = rewrite(os.path.join(package_dir, f), entries, api_classes)
        print('%s: %s' % (f, ', '.join('%s %d' % kv for kv in sorted(stats.items()))))
