"""Sends raw requests to a ThingsBoard server to see whether endpoints exist, including ones
hidden from the OpenAPI spec (springdoc documents one operation per path + method).

Usage: python3 codegen/probe_endpoints.py <requests.json>

Server and credentials come from the environment:
  TB_URL                                       default http://localhost:8080
  TB_TENANT_USERNAME, TB_TENANT_PASSWORD       required
  TB_SYSADMIN_USERNAME, TB_SYSADMIN_PASSWORD   only for requests with "user": "sysadmin"

requests.json is a list of {"label", "method", "path", "user"?: "tenant"|"sysadmin", "body"?: raw string}.
Placeholders in paths: {tenantId} (current tenant), {deviceId} (first device of the tenant),
{randomId} (an id that does not exist, so write requests cannot change anything).

How to read the answers:
  404 'No static resource ...'          no such route on the server
  404 '... is not found' / 'Requested item wasn't found!'   route exists, the entity does not
  405 'Request method ... is not supported'                  path exists, not for this HTTP method
  400 'Parameter conditions ... not met'                     path exists, the message lists the
                                                             param variants the server accepts
  200                                   the endpoint works (hidden if it is not in the spec)
"""
import json
import os
import sys
import urllib.error
import urllib.request

RANDOM_ID = 'a0000000-0000-11f1-0000-000000000001'
base = os.environ.get('TB_URL', 'http://localhost:8080').rstrip('/')


def call(method, path, token=None, body=None):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if token:
        headers['X-Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, method=method, headers=headers,
                                 data=body.encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode(errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors='replace')


def login(user):
    username = os.environ.get('TB_%s_USERNAME' % user.upper())
    password = os.environ.get('TB_%s_PASSWORD' % user.upper())
    if not username or not password:
        sys.exit('Set TB_%s_USERNAME and TB_%s_PASSWORD' % (user.upper(), user.upper()))
    status, data = call('POST', '/api/auth/login', body=json.dumps({'username': username, 'password': password}))
    if status != 200:
        sys.exit('%s login failed: %d %s' % (user, status, data[:200]))
    return json.loads(data)['token']


def summarize(data):
    try:
        d = json.loads(data)
    except ValueError:
        return repr(data[:120])
    if isinstance(d, dict) and ('message' in d or 'error' in d):
        return 'message=%r' % d.get('message', d.get('error'))
    if isinstance(d, dict) and 'data' in d:
        return 'page: %d items, totalElements=%s' % (len(d['data']), d.get('totalElements'))
    if isinstance(d, list):
        return 'list: %d items' % len(d)
    return data[:120]


requests = json.load(open(sys.argv[1]))
tokens = {'tenant': login('tenant')}
if any(r.get('user') == 'sysadmin' for r in requests):
    tokens['sysadmin'] = login('sysadmin')
values = {'randomId': RANDOM_ID}
status, data = call('GET', '/api/auth/user', tokens['tenant'])
values['tenantId'] = json.loads(data)['tenantId']['id']
status, data = call('GET', '/api/tenant/devices?pageSize=1&page=0', tokens['tenant'])
devices = json.loads(data).get('data', []) if status == 200 else []
values['deviceId'] = devices[0]['id']['id'] if devices else RANDOM_ID

for r in requests:
    path = r['path'].format(**values)
    status, data = call(r['method'], path, tokens[r.get('user', 'tenant')], r.get('body'))
    shown = path.replace(values['tenantId'], '{tenantId}').replace(values['deviceId'], '{deviceId}').replace(RANDOM_ID, '{randomId}')
    print('%-46s %-6s %-64s -> %d  %s' % (r['label'][:46], r['method'], shown[:64], status, summarize(data)[:150]))
