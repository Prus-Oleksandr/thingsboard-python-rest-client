"""Compares a generated Python client with the OpenAPI spec it was generated from.

Usage: python3 codegen/check_spec.py [--spec PATH] [--package PATH] [--full] [--json PATH]

Operations are matched by HTTP method + path, models by schema name, so renamed
methods do not hide anything. Findings are split into ERROR (something from the
spec is lost or wrong in the client) and WARN (known generator limitations).
By default up to 3 examples per finding are printed; --full prints all of them.
"""
import argparse
import ast
import collections
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTTP_METHODS = ('get', 'post', 'put', 'delete', 'patch', 'head', 'options')

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--spec', default=os.path.join(ROOT, 'codegen/spec/thingsboard-swagger.json'))
parser.add_argument('--package', default=os.path.join(ROOT, 'draft/tb_rest_client'))
parser.add_argument('--full', action='store_true', help='print every finding, not just examples')
parser.add_argument('--json', help='also write all findings to this JSON file')
args = parser.parse_args()

spec = json.load(open(args.spec))
schemas = spec['components']['schemas']
findings = collections.defaultdict(list)


def report(severity, kind, *details):
    findings[(severity, kind)].append(details)


def norm(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def ref_name(ref):
    return ref.rsplit('/', 1)[-1]


def is_free_form(name):
    """Schema that accepts any JSON, e.g. JsonNode."""
    if name not in schemas:
        return False
    s = schemas[name]
    return not any(k in s for k in ('properties', 'allOf', 'oneOf', 'anyOf', 'enum', 'items')) \
        and s.get('type') in (None, 'object')


def expected_type(p):
    """Python type swagger-codegen should produce for a spec schema."""
    if '$ref' in p:
        name = ref_name(p['$ref'])
        return 'object' if is_free_form(name) else name
    if 'allOf' in p and len(p['allOf']) == 1 and '$ref' in p['allOf'][0]:
        return expected_type(p['allOf'][0])
    for k in ('allOf', 'oneOf', 'anyOf'):
        if k in p:
            return '<%s:%s>' % (k, ','.join(expected_type(x) for x in p[k]))
    t, fmt = p.get('type'), p.get('format')
    if t == 'string':
        return {'date-time': 'datetime', 'date': 'date'}.get(fmt, 'str')
    if t in ('integer', 'number', 'boolean'):
        return {'integer': 'int', 'number': 'float', 'boolean': 'bool'}[t]
    if t == 'array':
        return 'list[%s]' % expected_type(p.get('items', {}))
    ap = p.get('additionalProperties')
    if isinstance(ap, dict) and ap:
        return 'dict(str, %s)' % expected_type(ap)
    if ap is True or ap == {}:
        return 'dict(str, object)'
    return 'object'


def compare_types(where, exp, got):
    # free-form schemas (JsonNode, ServerSentEventString, ...) are generated either as 'object' or as an empty class
    got_free_form = re.sub(r'\w+', lambda m: 'object' if is_free_form(m.group()) else m.group(), got)
    if norm(exp) in (norm(got), norm(got_free_form)):
        return
    if exp == 'object' and got in gen_classes:
        return  # inline object schema generated as its own model, e.g. AuthTokenBody
    if '<' in exp:
        report('WARN', 'oneOf/anyOf typed loosely', *where, exp, got)
    elif norm(got).endswith('object') and not norm(exp).endswith('object'):
        report('ERROR', 'type degraded to object', *where, exp, got)
    else:
        report('ERROR', 'type differs', *where, exp, got)


def spec_props(name, seen=()):
    """Effective properties and required fields of a schema, including allOf parents."""
    if name in seen or name not in schemas:
        return {}, set()
    s = schemas[name]
    props, required = {}, set()
    for part in s.get('allOf', []):
        if '$ref' in part:
            p, r = spec_props(ref_name(part['$ref']), seen + (name,))
        else:
            p, r = part.get('properties', {}), set(part.get('required', []))
        props.update(p)
        required |= r
    props.update(s.get('properties', {}))
    required |= set(s.get('required', []))
    return props, required


# ---------- generated models ----------
def parse_model(path):
    src = open(path).read()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef))
    info = {'bases': [b.id for b in cls.bases if isinstance(b, ast.Name) and b.id != 'object'],
            'swagger_types': {}, 'attribute_map': {}, 'disc_map': {}, 'enum_values': [],
            'allowed': {}, 'required': set()}
    for st in cls.body:
        if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
            target = st.targets[0].id
            if target in ('swagger_types', 'attribute_map'):
                info[target] = ast.literal_eval(st.value)
            elif target == 'discriminator_value_class_map':
                # keys look like 'VALUE'.lower()
                info['disc_map'] = {
                    (k.func.value.value.lower() if isinstance(k, ast.Call) else k.value): v.value
                    for k, v in zip(st.value.keys, st.value.values)}
            elif isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                info['enum_values'].append(st.value.value)
        elif isinstance(st, ast.FunctionDef) and len(st.args.args) == 2:  # property setter
            body = ast.get_source_segment(src, st)
            m = re.search(r'allowed_values = (\[.*?\])', body)
            if m:
                info['allowed'][st.name] = ast.literal_eval(m.group(1))
            if 'must not be `None`' in body:
                info['required'].add(st.name)
    return cls.name, info


