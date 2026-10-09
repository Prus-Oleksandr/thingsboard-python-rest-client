"""Checks the hand-written wrappers (rest_client_*.py) against a newly generated client.

Usage: python3 codegen/check_wrappers.py [--old-package PATH] [--package PATH] [--full] [--json PATH]

Each wrapper call self.<controller>.<method>(...) is resolved in the old generated
API (the one the wrappers were written for) to its HTTP method + path, and then
matched by HTTP method + path in the new client, because method names change
between spec versions. When the path is gone, or now belongs to another variant,
the new op implemented by the same Java controller method (the name the summary
ends with), or else with the same summary title in the same controller, is used
if the HTTP method and response type agree. Findings:
  ERROR  the wrapper will not work even after renaming (endpoint or param gone,
         new required param not passed, call already broken in the old client)
  RENAME mechanical changes: new method, controller or param name
  WARN   response type changed; and the wrapper against the spec of the op it calls: deprecated
         operation, spec param the wrapper does not accept, required-ness differs
  INFO   new operations no wrapper calls yet
--json writes the full old -> new mapping of every call, to drive the rewrite.
"""
import argparse
import ast
import builtins
import collections
import json
import os
import re
import sys
import typing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client_parser import parse_api_dir, parse_models_dir  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAPPER_FILES = ('rest_client.py', 'rest_client_base.py', 'rest_client_ce.py', 'rest_client_pe.py')

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--old-package', default=os.path.join(ROOT, 'tb_rest_client'),
                    help='package with the wrappers and the API they were written for')
parser.add_argument('--package', default=os.path.join(ROOT, 'draft/tb_rest_client'), help='newly generated package')
parser.add_argument('--full', action='store_true', help='print every finding, not just examples')
parser.add_argument('--json', help='also write the call mapping and findings to this JSON file')
parser.add_argument('--spec', default=os.path.join(ROOT, 'codegen/spec/thingsboard-swagger.json'),
                    help='OpenAPI spec of the new client, for the wrapper vs spec warnings')
args = parser.parse_args()

findings = collections.defaultdict(list)
spec = json.load(open(args.spec))


def report(severity, kind, *details):
    findings[(severity, kind)].append(details)


def path_key(op):
    """HTTP method + path with placeholder names dropped: /api/device/{deviceId} -> /api/device/{}"""
    return op['http_method'], re.sub(r'\{[^}]*\}', '{}', op['path'])


def placeholders(path):
    return re.findall(r'\{([^}]*)\}', path)


def edition_of(module):
    """tb_rest_client.api.api_ce[.x_api] -> api_ce; tb_rest_client.api[.x_api] -> api (single edition)"""
    parts = module.split('.')
    # an edition is a package (api_ce, api_pe), not a module such as api.api_key_controller_api
    return parts[2] if len(parts) > 2 and parts[2] in editions else 'api'


# ---------- old generated API, per edition (api_ce/api_pe, or a single api) ----------
old_api = {}  # (edition, class) -> {method name: op}
api_root = os.path.join(args.old_package, 'api')
editions = sorted(d for d in os.listdir(api_root) if os.path.isdir(os.path.join(api_root, d)) and d.startswith('api_'))
for edition in editions or ['api']:
    for op in parse_api_dir(os.path.join(api_root, edition) if editions else api_root):
        old_api.setdefault((edition, op['class']), {})[op['name']] = op

# ---------- new generated API ----------
new_ops = parse_api_dir(os.path.join(args.package, 'api'))
new_by_key = {path_key(op): op for op in new_ops}


# ---------- wrappers ----------
def parse_wrappers(path):
    """Returns ({attr: (edition, class)}, [calls]) of a rest_client_*.py file."""
    tree = ast.parse(open(path).read())
    imported = {}  # class -> edition
    star_edition = None  # from tb_rest_client.api.api_pe import *
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module \
                and (node.module == 'tb_rest_client.api' or node.module.startswith('tb_rest_client.api.')):
            edition = edition_of(node.module)
            for alias in node.names:
                if alias.name == '*':
                    star_edition = edition
                else:
                    imported[alias.asname or alias.name] = edition
    if star_edition:
        imported.update({op['class']: star_edition for (ed, _), ops in old_api.items() if ed == star_edition
                         for op in ops.values() if op['class'] not in imported})
    controllers, calls = {}, []
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
            # wrapper param -> has a default value
            fn_args = fn.args.args[1:]
            optional = {a.arg for a in fn_args[len(fn_args) - len(fn.args.defaults):]} if fn.args.defaults else set()
            wrapper_params = {a.arg: a.arg in optional for a in fn_args}
            for node in ast.walk(fn):
                # self.<attr> = <Class>(self.api_client)
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                        and isinstance(node.value.func, ast.Name) and node.value.func.id in imported:
                    target = node.targets[0]
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                        controllers[target.attr] = (imported[node.value.func.id], node.value.func.id)
                # self.<attr>.<method>(...)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name) \
                        and node.func.value.value.id == 'self':
                    calls.append({'file': os.path.basename(path), 'line': node.lineno,
                                  'wrapper': '%s.%s' % (cls.name, fn.name),
                                  'controller': node.func.value.attr, 'method': node.func.attr,
                                  'kwargs': [k.arg for k in node.keywords], 'n_positional': len(node.args),
                                  # call kwarg -> wrapper param passed to it (as is or via self.get_id(...))
                                  'kw_params': {k.arg: next((n.id for n in ast.walk(k.value) if isinstance(n, ast.Name)
                                                             and n.id in wrapper_params), None)
                                                for k in node.keywords},
                                  'wrapper_params': wrapper_params})
    return controllers, calls


