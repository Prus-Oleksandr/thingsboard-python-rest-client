"""Practical end-to-end check of RestClient against a live ThingsBoard 4.4 server: the behaviour
changed during the 4.4 migration, through the public wrappers, the way a user script would call them.

Usage:
  python3 codegen/smoke_scenario.py [--package draft] [--write]

Without --write it only reads (GET requests); nothing on the server changes.
With --write it also creates temporary entities named 'smoke-<random>-...' (a device, a customer,
a relation, an alarm, a persistent RPC, an image), checks them and deletes them at the end, also when
a step fails. Run --write only on a test server, never on production.

Server and credentials come from the environment, never from files:
  TB_URL                                     default http://localhost:8080
  TB_TENANT_USERNAME, TB_TENANT_PASSWORD     a tenant administrator
  TB_TENANT_TOKEN                            or a JWT of one (e.g. copied from Swagger UI)

Each step prints OK / FAIL / SKIP and what it saw; the exit code is 1 if any step failed.
"""
import argparse
import json
import os
import random
import sys
import tempfile
import time
import traceback
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--package', default=os.path.join(ROOT, 'draft'), help='dir that contains tb_rest_client')
parser.add_argument('--write', action='store_true', help='also create, check and delete temporary entities')
args = parser.parse_args()
sys.path.insert(0, args.package)

from tb_rest_client.rest_client import RestClient  # noqa: E402
from tb_rest_client.rest import ApiException  # noqa: E402
from tb_rest_client.models import (Alarm, AgentAppStep, Customer, Device, DeviceId, EntityRelation,  # noqa: E402
                                   RpcId, RuleChainMetaData, ThingsboardErrorCode)

SYSTEM_TENANT = '13814000-1dd2-11b2-8080-808080808080'
PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                    '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082')
results = []


class Skip(Exception):
    pass


def step(name):
    """Decorator: runs the step at once, prints OK / FAIL / SKIP and keeps going."""
    def run(fn):
        try:
            detail = fn()
            results.append('OK')
            print('OK    %s%s' % (name, ': %s' % detail if detail else ''))
        except Skip as e:
            results.append('SKIP')
            print('SKIP  %s: %s' % (name, e))
        except Exception as e:  # report every step, do not stop at the first failure
            results.append('FAIL')
            where = traceback.extract_tb(e.__traceback__)[-1]
            print('FAIL  %s: %s: %s (%s:%d)' % (name, type(e).__name__, str(e)[:300],
                                              os.path.basename(where.filename), where.lineno))
        return fn
    return run


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


def wait_for(read, ready, seconds=10):
    """Polls read() until ready(result); telemetry sent through the device API is stored asynchronously."""
    deadline = time.time() + seconds
    while True:
        result = read()
        if ready(result) or time.time() > deadline:
            return result
        time.sleep(0.5)


url = os.environ.get('TB_URL', 'http://localhost:8080').rstrip('/')
client = RestClient(url)
if os.environ.get('TB_TENANT_TOKEN'):
    client.token_login(os.environ['TB_TENANT_TOKEN'])
elif os.environ.get('TB_TENANT_USERNAME') and os.environ.get('TB_TENANT_PASSWORD'):
    client.login(os.environ['TB_TENANT_USERNAME'], os.environ['TB_TENANT_PASSWORD'])
else:
    sys.exit('Set TB_TENANT_TOKEN, or TB_TENANT_USERNAME and TB_TENANT_PASSWORD')
print('Server %s, package %s, mode %s\n' % (url, args.package, 'read + write' if args.write else 'read only'))
state = {}
cleanup = []  # (description, function) run in reverse order at the end


# ---------------------------------------------------------------- read only
@step('login and current user')
def _():
    user = client.get_user()
    state['user'] = user
    expect(user.authority == 'TENANT_ADMIN', 'the scenario needs a tenant administrator, got %s' % user.authority)
    return '%s, tenant %s' % (user.authority, user.tenant_id.id)


