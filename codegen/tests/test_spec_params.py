"""Calls wrappers with the spec params added to them in 4.4 (Q6), left out where the spec makes them
optional, or missing where the spec requires them, with the HTTP layer faked and checks the result.

Usage: python3 codegen/tests/test_spec_params.py [package_parent_dir]   (default: draft)
"""
import os
import sys
import time

import jwt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'draft'))

from tb_rest_client.rest_client import RestClient
from tb_rest_client.models import Device, DeviceId, OtaPackageId

U = '784f394c-42b6-435a-983c-b7beff2784f9'
sent = []


class FakeResponse:
    status, reason, data = 200, 'OK', b'{}'

    def getheaders(self):
        return {}


def fake_request(method, url, query_params=None, headers=None, post_params=None, body=None,
                 _preload_content=True, _request_timeout=None):
    extra = {k: v for k, v in (headers or {}).items() if k in ('Accept-Encoding', 'If-None-Match')}
    sent.append((method, url.replace('http://tb:8080', ''), list(query_params or []), extra))
    return FakeResponse()


c = RestClient('http://tb:8080')
c.token_login(jwt.encode({'sub': 't', 'exp': int(time.time()) + 3600}, 's' * 32, algorithm='HS256'))
c.api_client.request = fake_request
c.api_client.deserialize = lambda response, response_type: None
device = DeviceId(id=U, entity_type='DEVICE')
cases = [
    (lambda: c.get_widget_types(10, 0, scada_first=True),
     ('GET', '/api/widgetTypes', [('pageSize', 10), ('page', 0), ('scadaFirst', True)], {})),
    (lambda: c.get_device_attributes('token', None, None, all_client_keys=True, all_shared_keys=False),
     ('GET', '/api/v1/token/attributes', [('allClientKeys', True), ('allSharedKeys', False)], {})),
    (lambda: c.get_attributes(device, key=['a', 'b']),
     ('GET', '/api/plugins/telemetry/DEVICE/%s/values/attributes' % U, [('key', 'a'), ('key', 'b')], {})),
    (lambda: c.save_device(Device(name='d'), name_conflict_policy='UNIQUIFY', uniquify_strategy='RANDOM'),
     ('POST', '/api/device', [('nameConflictPolicy', 'UNIQUIFY'), ('uniquifyStrategy', 'RANDOM')], {})),
    (lambda: c.get_resources(10, 0, resource_type=['JS_MODULE', 'IMAGE']),
     ('GET', '/api/resource', [('pageSize', 10), ('page', 0), ('resourceType', 'JS_MODULE'), ('resourceType', 'IMAGE')], {})),
    (lambda: c.get_jobs(10, 0, types=['CF_REPROCESSING'], include_customers=True),
     ('GET', '/api/jobs', [('pageSize', 10), ('page', 0), ('types', 'CF_REPROCESSING'), ('includeCustomers', True)], {})),
    (lambda: c.get_privacy_policy(pkg_name='app', platform='ANDROID'),
     ('GET', '/api/noauth/selfRegistration/privacyPolicy', [('pkgName', 'app'), ('platform', 'ANDROID')], {})),
    (lambda: c.get_home_dashboard(accept_encoding='gzip'),
     ('GET', '/api/dashboard/home', [], {'Accept-Encoding': 'gzip'})),
    # params optional in the spec can be left out
    (lambda: c.get_persisted_rpc_by_device(device, 10, 0),
     ('GET', '/api/rpc/persistent/device/%s' % U, [('pageSize', 10), ('page', 0)], {})),
    (lambda: c.get_device_attributes('token'),
     ('GET', '/api/v1/token/attributes', [], {})),
    (lambda: c.get_timeseries(device, 1, 2, key=['t']),
     ('GET', '/api/plugins/telemetry/DEVICE/%s/values/timeseries/history' % U, [('startTs', 1), ('endTs', 2), ('key', 't')], {})),
    (lambda: c.delete_entity_attributes(device, 'SERVER_SCOPE', key=['a']),
     ('DELETE', '/api/plugins/telemetry/DEVICE/%s/SERVER_SCOPE' % U, [('key', 'a')], {})),
    # params required in the spec must be passed
    (lambda: c.save_entity_telemetry(device, 'ANY'), 'TypeError'),
    (lambda: c.save_ota_package_data(OtaPackageId(id=U, entity_type='OTA_PACKAGE'), 'SHA256', '/tmp/no-such-fw.bin'),
     'FileNotFoundError'),  # the file is opened only after the required params are checked
]
passed = 0
for call, expected in cases:
    del sent[:]
    try:
        call()
        got = sent[-1] if sent else None
    except Exception as e:  # report every case; an expected error is given by its class name
        got = type(e).__name__
    ok = got == expected
    passed += ok
    print('%-4s %s' % ('OK' if ok else 'FAIL', got if ok else 'expected %s\n     got      %s' % (expected, got)))
print('%d/%d OK' % (passed, len(cases)))
sys.exit(0 if passed == len(cases) else 1)