models_dir = os.path.join(args.package, 'models')
gen_classes = dict(parse_model(os.path.join(models_dir, f)) for f in sorted(os.listdir(models_dir))
                   if f.endswith('.py') and f != '__init__.py')
class_by_norm = {norm(c): c for c in gen_classes}


def gen_props(cls, seen=()):
    """Effective swagger_types, attribute_map, required and allowed values, including base classes."""
    if cls in seen or cls not in gen_classes:
        return {}, {}, set(), {}
    info = gen_classes[cls]
    types, amap, required, allowed = {}, {}, set(), {}
    for base in info['bases']:
        t, a, r, al = gen_props(base, seen + (cls,))
        types.update(t), amap.update(a), required.update(r), allowed.update(al)
    types.update(info['swagger_types']), amap.update(info['attribute_map'])
    required.update(info['required']), allowed.update(info['allowed'])
    return types, amap, required, allowed


def check_model(name, s):
    # reserved words are renamed with a 'Model' prefix, e.g. None -> ModelNone
    cls = class_by_norm.get(norm(name)) or class_by_norm.get('model' + norm(name))
    if cls is None:
        return report('ERROR', 'model missing', name)
    info = gen_classes[cls]
    if 'enum' in s:
        if sorted(map(str, s['enum'])) != sorted(info['enum_values']):
            report('ERROR', 'enum values differ', name, s['enum'], info['enum_values'])
        elif not all(isinstance(v, str) for v in s['enum']):
            report('WARN', 'non-string enum constants are strings', name, s['enum'])
        return
    props, required = spec_props(name)
    types, amap, gen_required, allowed = gen_props(cls)
    if props and not types:
        return report('ERROR', 'model has no fields', name, sorted(props))
    py_by_wire = {wire: py for py, wire in amap.items()}
    for wire, p in props.items():
        py = py_by_wire.get(wire)
        if py is None:
            report('ERROR', 'field missing', name, wire)
            continue
        compare_types((name, wire), expected_type(p), types[py])
        # enums on $ref fields are enforced by the referenced enum class,
        # generator ignores enums on non-string types
        if 'enum' in p and '$ref' not in p and p.get('type') == 'string' \
                and sorted(allowed.get(py, [])) != sorted(p['enum']):
            report('ERROR', 'enum values differ', '%s.%s' % (name, wire), p['enum'], allowed.get(py))
        if wire in required and py not in gen_required:
            report('WARN', 'required field not enforced', name, wire)
    for wire in py_by_wire:
        if wire not in props:
            report('ERROR', 'field not in spec', name, wire)
    if 'discriminator' in s:
        mapping = s['discriminator'].get('mapping') or {}
        children = [n for n, cs in schemas.items()
                    if any(part.get('$ref', '').endswith('/' + name) for part in cs.get('allOf', []))]
        if (mapping or children) and not info['disc_map']:
            report('ERROR', 'discriminator map empty', name, sorted(mapping) or children)
        for value, target in info['disc_map'].items():
            if target not in gen_classes:
                report('ERROR', 'discriminator maps to unknown class', name, value, target)
        missing = {v.lower() for v in mapping} - set(info['disc_map'])
        if missing:
            report('ERROR', 'discriminator values missing', name, sorted(missing))
    parents = [ref_name(p['$ref']) for p in s.get('allOf', []) if '$ref' in p]
    if parents and not info['bases']:
        report('WARN', 'allOf parent not inherited', name, parents)