@step('entity id argument order kept from 4.3: DeviceId(uuid, "DEVICE")')
def _():
    i = DeviceId('784f394c-42b6-435a-983c-b7beff2784f9', 'DEVICE')
    expect(i.id == '784f394c-42b6-435a-983c-b7beff2784f9' and i.entity_type == 'DEVICE', i)


@step('tenant devices, paged')
def _():
    page = client.get_tenant_devices(10, 0)
    expect(isinstance(page.data, list), type(page.data))
    if page.data:
        state['device'] = page.data[0]
    return '%d devices, first: %s' % (page.total_elements, page.data[0].name if page.data else '-')


@step('error answer: 404 with errorCode comparable to ThingsboardErrorCode')
def _():
    try:
        client.get_device_by_id(DeviceId(str(uuid.uuid4()), 'DEVICE'))
    except ApiException as e:
        body = json.loads(e.body)
        expect(e.status == 404 and body['errorCode'] == ThingsboardErrorCode._32, (e.status, body))
        return 'status %d, errorCode %d (ITEM_NOT_FOUND)' % (e.status, body['errorCode'])
    raise AssertionError('no error for a device that does not exist')


@step('JSON typed as string in the spec comes back as a dict: device API attributes')
def _():
    if 'device' not in state:
        raise Skip('no device on the server (run with --write to create one)')
    token = client.get_device_credentials_by_device_id(state['device'].id).credentials_id
    attrs = client.get_device_attributes(token, all_client_keys=True, all_shared_keys=True)
    expect(isinstance(attrs, dict), 'got %s: %r' % (type(attrs).__name__, attrs))
    return 'dict with keys %s' % sorted(attrs)


@step('persisted RPC page comes back as a dict')
def _():
    if 'device' not in state:
        raise Skip('no device on the server')
    page = client.get_persisted_rpc_by_device(state['device'].id, 10, 0)
    expect(isinstance(page, dict) and 'data' in page, 'got %s: %r' % (type(page).__name__, page))
    return 'totalElements=%s' % page.get('totalElements')


@step('plain text answer decoded: help base URL')
def _():
    text = client.get_help_base_url()
    expect(isinstance(text, str) and not text.startswith("b'"), repr(text))
    return text


@step('latest telemetry and attributes of a device')
def _():
    if 'device' not in state:
        raise Skip('no device on the server')
    latest = client.get_latest_timeseries(state['device'].id)
    attrs = client.get_attributes(state['device'].id)
    expect(isinstance(latest, dict) and isinstance(attrs, list), (type(latest), type(attrs)))
    return 'timeseries keys %s, %d attributes' % (sorted(latest)[:5], len(attrs))


@step('root rule chain metadata (null ruleChainConnections accepted)')
def _():
    chains = client.get_rule_chains(50, 0)
    root = next((c for c in chains.data if c.root), None)
    if root is None:
        raise Skip('no root rule chain')
    meta = client.get_rule_chain_meta_data(root.id)
    expect(isinstance(meta, RuleChainMetaData) and meta.nodes, meta)
    return '%s: %d nodes, %d connections' % (root.name, len(meta.nodes), len(meta.connections or []))


@step('agent templates: steps resolve to their subclasses')
def _():
    try:
        templates = client.get_agent_app_templates()
    except ApiException as e:
        raise Skip('agent templates not available: %s' % e.status)
    steps = [s for t in templates for f in ('start_steps', 'upgrade_steps', 'delete_steps', 'rollback_steps',
                                            'restart_steps') for s in (getattr(t, f) or [])]
    if not steps:
        raise Skip('no agent templates on the server')
    base_only = [s.type for s in steps if type(s) is AgentAppStep]
    expect(not base_only, 'left as the base class: %s' % sorted(set(base_only)))
    return '%d templates, step classes %s' % (len(templates), sorted({type(s).__name__ for s in steps}))


