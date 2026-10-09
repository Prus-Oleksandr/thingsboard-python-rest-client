"""Calls wrappers of operations the spec types as 'string' (JSON or files) with the response bodies
a 4.4 server returned (see response_type_overrides in codegen/postprocess.py) and checks what the
caller gets.

Usage: python3 codegen/tests/test_string_responses.py [package_parent_dir]   (default: draft)
"""
import os
import sys
import time

import jwt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'draft'))

from tb_rest_client.rest_client import RestClient
from tb_rest_client.models import DeviceId, EdgeId, TbResourceId

U = '784f394c-42b6-435a-983c-b7beff2784f9'
body = [b'']


class FakeResponse:
    status, reason = 200, 'OK'

    def __init__(self):
        self.data = body[0]

    def getheaders(self):
        return {}


def fake_request(method, url, query_params=None, headers=None, post_params=None, body=None,
                 _preload_content=True, _request_timeout=None):
    return FakeResponse()


c = RestClient('http://tb:8080')
c.token_login(jwt.encode({'sub': 't', 'exp': int(time.time()) + 3600}, 's', algorithm='HS256'))
c.api_client.request = fake_request
device = DeviceId(id=U, entity_type='DEVICE')
passed = 0
cases = [
    ('get_device_attributes', b'{"client":{"q3attr":4}}', {'client': {'q3attr': 4}},
     lambda: c.get_device_attributes('token', 'a', 'b')),
    ('get_persisted_rpc_by_device', b'{"data":[],"totalPages":0,"totalElements":0,"hasNext":false}',
     {'data': [], 'totalPages': 0, 'totalElements': 0, 'hasNext': False},
     lambda: c.get_persisted_rpc_by_device(device, 10, 0, None)),
    ('find_missing_to_related_rule_chains', b'{}', {},
     lambda: c.find_missing_to_related_rule_chains(EdgeId(id=U, entity_type='EDGE'))),
    ('provision_device', b'{"errorMsg":"Provision data was not found!","status":"NOT_FOUND"}',
     {'errorMsg': 'Provision data was not found!', 'status': 'NOT_FOUND'},
     lambda: c.provision_device('{}')),
    ('handle_two_way_device_rpc_request_v1', b'{"result":"ok"}', {'result': 'ok'},
     lambda: c.handle_two_way_device_rpc_request_v1(device, '{"method":"m","params":{}}')),
    ('handle_one_way_device_rpc_request_v1 (empty body)', b'', None,
     lambda: c.handle_one_way_device_rpc_request_v1(device, '{"method":"m","params":{}}')),
    ('save_entity_telemetry (empty body)', b'', None,
     lambda: c.save_entity_telemetry(device, 'ANY', {'t': 1})),
    ('post_telemetry (empty body)', b'', None,
     lambda: c.post_telemetry('token', '{"t":1}')),
    ('get_help_base_url (plain text)', b'https://raw.githubusercontent.com/x', 'https://raw.githubusercontent.com/x',
     lambda: c.get_help_base_url()),
    ('get_login_processing_url (JSON string)', b'"/login/oauth2/code/"', '/login/oauth2/code/',
     lambda: c.get_login_processing_url()),
    ('get_privacy_policy (empty body)', b'', '',
     lambda: c.get_privacy_policy()),
    ('get_firmware (binary)', b'\x89PNG\r\n\x1a\n\xff', b'\x89PNG\r\n\x1a\n\xff',
     lambda: c.get_firmware('token', 'fw', '1')),
    # files ('format: binary' in the spec) are returned as the raw body even when it is text or JSON
    ('download_full_translation (JSON file)', b'{"home":"Home"}', b'{"home":"Home"}',
     lambda: c.download_full_translation('en_US')),
    ('download_js_resource_if_changed (text file)', b'export const a = 1;', b'export const a = 1;',
     lambda: c.download_js_resource_if_changed(TbResourceId(id=U, entity_type='TB_RESOURCE'))),
    ('download_image (SVG)', b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'<svg xmlns="http://www.w3.org/2000/svg"/>',
     lambda: c.download_image('tenant', 'logo.svg')),
]
for name, data, expected, call in cases:
    body[0] = data
    try:
        result = call()
    except Exception as e:  # report every case, do not stop at the first failure
        result = e
    ok = result == expected and type(result) is type(expected)
    passed += ok
    print('%-4s %s -> %r' % ('OK' if ok else 'FAIL', name, result))

print('%d/%d OK' % (passed, len(cases)))
sys.exit(0 if passed == len(cases) else 1)