# ---------- generated APIs ----------
def parse_api(path):
    src = open(path).read()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef))
    for fn in cls.body:
        if not (isinstance(fn, ast.FunctionDef) and fn.name.endswith('_with_http_info')):
            continue
        body = ast.get_source_segment(src, fn)
        method_path = re.search(r"call_api\(\s*'([^']+)', '([A-Z]+)'", body)
        params = {}
        for location, regex in (('path', r"path_params\['([^']+)'\] = params\['(\w+)'\]"),
                                ('query', r"query_params\.append\(\('([^']+)', params\['(\w+)'\]"),
                                ('header', r"header_params\['([^']+)'\] = params\['(\w+)'\]")):
            for wire, py in re.findall(regex, body):
                params[(location, wire)] = py
        content_type = re.search(r"select_header_content_type\(\s*(?:#.*\n\s*)?(\[[^\]]*\])", body)
        response_type = re.search(r"response_type=(?:'([^']*)'|None)", body)
        yield (method_path.group(2), method_path.group(1)), {
            'name': fn.name[:-len('_with_http_info')],
            'params': params,
            'doc_types': {n: t for t, n in re.findall(r':param (\S+) (\w+):', body)},
            'required': set(re.findall(r'Missing the required parameter `(\w+)`', body)),
            'body': "body_params = params['body']" in body,
            'form': re.findall(r"form_params\.append\(\('([^']+)'", body) + re.findall(r"local_var_files\['([^']+)'\]", body),
            'content_type': ast.literal_eval(content_type.group(1)) if content_type else [],
            'response_type': response_type.group(1) if response_type else None,
        }


api_dir = os.path.join(args.package, 'api')
gen_ops = {}
for f in sorted(os.listdir(api_dir)):
    if f.endswith('_api.py'):
        for key, op in parse_api(os.path.join(api_dir, f)):
            if key in gen_ops:
                report('ERROR', 'operation generated twice', key, gen_ops[key]['name'], op['name'])
            gen_ops[key] = op


def check_operation(key, o):
    g = gen_ops.get(key)
    op_id = o.get('operationId', '%s %s' % key)
    if g is None:
        return report('ERROR', 'operation missing', op_id, key)
    for prm in o.get('parameters', []):
        py = g['params'].get((prm['in'], prm['name']))
        if py is None:
            report('ERROR', 'param missing', op_id, prm['in'], prm['name'])
            continue
        if prm.get('required') and py not in g['required']:
            report('ERROR', 'required param not enforced', op_id, prm['name'])
        if py in g['doc_types']:
            compare_types((op_id, prm['name']), expected_type(prm.get('schema', {})), g['doc_types'][py])
    spec_params = {(p['in'], p['name']) for p in o.get('parameters', [])}
    for location, wire in g['params']:
        if (location, wire) not in spec_params:
            report('ERROR', 'param not in spec', op_id, location, wire)
    body = o.get('requestBody')
    if body:
        content = body.get('content', {})
        if 'multipart/form-data' in content:
            if not g['form'] and not g['body']:
                report('ERROR', 'request body missing', op_id, 'multipart/form-data')
        elif not g['body']:
            report('ERROR', 'request body missing', op_id, list(content))
        else:
            first = next(iter(content))
            if 'body' in g['doc_types']:
                compare_types((op_id, 'body'), expected_type(content[first].get('schema', {})), g['doc_types']['body'])
            if body.get('required') and 'body' not in g['required']:
                report('WARN', 'required body not enforced', op_id)
        if set(g['content_type']) != set(content):
            report('ERROR', 'content type differs', op_id, list(content), g['content_type'])
    elif g['body'] or g['form']:
        report('ERROR', 'request body not in spec', op_id)
    responses = o.get('responses', {})
    content = (responses.get('200') or responses.get('201') or {}).get('content', {})
    if content:
        first = next(iter(content))
        if g['response_type'] is None:
            report('ERROR', 'response type missing', op_id, first, expected_type(content[first].get('schema', {})))
        else:
            compare_types((op_id, 'response'), expected_type(content[first].get('schema', {})), g['response_type'])


spec_ops = [((m.upper(), p), o) for p, v in spec['paths'].items() for m, o in v.items() if m in HTTP_METHODS]
for key, o in spec_ops:
    check_operation(key, o)
for key in set(gen_ops) - {k for k, _ in spec_ops}:
    report('ERROR', 'operation not in spec', gen_ops[key]['name'], key)
for name, s in schemas.items():
    check_model(name, s)

# ---------- report ----------
print('Spec:    %s (OpenAPI %s, version %s)' % (args.spec, spec.get('openapi'), spec['info'].get('version')))
print('Package: %s' % args.package)
print('Operations: %d in spec, %d generated. Models: %d in spec, %d generated.\n'
      % (len(spec_ops), len(gen_ops), len(schemas), len(gen_classes)))
for severity in ('ERROR', 'WARN'):
    keys = sorted((k for k in findings if k[0] == severity), key=lambda k: -len(findings[k]))
    print('%s: %d' % (severity, sum(len(findings[k]) for k in keys)))
    for key in keys:
        items = findings[key]
        print('  %-40s %d' % (key[1], len(items)))
        for item in items if args.full else items[:3]:
            print('      ' + ' | '.join(map(str, item)))
        if not args.full and len(items) > 3:
            print('      ...')
if args.json:
    with open(args.json, 'w') as f:
        json.dump({'%s: %s' % k: v for k, v in findings.items()}, f, indent=1, default=str)
