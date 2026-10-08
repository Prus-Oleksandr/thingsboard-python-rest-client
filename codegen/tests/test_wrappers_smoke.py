"""Calls a few RestClient wrappers end to end with the HTTP layer faked.

Usage: python3 codegen/tests/test_wrappers_smoke.py [package_parent_dir]   (default: draft)
"""
import os
import sys
import time

import jwt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'draft'))

from tb_rest_client.rest_client import RestClient
from tb_rest_client.models import DeviceId, AssetId

sent = []


class FakeResponse:
    status, reason = 200, 'OK'

    def __init__(self, data):
        self.data = data

    def getheaders(self):
        return {}


def fake_request(method, url, query_params=None, headers=None, post_params=None, body=None,
                 _preload_content=True, _request_timeout=None):
    sent.append((method, url, query_params, body))
    return FakeResponse('{"data": [], "totalPages": 0, "totalElements": 0, "hasNext": false}'
                        if 'page' in str(query_params) else '{}')


token = jwt.encode({'sub': 'tenant@thingsboard.org', 'exp': int(time.time()) + 3600}, 'secret', algorithm='HS256')
failed = False
for cls in (RestClient,):
    client = cls('http://tb:8080')
    client.token_login(token)
    client.api_client.request = fake_request
    cases = [
        ('get_tenant_assets', lambda: client.get_tenant_assets(page_size=10, page=0, text_search='a'),
         ('GET', 'http://tb:8080/api/tenant/assets', [('pageSize', 10), ('page', 0), ('textSearch', 'a')])),
        ('get_device_by_id', lambda: client.get_device_by_id(DeviceId('784f394c-42b6-435a-983c-b7beff2784f9', 'DEVICE')),
         ('GET', 'http://tb:8080/api/device/784f394c-42b6-435a-983c-b7beff2784f9', [])),
        ('delete_asset', lambda: client.delete_asset(AssetId('11111111-42b6-435a-983c-b7beff2784f9', 'ASSET')),
         ('DELETE', 'http://tb:8080/api/asset/11111111-42b6-435a-983c-b7beff2784f9', [])),
    ]
    for name, call, expected in cases:
        try:
            result = call()
            got = sent[-1][:3]
            ok = got[0] == expected[0] and got[1] == expected[1] and list(got[2] or []) == expected[2]
            print('%-4s %s.%s -> %s %s %s | %s' % ('OK' if ok else 'FAIL', cls.__name__, name, *got, type(result).__name__))
        except Exception as e:
            ok = False
            print('FAIL %s.%s -> %s: %s' % (cls.__name__, name, type(e).__name__, e))
        failed |= not ok
    headers = client.configuration.api_key
    print('     auth header value set:', headers.get('X-Authorization', '')[:12] + '...')
sys.exit(1 if failed else 0)
