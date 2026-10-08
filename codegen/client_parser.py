"""Parses swagger-codegen v3 Python client code (api and models) with ast."""
import ast
import os
import re


def java_method(summary):
    """Controller method name from an operation summary.

    ThingsBoard summaries end with it, 'Get Tenant Asset (getTenantAsset)', or are just
    the name. It stays the same when the path or the operationId change between versions.
    """
    m = re.search(r'\(([a-z]\w*)\)$', summary) or re.match(r'^([a-z]\w*)$', summary)
    return m.group(1) if m else None


def parse_api(path):
    """Returns the operations of a generated *_api.py file, one dict per *_with_http_info method."""
    src = open(path).read()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef))
    # required params are positional args of the public method
    positional = {fn.name: [a.arg for a in fn.args.args[1:]] for fn in cls.body if isinstance(fn, ast.FunctionDef)}
    summaries = {fn.name: (ast.get_docstring(fn) or '').split('\n')[0].replace('# noqa: E501', '').strip()
                 for fn in cls.body if isinstance(fn, ast.FunctionDef)}
    ops = []
    for fn in cls.body:
        if not (isinstance(fn, ast.FunctionDef) and fn.name.endswith('_with_http_info')):
            continue
        body = ast.get_source_segment(src, fn)
        call = re.search(r"call_api\(\s*'([^']+)',\s*'([A-Z]+)'", body)
        params = {}
        for location, regex in (('path', r"path_params\['([^']+)'\] = params\['(\w+)'\]"),
                                ('query', r"query_params\.append\(\('([^']+)', params\['(\w+)'\]"),
                                ('header', r"header_params\['([^']+)'\] = params\['(\w+)'\]"),
                                ('form', r"form_params\.append\(\('([^']+)', params\['(\w+)'\]"),
                                ('form', r"local_var_files\['([^']+)'\] = params\['(\w+)'\]")):
            for wire, py in re.findall(regex, body):
                params[(location, wire)] = py
        all_params = re.search(r'all_params = (\[.*?\])', body)
        content_type = re.search(r"select_header_content_type\(\s*(?:#.*\n\s*)?(\[[^\]]*\])", body)
        response_type = re.search(r"response_type=(?:'([^']*)'|None)", body)
        name = fn.name[:-len('_with_http_info')]
        summary = summaries.get(name, '')
        ops.append({
            'class': cls.name,
            'file': path,
            'name': name,
            'summary': summary,
            'java': java_method(summary),
            'positional': positional.get(name, []),
            'http_method': call.group(2),
            # older springfox specs put query params into the path: {?a,b}, ?scope=ANY, ?a=b{&c,d}
            'path': re.sub(r'\?[^{}]*$', '', re.sub(r'\{[?&][^}]*\}', '', call.group(1))),
            'params': params,
            'all_params': ast.literal_eval(all_params.group(1)) if all_params else [],
            'doc_types': {n: t for t, n in re.findall(r':param (\S+) (\w+):', body)},
            'required': set(re.findall(r'Missing the required parameter `(\w+)`', body)),
            'body': "body_params = params['body']" in body,
            'form': re.findall(r"form_params\.append\(\('([^']+)'", body) + re.findall(r"local_var_files\['([^']+)'\]", body),
            'content_type': ast.literal_eval(content_type.group(1)) if content_type else [],
            'response_type': response_type.group(1) if response_type else None,
        })
    return ops


def parse_api_dir(api_dir):
    ops = []
    for f in sorted(os.listdir(api_dir)):
        if f.endswith('_api.py'):
            ops.extend(parse_api(os.path.join(api_dir, f)))
    return ops


def parse_model(path):
    """Returns (class name, info) for a generated model file."""
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


def parse_models_dir(models_dir):
    return dict(parse_model(os.path.join(models_dir, f)) for f in sorted(os.listdir(models_dir))
                if f.endswith('.py') and f != '__init__.py')
