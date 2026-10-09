"""Calls the hand-fixed wrappers (moved and 4.3-broken endpoints) with the HTTP layer faked and checks the requests.

Usage: python3 codegen/tests/test_manual_fixes.py [package_parent_dir]   (default: draft)
"""
import os
import sys
import time

import jwt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'draft'))

from tb_rest_client.rest_client import RestClient
from tb_rest_client.models import DeviceId, RpcId, TbResourceId

UUID = '784f394c-42b6-435a-983c-b7beff2784f9'
DEVICE = DeviceId(id=UUID, entity_type='DEVICE')
sent = []


class FakeResponse:
    status, reason, data = 200, 'OK', '{}'

    def getheaders(self):
        return {}


def fake_request(method, url, query_params=None, headers=None, post_params=None, body=None,
                 _preload_content=True, _request_timeout=None):
    query = {}
    for k, v in query_params or []:
        query[k] = query[k] + [v] if isinstance(query.get(k), list) else ([query[k], v] if k in query else v)
    sent.append((method, url.replace('http://tb:8080', ''), query))
    return FakeResponse()


def client(cls):
    c = cls('http://tb:8080')
    c.token_login(jwt.encode({'sub': 't', 'exp': int(time.time()) + 3600}, 's', algorithm='HS256'))
    c.api_client.request = fake_request
    # responses are not checked here, only the requests
    c.api_client.deserialize = lambda response, response_type: None
    return c


ce, pe = client(RestClient), client(RestClient)
cases = [
    (lambda: ce.find_by_from(DEVICE, 'Contains'), ('GET', '/api/relations/from/DEVICE/%s/Contains' % UUID, {})),
    (lambda: ce.find_by_from_v1(DEVICE, 'DEVICE', 'COMMON'), ('GET', '/api/relations/from/DEVICE/%s' % UUID, {'relationTypeGroup': 'COMMON'})),
    (lambda: ce.find_info_by_to(DEVICE, 'DEVICE'), ('GET', '/api/relations/info/to/DEVICE/%s' % UUID, {})),
    (lambda: ce.find_by_to(DEVICE, 'Contains'), ('GET', '/api/relations/to/DEVICE/%s/Contains' % UUID, {})),
    (lambda: ce.get_timeseries(DEVICE, 1, 2, 'temp'), ('GET', '/api/plugins/telemetry/DEVICE/%s/values/timeseries/history' % UUID,
                                                       {'keys': 'temp', 'startTs': 1, 'endTs': 2})),
    (lambda: ce.get_user_settings(), ('GET', '/api/user/settings/general', {})),
    (lambda: ce.put_user_settings({'a': 1}), ('PUT', '/api/user/settings/general', {})),
    (lambda: ce.get_tenant_profiles_by_ids(['a', 'b']), ('GET', '/api/tenantProfiles/list', {'ids': 'a,b'})),
    (lambda: ce.get_tenant_edge('e1'), ('GET', '/api/tenant/edge', {'edgeName': 'e1'})),
    (lambda: ce.get_tenant_edge_infos(10, 0), ('GET', '/api/edgeInfos/all', {'pageSize': 10, 'page': 0})),
    (lambda: ce.get_tenant_entity_view_infos(10, 0), ('GET', '/api/entityViewInfos/all', {'pageSize': 10, 'page': 0})),
    (lambda: ce.get_notifications(10, 0, delivery_method='WEB'), ('GET', '/api/notifications', {'pageSize': 10, 'page': 0, 'deliveryMethod': 'WEB'})),
    (lambda: ce.get_mobile_app_info_by_id(UUID), ('GET', '/api/mobile/app/%s' % UUID, {})),
    (lambda: ce.get_tenant_mobile_app_infos(10, 0), ('GET', '/api/mobile/app', {'pageSize': 10, 'page': 0})),
    (lambda: ce.get_client_registration_templates(), ('GET', '/api/oauth2/config/template', {})),
    (lambda: ce.activate_instance('secret', '2026-01-01'), ('POST', '/api/license/activateInstance', {'licenseSecret': 'secret', 'releaseDate': '2026-01-01'})),
    (lambda: ce.delete_resource(RpcId(id=UUID, entity_type='RPC')), ('DELETE', '/api/rpc/persistent/%s' % UUID, {})),
    (lambda: ce.delete_resource_v1(TbResourceId(id=UUID, entity_type='TB_RESOURCE')), ('DELETE', '/api/resource/%s' % UUID, {})),
    (lambda: ce.get_resource_by_id(TbResourceId(id=UUID, entity_type='TB_RESOURCE')), ('GET', '/api/resource/%s' % UUID, {})),
    (lambda: ce.handle_rule_engine_request_for_entity(DEVICE, {}), ('POST', '/api/rule-engine/DEVICE/%s' % UUID, {})),
    (lambda: ce.handle_rule_engine_request_for_entity_with_timeout(DEVICE, 5000, {}), ('POST', '/api/rule-engine/DEVICE/%s/5000' % UUID, {})),
    (lambda: ce.handle_rule_engine_request_for_entity_with_queue_and_timeout(DEVICE, 'Main', 5000, {}), ('POST', '/api/rule-engine/DEVICE/%s/Main/5000' % UUID, {})),
    (lambda: ce.handle_rule_engine_request_for_user({}), ('POST', '/api/rule-engine/', {})),
    (lambda: pe.get_client_registration_templates(), ('GET', '/api/oauth2/config/template', {})),
    (lambda: pe.get_tenant_edge('e1'), ('GET', '/api/tenant/edge', {'edgeName': 'e1'})),
    (lambda: pe.get_device_profiles_by_ids(['a']), ('GET', '/api/deviceProfileInfos/list', {'deviceProfileIds': 'a'})),
    (lambda: pe.get_custom_menu(), ('GET', '/api/customMenu', {})),
]
failed = 0
for call, expected in cases:
    try:
        call()
        ok = sent[-1] == expected
        print('%-4s %s %s %s' % ('OK' if ok else 'FAIL', *sent[-1]) + ('' if ok else '   expected %s' % (expected,)))
    except Exception as e:
        ok = False
        print('FAIL %s -> %s: %s' % (expected[1], type(e).__name__, e))
    failed += not ok
print('%d/%d OK' % (len(cases) - failed, len(cases)))
sys.exit(1 if failed else 0)