@step('notification info keeps the fields the spec does not describe')
def _():
    page = client.get_notifications(10, 0)
    if not page.data:
        raise Skip('no notifications for this user')
    info = page.data[0].info
    extra = getattr(info, 'additional_properties', {})
    expect(extra, 'nothing kept for %s' % info.type)
    return '%s: %s' % (info.type.split('.')[-1], ', '.join('%s=%s' % kv for kv in list(extra.items())[:3]))


@step('owners keep the tenant fields (title, ...)')
def _():
    page = client.get_owners(10, 0)
    if not page.data:
        raise Skip('no owners')
    first = page.data[0]
    expect(type(first.id).__name__ in ('TenantId', 'CustomerId'), 'owner id is %s' % type(first.id).__name__)
    return '%s %s, additional_properties keys %s' % (type(first.id).__name__, first.name,
                                                    sorted(getattr(first, 'additional_properties', {})))


@step('image download returns the file as bytes')
def _():
    page = client.get_images(10, 0, include_system_images=True)
    if not page.data:
        raise Skip('no images')
    image = page.data[0]
    kind = 'system' if image.tenant_id.id == SYSTEM_TENANT else 'tenant'
    data = client.download_image(kind, image.resource_key)
    expect(isinstance(data, bytes) and data, type(data))
    return '%s/%s: %d bytes' % (kind, image.resource_key, len(data))