controllers_by_file, calls = {}, []
for f in WRAPPER_FILES:
    path = os.path.join(args.old_package, f)
    if os.path.exists(path):
        controllers_by_file[f], file_calls = parse_wrappers(path)
        calls.extend(file_calls)
base_controllers = controllers_by_file.get('rest_client_base.py', {})


def resolve_old(call):
    """Finds the old generated op a wrapper call goes to. Base wrappers run with the base
    controllers in CE and with the ones RestClientPE replaces in PE."""
    if call['file'] == 'rest_client_base.py':
        candidates = [base_controllers, controllers_by_file.get('rest_client_pe.py', {})]
    else:
        candidates = [controllers_by_file.get(call['file'], {}), base_controllers]
    found_cls = None
    for controllers in candidates:
        if call['controller'] in controllers:
            edition, cls = controllers[call['controller']]
            found_cls = found_cls or cls
            op = old_api.get((edition, cls), {}).get(call['method'])
            if op:
                return cls, op
    return found_cls, None


def base_name(name):
    """get_users_by_ids_using_get1 -> get_users_by_ids"""
    return re.sub(r'_using_(get|post|put|delete|patch)\d*$|\d+$', '', name)


new_by_name = collections.defaultdict(list)
for op in new_ops:
    new_by_name[base_name(op['name'])].append(op)


new_by = {'java': collections.defaultdict(list), 'title': collections.defaultdict(list)}
for op in new_ops:
    for key in new_by:
        if op[key]:
            new_by[key][op[key]].append(op)


def path_similarity(a, b):
    def segments(path):
        return set(re.sub(r'\{[^}]*\}', '{}', path).split('/')) - {'', 'api'}

    return len(segments(a) & segments(b)) / len(segments(a) | segments(b))


def find_same_operation(old, old_cls, key):
    """The new op with the same Java controller method name (key='java') or summary title
    (key='title') as the old one, if unambiguous. The HTTP method must match (PUT update vs
    POST save differ even with one summary). Several controllers have methods with the same
    name (findByQuery), so the same class is preferred, then the most similar path."""
    candidates = [op for op in new_by[key].get(old[key], []) if op['http_method'] == old['http_method']]
    if key == 'title' or any(op['class'] == old_cls for op in candidates):
        # titles like 'Update oauth2 clients' repeat across controllers
        candidates = [op for op in candidates if op['class'] == old_cls]
    if len(candidates) > 1:
        candidates.sort(key=lambda op: -path_similarity(old['path'], op['path']))
        if path_similarity(old['path'], candidates[0]['path']) == path_similarity(old['path'], candidates[1]['path']):
            return None
    return candidates[0] if candidates else None


def compatible_response(old, new):
    """Same response type, or one of them too loose to tell (object, str, DeferredResult...)."""
    weak = re.compile(r'^(None|object|str|JsonNode|ObjectNode|Deferred\w*)$')
    a, b = old['response_type'] or 'None', new['response_type'] or 'None'
    return a == b or bool(weak.match(a)) or bool(weak.match(b))


def moved_candidate(old):
    """A new op that probably replaced an old op whose path is gone: same method name,
    otherwise the same HTTP method with the most similar path."""
    same_name = [op for op in new_by_name.get(base_name(old['name']), []) if op['http_method'] == old['http_method']]
    if same_name:
        return 'same name', same_name[0]
    candidates = [op for op in new_ops if op['http_method'] == old['http_method']]
    best = max(candidates, key=lambda op: path_similarity(old['path'], op['path']), default=None)
    if best and path_similarity(old['path'], best['path']) >= 0.5:
        return 'similar path', best
    return None, None


def query_wires(op):
    return {wire for location, wire in op['params'] if location == 'query'}


