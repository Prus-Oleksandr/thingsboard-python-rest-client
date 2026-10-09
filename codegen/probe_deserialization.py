"""Deserializes real responses of a ThingsBoard server with the generated client to find models that
do not accept what the server sends (e.g. null in a field the spec marks required).

Usage: python3 codegen/probe_deserialization.py [package_parent_dir]   (default: draft)

Read-only: calls every GET operation that needs only paging params (or none), then the GET
operations with one '<entity>_id' param for up to 3 ids of that entity type seen in the answers.
Server and credentials as in probe_endpoints.py: TB_URL, and TB_TENANT_TOKEN (a JWT) or
TB_TENANT_USERNAME + TB_TENANT_PASSWORD.
"""
import glob
import importlib
import json
import os
import re
import sys
import traceback
import urllib.request

CODEGEN = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CODEGEN)
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(CODEGEN), 'draft'))

from client_parser import parse_api  # noqa: E402
from tb_rest_client.api_client import ApiClient  # noqa: E402
from tb_rest_client.configuration import Configuration  # noqa: E402
from tb_rest_client.rest import ApiException  # noqa: E402

base = os.environ.get('TB_URL', 'http://localhost:8080').rstrip('/')
token = os.environ.get('TB_TENANT_TOKEN')
if not token:
    username, password = os.environ.get('TB_TENANT_USERNAME'), os.environ.get('TB_TENANT_PASSWORD')
    if not username or not password:
        sys.exit('Set TB_TENANT_TOKEN or TB_TENANT_USERNAME and TB_TENANT_PASSWORD')
    req = urllib.request.Request(base + '/api/auth/login', method='POST', headers={'Content-Type': 'application/json'},
                                 data=json.dumps({'username': username, 'password': password}).encode())
    token = json.load(urllib.request.urlopen(req))['token']

conf = Configuration()
conf.host = base
conf.api_key['X-Authorization'] = token
conf.api_key_prefix['X-Authorization'] = 'Bearer'
client = ApiClient(conf)
package_dir = os.path.dirname(importlib.import_module('tb_rest_client').__file__)
apis = []
for f in sorted(glob.glob(os.path.join(package_dir, 'api', '*_api.py'))):
    ops = parse_api(f)
    if ops:
        module = importlib.import_module('tb_rest_client.api.' + os.path.basename(f)[:-3])
        apis.append((getattr(module, ops[0]['class'])(client), ops))

calls = ok = http_errors = models = 0
errors = []
ids = {}  # entity type -> ids seen in the answers


def collect(obj, depth=0):
    """Counts models in a result and remembers entity ids by entity type."""
    global models
    if depth > 6 or obj is None:
        return
    if isinstance(obj, list):
        for x in obj:
            collect(x, depth + 1)
    elif hasattr(obj, 'swagger_types'):
        models += 1
        if hasattr(obj, 'entity_type') and isinstance(getattr(obj, 'id', None), str):
            ids.setdefault(obj.entity_type, set()).add(obj.id)
        for attr in obj.swagger_types:
            collect(getattr(obj, attr, None), depth + 1)


def call(api, op, *args, **kwargs):
    global calls, ok, http_errors
    calls += 1
    try:
        collect(getattr(api, op['name'])(*args, **kwargs))
        ok += 1
    except ApiException:
        http_errors += 1
    except Exception as e:
        where = traceback.extract_tb(e.__traceback__)[-1]
        errors.append('%s.%s GET %s -> %s\n      %s: %s (%s:%d)' % (
            op['class'], op['name'], op['path'], op['response_type'], type(e).__name__, str(e)[:160],
            os.path.basename(where.filename), where.lineno))


def readable(op):
    return op['http_method'] == 'GET' and op['response_type'] not in (None, 'bytes')


for api, ops in apis:
    for op in ops:
        if readable(op) and set(op['positional']) <= {'page_size', 'page'}:
            call(api, op, **({'page_size': 50, 'page': 0} if op['positional'] else {}))
for api, ops in apis:
    for op in ops:
        m = re.fullmatch(r'(\w+?)_id', op['positional'][0]) if readable(op) and len(op['positional']) == 1 else None
        for value in sorted(ids.get(m.group(1).upper(), ()))[:3] if m else ():
            call(api, op, value)

print('%d calls: %d deserialized (%d models), %d HTTP errors (403/404/... not checked), %d deserialization errors'
      % (calls, ok, models, http_errors, len(errors)))
print('entity types seen: %s' % ', '.join('%s %d' % (k, len(v)) for k, v in sorted(ids.items())))
for e in errors:
    print('  ' + e)
sys.exit(1 if errors else 0)
