"""Checks the runtime fixes in api_client.py and configuration.py of the draft without a server.

Usage: python3 codegen/tests/test_runtime_fixes.py [package_parent_dir]   (default: draft)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'draft'))

from tb_rest_client.api_client import ApiClient
from tb_rest_client.configuration import Configuration
from tb_rest_client.api.asset_controller_api import AssetControllerApi
from tb_rest_client.api.custom_menu_controller_api import CustomMenuControllerApi
from tb_rest_client.api.device_controller_api import DeviceControllerApi
from tb_rest_client.models.device_id import DeviceId

sent = []


class FakeResponse:
    status, reason, data = 200, 'OK', '{}'

    def getheaders(self):
        return {}


def fake_request(method, url, query_params=None, headers=None, post_params=None, body=None,
                 _preload_content=True, _request_timeout=None):
    sent.append({'method': method, 'url': url, 'query': query_params, 'headers': headers})
    return FakeResponse()


def check(name, ok, detail):
    print('%-4s %s: %s' % ('OK' if ok else 'FAIL', name, detail))
    if not ok:
        check.failed = True


check.failed = False

a, b = Configuration(), Configuration()
a.api_key['X-Authorization'] = 'tenant-token'
check('configs do not share api_key', b.api_key == {}, 'b.api_key=%s' % b.api_key)

conf = Configuration()
conf.host = 'http://tb:8080'
conf.api_key['X-Authorization'] = 'jwt'
conf.api_key_prefix['X-Authorization'] = 'Bearer'
client = ApiClient(conf)
check('thread pool created lazily', client._pool is None, '_pool=%s' % client._pool)
client.request = fake_request

AssetControllerApi(client).get_tenant_assets(page_size=10, page=0, type=None, text_search=None,
                                             sort_property='name', sort_order=None)
r = sent[-1]
check('None query params dropped', r['query'] == [('pageSize', 10), ('page', 0), ('sortProperty', 'name')], r['query'])
check('auth header sent', r['headers'].get('X-Authorization') == 'Bearer jwt'
      and 'Authorization' not in r['headers'], r['headers'])

device_id = DeviceId(id='784f394c-42b6-435a-983c-b7beff2784f9', entity_type='DEVICE')
DeviceControllerApi(client).get_device_by_id(device_id)
check('entity id object in path', sent[-1]['url'].endswith('/api/device/784f394c-42b6-435a-983c-b7beff2784f9'),
      sent[-1]['url'])

CustomMenuControllerApi(client).get_custom_menu(if_none_match=None)
check('None header params dropped', 'If-None-Match' not in sent[-1]['headers'], sent[-1]['headers'])


class Body:
    def __init__(self, data):
        self.data = data


# response bodies seen on a 4.4 server for operations typed as string in the spec
for name, body, expected in (
        ('plain text body decoded', b'https://raw.githubusercontent.com/x', 'https://raw.githubusercontent.com/x'),
        ('JSON string body unquoted', b'"/login/oauth2/code/"', '/login/oauth2/code/'),
        ('empty body is empty string', b'', ''),
        ('non-ASCII text decoded', 'Умови'.encode(), 'Умови'),
        ('binary body kept as bytes', b'\x89PNG\r\n\x1a\n\xff', b'\x89PNG\r\n\x1a\n\xff')):
    result = client.deserialize(Body(body), 'str')
    check(name, result == expected, repr(result))
result = client.deserialize(Body(b'{"client":{"a":1}}'), 'object')
check('JSON object body as dict', result == {'client': {'a': 1}}, repr(result))
result = client.deserialize(Body(b''), 'object')
check('empty body of an object response is None', result is None, repr(result))

# metadata of the Root Rule Chain on a 4.4 server: ruleChainConnections is null, the spec says required
body = (b'{"ruleChainId":{"entityType":"RULE_CHAIN","id":"784f394c-42b6-435a-983c-b7beff2784f9"},'
        b'"version":1,"firstNodeIndex":0,"nodes":[],"connections":[],"ruleChainConnections":null}')
try:
    result = client.deserialize(Body(body), 'RuleChainMetaData')
    check('null in a nullable required field', result.rule_chain_connections is None
          and result.rule_chain_id.id == '784f394c-42b6-435a-983c-b7beff2784f9', repr(result.rule_chain_id))
except ValueError as e:
    check('null in a nullable required field', False, e)

# fields the server sends that the model does not have are kept and sent back
info = {'type': 'org.thingsboard.server.common.data.notification.info.EntityActionNotificationInfo',
        'stateEntityId': {'entityType': 'DEVICE', 'id': '784f394c-42b6-435a-983c-b7beff2784f9'},
        'entityName': 'Thermostat', 'actionType': 'ADDED', 'affectedUserId': None}
notification = client.deserialize(Body(json.dumps({'subject': 's', 'info': info}).encode()), 'Notification')
kept = getattr(notification.info, 'additional_properties', None)
check('unknown fields kept on the object', kept == {'entityName': 'Thermostat', 'actionType': 'ADDED', 'affectedUserId': None},
      kept)
check('known fields still typed', type(notification.info.state_entity_id).__name__ == 'DeviceId',
      type(notification.info.state_entity_id).__name__)
back = client.sanitize_for_serialization(notification)
check('unknown fields sent back, nulls left out', back['info'] == {k: v for k, v in info.items() if v is not None}, back['info'])
device = client.deserialize(Body(b'{"name": "d", "type": "default", "externalId": {"entityType": "DEVICE", '
                                 b'"id": "784f394c-42b6-435a-983c-b7beff2784f9"}}'), 'Device')
check('externalId kept through get -> save', client.sanitize_for_serialization(device).get('externalId') ==
      {'entityType': 'DEVICE', 'id': '784f394c-42b6-435a-983c-b7beff2784f9'}, getattr(device, 'additional_properties', None))
plain = client.deserialize(Body(b'{"name": "d", "type": "default"}'), 'Device')
check('no attribute when nothing is unknown', not hasattr(plain, 'additional_properties'), plain.__dict__.keys())
step = client.deserialize(Body(b'{"type": "COMPOSE", "title": "t", "futureField": 1}'), 'AgentAppStep')
check('unknown fields kept on a resolved subclass', type(step).__name__ == 'ComposeStep'
      and getattr(step, 'additional_properties', None) == {'futureField': 1}, getattr(step, 'additional_properties', None))

# Accept: a file endpoint lists its media type and application/json (errors); sending only
# application/json made the server answer 406
check('Accept keeps the file media type', client.select_header_accept(['image/*', 'application/json'])
      == 'image/*, application/json', client.select_header_accept(['image/*', 'application/json']))
check('Accept of a JSON endpoint unchanged', client.select_header_accept(['application/json']) == 'application/json',
      client.select_header_accept(['application/json']))

# rest.py: a JSON request without a body sends none (the generator sent '{}')
from tb_rest_client.rest import RESTClientObject


class FakePool:
    def request(self, method, url, **kwargs):
        self.body = kwargs.get('body')
        return type('R', (), {'status': 200, 'reason': 'OK', 'data': b'{}', 'headers': {}})()


rest = RESTClientObject(Configuration())
rest.pool_manager = FakePool()
rest.request('POST', 'http://tb:8080/api/x', headers={'Content-Type': 'application/json'})
check('no body sent when none given', rest.pool_manager.body is None, repr(rest.pool_manager.body))
rest.request('POST', 'http://tb:8080/api/x', headers={'Content-Type': 'application/json'}, body={'a': 1})
check('JSON body sent', rest.pool_manager.body == '{"a": 1}', repr(rest.pool_manager.body))

del client
sys.exit(1 if check.failed else 0)