# Springfox specs had several operations on one path + method that differ only by
# query params (get_tenant_asset?assetName vs get_tenant_assets?pageSize&page).
# Springdoc keeps one of them per path + method, so the others are not in the new spec.
variants = collections.defaultdict(dict)
for call in calls:
    old = resolve_old(call)[1]
    if old and path_key(old) in new_by_key:
        variants[path_key(old)][(old['class'], old['name'])] = old


def is_kept_variant(old):
    """True if the new spec kept this old op, not another one with the same path + method."""
    new_query = query_wires(new_by_key[path_key(old)])

    def score(op):
        return len(query_wires(op) & new_query) - len(query_wires(op) - new_query)

    return score(old) == max(score(op) for op in variants[path_key(old)].values())


mapping = []
used_new = set()
for call in calls:
    where = '%s:%d %s' % (call['file'], call['line'], call['wrapper'])
    old_cls, old = resolve_old(call)
    if old_cls is None:
        continue  # not a controller call (e.g. self.api_client.*)
    entry = {'wrapper': call['wrapper'], 'file': call['file'], 'line': call['line'],
             'old': '%s.%s' % (old_cls, call['method']), 'controller_attr': call['controller'],
             'new': None, 'http': None, 'kwargs': {}, 'issues': []}
    mapping.append(entry)

    def issue(severity, kind, *details):
        entry['issues'].append({'severity': severity, 'kind': kind, 'details': details})
        report(severity, kind, where, *details)

    if old is None:
        issue('ERROR', 'calls a method missing in the old client', '%s.%s' % (old_cls, call['method']))
        continue
    entry['http'] = '%s %s' % (old['http_method'], old['path'])
    new = new_by_key.get(path_key(old))
    collapsed = new is not None and new['java'] != old['java'] and not is_kept_variant(old)
    # The controller method name, or at least the summary title, survives path and operationId
    # changes. Summaries are sometimes copy-pasted from another operation, so the path wins when
    # it still exists, and a move is only trusted when the response type agrees.
    moved_to, moved_by = None, None
    if new is None or collapsed:
        for key, label in (('java', 'same Java method'), ('title', 'same summary')):
            candidate = find_same_operation(old, old_cls, key) if old[key] else None
            if candidate is not None and compatible_response(old, candidate):
                moved_to, moved_by = candidate, label
                break
    if moved_to is not None:
        new = moved_to
        issue('RENAME', 'endpoint moved (%s)' % moved_by, entry['http'], '%s %s' % (new['http_method'], new['path']))
    elif new is None:
        how, candidate = moved_candidate(old)
        if how == 'same name':
            issue('ERROR', 'endpoint moved (same name, other path)', entry['http'], entry['old'],
                  'now %s %s %s.%s' % (candidate['http_method'], candidate['path'], candidate['class'], candidate['name']))
        else:
            issue('ERROR', 'endpoint not in spec', entry['http'], entry['old'],
                  'similar: %s %s %s.%s' % (candidate['http_method'], candidate['path'], candidate['class'],
                                            candidate['name']) if candidate else 'no similar endpoint')
        continue
    elif collapsed:
        issue('ERROR', 'variant not in spec (same path, other query)',
              '%s?%s' % (entry['http'], '&'.join(sorted(query_wires(old)))), entry['old'],
              'spec has only %s.%s' % (new['class'], new['name']))
        continue
    used_new.add(path_key(new))
    entry['new'] = '%s.%s' % (new['class'], new['name'])
    if new['class'] != old_cls:
        issue('RENAME', 'controller changed', old_cls, new['class'])
    if new['name'] != call['method']:
        issue('RENAME', 'method renamed', call['method'], new['name'])

    # old python param -> (location, wire name) -> new python param
    old_wire = {py: key for key, py in old['params'].items()}
    # path params keep their position on the same path; on a moved endpoint they are matched by name
    path_rename = dict(zip(placeholders(old['path']), placeholders(new['path']))) \
        if path_key(old) == path_key(new) else {}
    passed_new = set()
    for kw in call['kwargs']:
        if kw in ('async_req', '_return_http_data_only', '_preload_content', '_request_timeout'):
            continue
        if kw == 'body':
            new_kw = 'body' if new['body'] else None
        elif kw in old_wire:
            location, wire = old_wire[kw]
            if location == 'path':
                wire = path_rename.get(wire, wire)
            new_kw = new['params'].get((location, wire))
            if new_kw is None:  # moved, e.g. from query to a multipart form field
                new_kw = next((py for (_, w), py in new['params'].items() if w == wire), None)
        else:
            issue('ERROR', 'passes a param unknown to the old method', kw)
            continue
        entry['kwargs'][kw] = new_kw
        if new_kw is None:
            issue('ERROR', 'param removed from endpoint', kw)
        else:
            passed_new.add(new_kw)
            if new_kw != kw:
                issue('RENAME', 'param renamed', kw, new_kw)
    for required in new['required'] - passed_new:
        issue('ERROR', 'new required param not passed', required, entry['new'])
    if (old['response_type'] or 'None') != (new['response_type'] or 'None'):
        issue('WARN', 'response type changed', old['response_type'], new['response_type'])

    # ---------- the wrapper against the spec of the new op (private helpers are not checked) ----------
    if call['wrapper'].split('.')[-1].startswith('_'):
        continue
    spec_op = spec['paths'].get(new['path'], {}).get(new['http_method'].lower(), {})
    if spec_op.get('deprecated'):
        issue('WARN', 'calls an operation deprecated in the spec', entry['new'], '%s %s' % (new['http_method'], new['path']))
    internal = {'async_req', '_return_http_data_only', '_preload_content', '_request_timeout'}
    not_exposed = [p for p in new['all_params'] if p not in passed_new and p not in internal]
    if not_exposed:
        issue('WARN', 'spec param not accepted by the wrapper', entry['new'], ', '.join(not_exposed))
    # required-ness from the spec itself: the generator does not enforce required multipart fields
    spec_required_params = {new['params'].get((p['in'], p['name'])) for p in spec_op.get('parameters', []) if p.get('required')}
    request_body = spec_op.get('requestBody', {})
    if request_body.get('required') and new['body']:
        spec_required_params.add('body')
    for media in request_body.get('content', {}).values():
        spec_required_params |= {new['params'].get(('form', w)) for w in (media.get('schema') or {}).get('required', [])}
    for kw, new_kw in entry['kwargs'].items():
        param = call['kw_params'].get(kw)
        if new_kw is None or param is None:
            continue
        spec_required = new_kw in spec_required_params
        wrapper_optional = call['wrapper_params'][param]
        if spec_required and wrapper_optional:
            issue('WARN', 'spec-required param optional in the wrapper', entry['new'], param)
        elif not spec_required and not wrapper_optional:
            issue('WARN', 'spec-optional param required in the wrapper', entry['new'], param)