# ---------------------------------------------------------------- write (--write)
if args.write:
    prefix = 'smoke-%06d' % random.randrange(10 ** 6)
    print('\nTemporary entities are named %s-*\n' % prefix)

    @step('create a device')
    def _():
        device = client.save_device(Device(name=prefix + '-device', type='default'))
        cleanup.append(('device ' + device.name, lambda: client.delete_device(device.id)))
        state['new_device'] = device
        state['token'] = client.get_device_credentials_by_device_id(device.id).credentials_id
        return device.id.id

    @step('device API: post telemetry and attributes (empty answers come back as None)')
    def _():
        if 'token' not in state:
            raise Skip('no device')
        expect(client.post_telemetry(state['token'], {'smokeTemperature': 21.5}) is None, 'telemetry answer not None')
        expect(client.post_device_attributes(state['token'], {'smokeClient': 'x'}) is None, 'attributes answer not None')
        attrs = wait_for(lambda: client.get_device_attributes(state['token'], client_keys='smokeClient'),
                         lambda a: a.get('client', {}).get('smokeClient') == 'x')
        expect(attrs.get('client', {}).get('smokeClient') == 'x', attrs)
        return 'client attribute read back: %s' % attrs['client']

    @step('telemetry: save, then read history with the new argument order (entity, start, end, keys)')
    def _():
        if 'new_device' not in state:
            raise Skip('no device')
        device = state['new_device']
        expect(client.save_entity_telemetry(device.id, 'ANY', {'smokeHumidity': 40}) is None, 'answer not None')
        now = int(time.time() * 1000)
        history = wait_for(lambda: client.get_timeseries(device.id, now - 3600000, now + 60000,
                                                         keys='smokeTemperature,smokeHumidity'),
                           lambda h: 'smokeTemperature' in h and 'smokeHumidity' in h)
        expect('smokeTemperature' in history and 'smokeHumidity' in history, history)
        return {k: v[0].value for k, v in history.items()}

    @step('server attributes: save, read by scope, delete by key')
    def _():
        if 'new_device' not in state:
            raise Skip('no device')
        device = state['new_device']
        client.save_entity_attributes_v2(device.id, 'SERVER_SCOPE', {'smokeServer': 7})
        saved = client.get_attributes_by_scope(device.id, 'SERVER_SCOPE', keys='smokeServer')
        expect([a.value for a in saved] == [7], saved)
        client.delete_entity_attributes(device.id, 'SERVER_SCOPE', keys='smokeServer')
        expect(client.get_attributes_by_scope(device.id, 'SERVER_SCOPE', keys='smokeServer') == [], 'not deleted')

    @step('customer: create, assign the device (owner API), unassign')
    def _():
        if 'new_device' not in state:
            raise Skip('no device')
        customer = client.save_customer(Customer(title=prefix + '-customer'))
        cleanup.append(('customer ' + customer.title, lambda: client.delete_customer(customer.id)))
        state['customer'] = customer
        device = client.assign_device_to_customer(customer.id, state['new_device'].id)
        expect(device.owner_id.id == customer.id.id, 'owner after assign: %s' % device.owner_id)
        device = client.unassign_device_from_customer(state['new_device'].id)
        expect(device.owner_id.entity_type == 'TENANT', 'owner after unassign: %s' % device.owner_id)
        return 'owner: customer -> tenant'

    @step('relation: save, find from the customer, delete')
    def _():
        if 'customer' not in state:
            raise Skip('no customer')
        customer, device = state['customer'], state['new_device']
        client.save_relation(EntityRelation(_from=customer.id, to=device.id, type='Contains', type_group='COMMON'))
        found = client.find_by_from(customer.id, 'Contains')
        expect([r.to.id for r in found] == [device.id.id], found)
        client.delete_relation(customer.id, 'Contains', device.id)
        expect(client.find_by_from(customer.id, 'Contains') == [], 'not deleted')

    @step('alarm: create, acknowledge, clear, delete')
    def _():
        if 'new_device' not in state:
            raise Skip('no device')
        alarm = client.save_alarm(Alarm(type=prefix + '-alarm', name=prefix + '-alarm', originator=state['new_device'].id,
                                        severity='WARNING', acknowledged=False, cleared=False, status='ACTIVE_UNACK'))
        cleanup.append(('alarm ' + alarm.type, lambda: client.delete_alarm(alarm.id)))
        acked = client.ack_alarm(alarm.id)
        client.clear_alarm(alarm.id)
        expect(acked.acknowledged, acked)
        expect(client.delete_alarm(alarm.id) is True, 'delete did not return True')
        cleanup.pop()
        return 'ack -> clear -> deleted'

    @step('persistent one-way RPC returns its id as a dict, listed, deleted')
    def _():
        if 'new_device' not in state:
            raise Skip('no device')
        device = state['new_device']
        answer = client.handle_one_way_device_rpc_request_v1(
            device.id, {'method': 'smoke', 'params': {}, 'persistent': True, 'timeout': 60000})
        expect(isinstance(answer, dict) and 'rpcId' in answer, 'got %s: %r' % (type(answer).__name__, answer))
        page = client.get_persisted_rpc_by_device(device.id, 10, 0)
        expect(page['totalElements'] >= 1, page)
        client.delete_rpc(RpcId(answer['rpcId'], 'RPC'))
        return 'rpcId %s' % answer['rpcId']

    @step('image: upload with the new argument order (file, title), download the same bytes, delete')
    def _():
        with tempfile.NamedTemporaryFile(prefix=prefix + '-', suffix='.png', delete=False) as f:
            f.write(PNG)
        try:
            info = client.upload_image(f.name, title=prefix + '-image')
            cleanup.append(('image ' + info.resource_key, lambda: client.delete_image('tenant', info.resource_key, force=True)))
            data = client.download_image('tenant', info.resource_key)
            expect(data == PNG, 'downloaded %d bytes, uploaded %d' % (len(data), len(PNG)))
            return '%s: %d bytes round trip' % (info.resource_key, len(data))
        finally:
            os.remove(f.name)

    print('\nCleanup:')
    for description, delete in reversed(cleanup):
        try:
            delete()
            print('  deleted %s' % description)
        except Exception as e:
            print('  NOT DELETED %s: %s (delete it by hand)' % (description, e))

print('\n%d OK, %d FAIL, %d SKIP' % (results.count('OK'), results.count('FAIL'), results.count('SKIP')))
sys.exit(1 if 'FAIL' in results else 0)
