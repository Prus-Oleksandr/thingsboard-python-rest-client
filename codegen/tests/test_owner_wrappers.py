"""Checks that assign/unassign-to-customer wrappers go through the owner API, with the HTTP layer faked.

Since 4.4 an entity is assigned to a customer by making the customer its owner, and unassigned by
making the tenant the owner again; the wrappers then return the updated entity, as in 4.3.

Usage: python3 codegen/tests/test_owner_wrappers.py [package_parent_dir]   (default: draft)
"""
import json
import os
import sys
import time

import jwt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'draft'))

from tb_rest_client.rest_client import RestClient
from tb_rest_client.models import CustomerId, AssetId, DeviceId, EdgeId, EntityViewId, DashboardId

ENTITY, CUSTOMER, TENANT = ('784f394c-42b6-435a-983c-b7beff2784f9', '11111111-42b6-435a-983c-b7beff2784f9',
                            '22222222-42b6-435a-983c-b7beff2784f9')
sent = []


class FakeResponse:
    status, reason = 200, 'OK'

    def __init__(self, data):
        self.data = data

    def getheaders(self):
        return {}


def fake_request(method, url, query_params=None, headers=None, post_params=None, body=None,
                 _preload_content=True, _request_timeout=None):
    path = url.replace('http://tb:8080', '')
    sent.append('%s %s' % (method, path.replace(ENTITY, '<id>').replace(CUSTOMER, '<customer>').replace(TENANT, '<tenant>')))
    if path == '/api/auth/user':
        return FakeResponse(json.dumps({'id': {'id': ENTITY, 'entityType': 'USER'}, 'email': 'user@example.com',
                                        'tenantId': {'id': TENANT, 'entityType': 'TENANT'}, 'authority': 'TENANT_ADMIN'}))
    # enough fields for every entity type the wrappers return
    return FakeResponse(json.dumps({'id': {'id': ENTITY, 'entityType': 'DEVICE'}, 'name': 'n', 'title': 't', 'type': 'default',
                                    'routingKey': 'rk', 'secret': 's', 'edgeLicenseKey': 'k', 'cloudEndpoint': 'http://tb',
                                    'entityId': {'id': ENTITY, 'entityType': 'DEVICE'}}))


client = RestClient('http://tb:8080')
client.token_login(jwt.encode({'sub': 'user@example.com', 'exp': int(time.time()) + 3600}, 'secret', algorithm='HS256'))
client.api_client.request = fake_request

customer = CustomerId(CUSTOMER, 'CUSTOMER')
cases = []
for entity_type, id_cls, name, getter in (('ASSET', AssetId, 'asset', 'asset'), ('DEVICE', DeviceId, 'device', 'device'),
                                          ('EDGE', EdgeId, 'edge', 'edge'),
                                          ('ENTITY_VIEW', EntityViewId, 'entity_view', 'entityView'),
                                          ('DASHBOARD', DashboardId, 'dashboard', 'dashboard')):
    entity_id = id_cls(ENTITY, entity_type)
    assign = getattr(client, 'assign_%s_to_customer' % name)
    unassign = getattr(client, 'unassign_%s_from_customer' % name)
    cases.append(('assign_%s_to_customer' % name, lambda a=assign, e=entity_id: a(customer, e),
                  ['POST /api/owner/CUSTOMER/<customer>/%s/<id>' % entity_type, 'GET /api/%s/<id>' % getter]))
    unassign_call = (lambda u=unassign, e=entity_id: u(customer, e)) if name == 'dashboard' else \
        (lambda u=unassign, e=entity_id: u(e))
    cases.append(('unassign_%s_from_customer' % name, unassign_call,
                  ['GET /api/auth/user', 'POST /api/owner/TENANT/<tenant>/%s/<id>' % entity_type, 'GET /api/%s/<id>' % getter]))

failed = 0
for name, call, expected in cases:
    sent.clear()
    try:
        result = call()
        ok = sent == expected and result is not None
        print('%-4s %-36s %s' % ('OK' if ok else 'FAIL', name, ' | '.join(sent)) + ('' if ok else '\n     expected %s' % expected))
    except Exception as e:
        ok = False
        print('FAIL %-36s %s: %s' % (name, type(e).__name__, e))
    failed += not ok
print('%d/%d OK' % (len(cases) - failed, len(cases)))
sys.exit(1 if failed else 0)