for op in new_ops:
    if path_key(op) not in used_new:
        report('INFO', 'new operation without wrapper', '%s.%s' % (op['class'], op['name']),
               '%s %s' % (op['http_method'], op['path']))

# ---------- annotations naming models the new client does not have ----------
new_models = set(parse_models_dir(os.path.join(args.package, 'models')))
trees = {f: ast.parse(open(os.path.join(args.old_package, f)).read()) for f in controllers_by_file}
known = new_models | set(dir(builtins)) | set(dir(typing)) | {
    n.name for tree in trees.values() for n in ast.walk(tree) if isinstance(n, ast.ClassDef)} | {
    a.asname or a.name for tree in trees.values() for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    for a in n.names if a.name != '*'}
for f, tree in trees.items():
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
            annotations = [a.annotation for a in fn.args.args + fn.args.kwonlyargs if a.annotation] + [fn.returns]
            unknown = sorted({n.id for a in annotations if a for n in ast.walk(a)
                              if isinstance(n, ast.Name) and n.id not in known})
            if unknown:
                report('WARN', 'annotation names a model missing in new client',
                       '%s:%d %s.%s' % (f, fn.lineno, cls.name, fn.name), ', '.join(unknown))

# ---------- report ----------
print('Wrappers: %s (%d controller calls)' % (', '.join(os.path.join(args.old_package, f) for f in controllers_by_file), len(mapping)))
print('Old API:  %d operations in %s' % (sum(len(v) for v in old_api.values()), ', '.join(editions or ['api'])))
print('New API:  %d operations in %s\n' % (len(new_ops), os.path.join(args.package, 'api')))
severities = [{i['severity'] for i in e['issues']} for e in mapping]
print('Calls: %d work as is, %d need only renames, %d have errors\n'
      % (sum(not s & {'ERROR', 'RENAME'} for s in severities),
         sum('RENAME' in s and 'ERROR' not in s for s in severities),
         sum('ERROR' in s for s in severities)))
for severity in ('ERROR', 'RENAME', 'WARN', 'INFO'):
    keys = sorted((k for k in findings if k[0] == severity), key=lambda k: -len(findings[k]))
    if not keys:
        continue
    print('%s: %d' % (severity, sum(len(findings[k]) for k in keys)))
    for key in keys:
        items = findings[key]
        print('  %-44s %d' % (key[1], len(items)))
        for item in items if args.full else items[:3]:
            print('      ' + ' | '.join(map(str, item)))
        if not args.full and len(items) > 3:
            print('      ...')
if args.json:
    with open(args.json, 'w') as f:
        json.dump({'calls': mapping, 'findings': {'%s: %s' % k: v for k, v in findings.items()}},
                  f, indent=1, default=str)
