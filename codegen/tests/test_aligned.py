"""Calls the wrappers aligned with the 4.4 spec params with the HTTP layer faked and checks the requests.

Usage: python3 codegen/tests/test_aligned.py [package_parent_dir]   (default: draft)
"""
import os
import sys
import time

import jwt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'draft'))

from tb_rest_client.rest_client import RestClient
from tb_rest_client.models import (CustomerId, DeviceProfileId, AssetProfileId, DashboardId, WidgetTypeId,
                                   WidgetsBundleId, EdgeId, NotificationTarget)

U = '784f394c-42b6-435a-983c-b7beff2784f9'
sent = []


class FakeResponse:
    status, reason, data = 200, 'OK', '{}'

    def getheaders(self):
        return {}


def fake_request(method, url, query_params=None, headers=None, post_params=None, body=None,
                 _preload_content=True, _request_timeout=None):
    extra = {k: v for k, v in (headers or {}).items() if k in ('Accept-Encoding', 'If-None-Match')}
    sent.append((method, url.replace('http://tb:8080', ''), dict(query_params or []), extra, body is not None))
    return FakeResponse()


def client(cls):
    c = cls('http://tb:8080')
    c.token_login(jwt.encode({'sub': 't', 'exp': int(time.time()) + 3600}, 's', algorithm='HS256'))
    c.api_client.request = fake_request
    c.api_client.deserialize = lambda response, response_type: None
    return c


ce, pe = client(RestClient), client(RestClient)
customer = CustomerId(id=U, entity_type='CUSTOMER')
cases = [
    (lambda: ce.get_customer_asset_infos(customer, 10, 0, include_customers=True,
                                         asset_profile_id=AssetProfileId(id=U, entity_type='ASSET_PROFILE')),
     ('GET', '/api/customer/%s/assetInfos' % U, {'pageSize': 10, 'page': 0, 'includeCustomers': True, 'assetProfileId': U}, {}, False)),
    (lambda: ce.get_customer_dashboards(customer, 10, 0, include_customers=False),
     ('GET', '/api/customer/%s/dashboards' % U, {'pageSize': 10, 'page': 0, 'includeCustomers': False}, {}, False)),
    (lambda: ce.get_tenant_queues_by_service_type('TB-RULE-ENGINE', 10, 0),
     ('GET', '/api/queues', {'serviceType': 'TB-RULE-ENGINE', 'pageSize': 10, 'page': 0}, {}, False)),
    (lambda: ce.get_widgets_bundles(10, 0, tenant_only=True),
     ('GET', '/api/widgetsBundles', {'pageSize': 10, 'page': 0, 'tenantOnly': True}, {}, False)),
    (lambda: ce.get_dashboard_by_id(DashboardId(id=U, entity_type='DASHBOARD'), include_resources=True, accept_encoding='gzip'),
     ('GET', '/api/dashboard/%s' % U, {'includeResources': True}, {'Accept-Encoding': 'gzip'}, False)),
    (lambda: ce.get_bundle_widget_types_details(WidgetsBundleId(id=U, entity_type='WIDGETS_BUNDLE'), include_resources=True),
     ('GET', '/api/widgetTypesDetails', {'widgetsBundleId': U, 'includeResources': True}, {}, False)),
    (lambda: ce.get_widget_type_by_id(WidgetTypeId(id=U, entity_type='WIDGET_TYPE'), include_resources=False),
     ('GET', '/api/widgetType/%s' % U, {'includeResources': False}, {}, False)),
    (lambda: ce.get_recipients_for_notification_target_config({'name': 't', 'configuration': {'type': 'PLATFORM_USERS'}}, 10, 0),
     ('POST', '/api/notification/target/recipients', {'pageSize': 10, 'page': 0}, {}, True)),
    (lambda: ce.download_image_preview('tenant', 'logo.png', if_none_match='etag1'),
     ('GET', '/api/images/tenant/logo.png/preview', {}, {'If-None-Match': 'etag1'}, False)),
    (lambda: ce.get_tenant_asset_infos(10, 0, asset_profile_id=AssetProfileId(id=U, entity_type='ASSET_PROFILE')),
     ('GET', '/api/assetInfos/all', {'pageSize': 10, 'page': 0, 'assetProfileId': U}, {}, False)),
    (lambda: ce.get_tenant_device_infos(10, 0, device_profile_id=DeviceProfileId(id=U, entity_type='DEVICE_PROFILE'), active=True),
     ('GET', '/api/deviceInfos/all', {'pageSize': 10, 'page': 0, 'deviceProfileId': U, 'active': True}, {}, False)),
    (lambda: ce.get_customer_device_infos(customer, 10, 0, active=False),
     ('GET', '/api/customer/%s/deviceInfos' % U, {'pageSize': 10, 'page': 0, 'active': False}, {}, False)),
    (lambda: pe.get_customer_device_infos(customer, 10, 0, include_customers=True),
     ('GET', '/api/customer/%s/deviceInfos' % U, {'pageSize': 10, 'page': 0, 'includeCustomers': True}, {}, False)),
    (lambda: pe.get_all_customer_infos(10, 0, include_customers=True),
     ('GET', '/api/customerInfos/all', {'pageSize': 10, 'page': 0, 'includeCustomers': True}, {}, False)),
    (lambda: pe.get_customer_customer_infos(customer, 10, 0),
     ('GET', '/api/customer/%s/customerInfos' % U, {'pageSize': 10, 'page': 0}, {}, False)),
    (lambda: pe.mobile_login('org.thingsboard.app', 'ANDROID'),
     ('GET', '/api/noauth/login', {'pkgName': 'org.thingsboard.app', 'platform': 'ANDROID'}, {}, False)),
    (lambda: pe.get_scheduler_events(10, 0, type='REPORT', edge_id=EdgeId(id=U, entity_type='EDGE')),
     ('GET', '/api/schedulerEvents', {'pageSize': 10, 'page': 0, 'type': 'REPORT', 'edgeId': U}, {}, False)),
    (lambda: pe.get_login_white_label_params(), ('GET', '/api/noauth/whiteLabel/loginWhiteLabelParams', {}, {}, False)),
    (lambda: pe.get_white_label_params(), ('GET', '/api/whiteLabel/whiteLabelParams', {}, {}, False)),
    (lambda: pe.get_all_user_infos(10, 0, include_customers=True),
     ('GET', '/api/userInfos/all', {'pageSize': 10, 'page': 0, 'includeCustomers': True}, {}, False)),
]
failed = 0
for call, expected in cases:
    try:
        call()
        ok = sent[-1] == expected
        print('%-4s %s %s %s %s body=%s' % ('OK' if ok else 'FAIL', *sent[-1]) + ('' if ok else '\n     expected %s' % (expected,)))
    except Exception as e:
        ok = False
        print('FAIL %s -> %s: %s' % (expected[1], type(e).__name__, e))
    failed += not ok
print('%d/%d OK' % (len(cases) - failed, len(cases)))
sys.exit(1 if failed else 0)
