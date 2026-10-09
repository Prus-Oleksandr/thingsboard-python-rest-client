"""Checks the models fixed by hand where the generator failed (Q8), with the HTTP layer faked:
polymorphic agent configs, steps and step states, the EntityExportData subclasses, the required
output of calculated field configurations and the numeric error codes.

Usage: python3 codegen/tests/test_models.py [package_parent_dir]   (default: draft)
"""
import json
import os
import sys
import time

import jwt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'draft'))

from tb_rest_client.api_client import ApiClient
from tb_rest_client.rest_client import RestClient
from tb_rest_client import models

U = '784f394c-42b6-435a-983c-b7beff2784f9'
client = ApiClient()
results = []


class Body:
    def __init__(self, data):
        self.data = json.dumps(data).encode() if not isinstance(data, bytes) else data


def check(name, ok, detail=''):
    results.append(ok)
    print('%-4s %s %s' % ('OK' if ok else 'FAIL', name, detail))


def deserialize(data, klass):
    try:
        return client.deserialize(Body(data), klass)
    except Exception as e:  # report every case
        return e


def strip_none(o):
    if isinstance(o, dict):
        return {k: strip_none(v) for k, v in o.items() if v is not None}
    if isinstance(o, list):
        return [strip_none(x) for x in o]
    return o


def round_trip(data, obj):
    return strip_none(data) == client.sanitize_for_serialization(obj)


# agent steps: the server sends the AgentAppStepType value in 'type', not the class name
template = {
    'appType': 'EDGE', 'currentVersion': '1',
    'startSteps': [
        {'id': U, 'title': 'choice', 'type': 'COMPOSE_TEMPLATE', 'composeTemplates': {'a': 'b'}},
        {'id': U, 'title': 'compose', 'type': 'COMPOSE',
         'state': {'type': 'COMPOSE', 'pullImages': {'value': True}}},
        {'id': U, 'title': 'job', 'type': 'RUN_JOB', 'state': {'type': 'RUN_JOB', 'image': {'value': 'img'}}}],
    'upgradeSteps': [{'id': U, 'title': 'backup', 'type': 'BACKUP_VOLUME',
                      'state': {'type': 'BACKUP_VOLUME', 'backupVolumes': {'value': ['v']}}}],
    'deleteSteps': [{'id': U, 'title': 'down', 'type': 'COMPOSE_DOWN',
                     'state': {'type': 'COMPOSE_DOWN', 'removeVolumes': {'value': False}}}],
    'rollbackSteps': [{'id': U, 'title': 'rollback', 'type': 'ROLLBACK', 'state': {'type': 'ROLLBACK'}}],
    'restartSteps': [{'id': U, 'title': 'restart', 'type': 'COMPOSE_RESTART'}],
}
t = deserialize(template, 'AgentAppTemplate')
steps = [] if isinstance(t, Exception) else [s for f in ('start_steps', 'upgrade_steps', 'delete_steps',
                                                        'rollback_steps', 'restart_steps') for s in getattr(t, f)]
got = [(type(s).__name__, type(getattr(s, 'state', None)).__name__) for s in steps]
check('agent steps resolve to their subclasses', got == [
    ('ComposeTypeChoiceStep', 'NoneType'), ('ComposeStep', 'ComposeStepState'), ('RunJobStep', 'RunJobStepState'),
    ('BackupVolumesStep', 'BackupVolumesStepState'), ('ComposeDownStep', 'ComposeDownStepState'),
    ('RollBackStep', 'RollBackStepState'), ('ComposeRestartStep', 'NoneType')], got if not isinstance(t, Exception) else t)
check('agent template round trip', not isinstance(t, Exception) and round_trip(template, t))

profile = {'appType': 'EDGE', 'name': 'p', 'templateVersion': '1',
           'config': {'type': 'DOCKER_COMPOSE', 'composeType': 'default', 'compose': {'services': {}}}}
p = deserialize(profile, 'AgentAppProfile')
check('agent app config resolves to DockerComposeConfig', type(getattr(p, 'config', None)).__name__ == 'DockerComposeConfig',
      type(getattr(p, 'config', p)).__name__)

event = {'stepStates': {'s1': {'type': 'COMPOSE', 'pullImages': {'value': True}}, 's2': {'type': 'ROLLBACK'}}}
e = deserialize(event, 'AgentAppEvent')
states = {k: type(v).__name__ for k, v in (getattr(e, 'step_states', None) or {}).items()}
check('agent step states resolve to their subclasses', states == {'s1': 'ComposeStepState', 's2': 'RollBackStepState'},
      states or e)

# EntityExportData subclasses: the generator flattened these four instead of inheriting
for name, entity_type, own in (('DeviceExportData', 'DEVICE', {'credentials': {
                                    'id': {'id': U}, 'deviceId': {'entityType': 'DEVICE', 'id': U},
                                    'credentialsType': 'ACCESS_TOKEN', 'credentialsId': 'token'}}),
                               ('RuleChainExportData', 'RULE_CHAIN', {'metaData': {
                                   'ruleChainId': {'entityType': 'RULE_CHAIN', 'id': U}, 'firstNodeIndex': 0,
                                   'nodes': [], 'connections': [], 'ruleChainConnections': []}}),
                               ('WidgetsBundleExportData', 'WIDGETS_BUNDLE', {'fqns': ['a.b'], 'widgets': [{'k': 1}]}),
                               ('EntityGroupExportData', 'ENTITY_GROUP', {'groupEntities': True, 'memberIds': [U]})):
    data = dict(own, entityType=entity_type, relations=[])
    x = deserialize(data, 'EntityExportData')
    check('%s is an EntityExportData' % name, type(x).__name__ == name and isinstance(x, models.EntityExportData)
          and round_trip(data, x), type(x).__name__)

# output is required for these calculated field types although it is declared in the parent
output = {'type': 'TIME_SERIES', 'name': 'out'}
for name, cf_type, own in (('GeofencingCalculatedFieldConfiguration', 'GEOFENCING', {
                                'entityCoordinates': {'latitudeKeyName': 'lat', 'longitudeKeyName': 'lon'}, 'zoneGroups': {}}),
                           ('EntityAggregationCalculatedFieldConfiguration', 'ENTITY_AGGREGATION', {
                               'arguments': {}, 'interval': {'type': 'HOUR', 'tz': 'UTC'}, 'metrics': {}}),
                           ('RelatedEntitiesAggregationCalculatedFieldConfiguration', 'RELATED_ENTITIES_AGGREGATION', {
                               'arguments': {}, 'metrics': {}, 'relation': {'direction': 'FROM', 'relationType': 'Contains'}})):
    data = dict(own, type=cf_type)
    with_output = deserialize(dict(data, output=output), 'CalculatedFieldConfiguration')
    without = deserialize(data, 'CalculatedFieldConfiguration')
    check('%s requires output' % name, type(with_output).__name__ == name and isinstance(without, ValueError),
          '%s / %s' % (type(with_output).__name__, without))
simple = deserialize({'type': 'SIMPLE', 'arguments': {}}, 'CalculatedFieldConfiguration')
check('SimpleCalculatedFieldConfiguration still accepts no output',
      type(simple).__name__ == 'SimpleCalculatedFieldConfiguration', type(simple).__name__)

# the server sends errorCode as a number
error = deserialize(b'{"status":404,"message":"Requested item wasn\'t found!","errorCode":32}', 'ThingsboardErrorResponse')
check('error code compares with ThingsboardErrorCode', error.error_code == models.ThingsboardErrorCode._32, repr(error.error_code))

# getManagedRelatedEntityIds: a list of entity ids of different types
rest = RestClient('http://tb:8080')
rest.token_login(jwt.encode({'sub': 't', 'exp': int(time.time()) + 3600}, 's' * 32, algorithm='HS256'))


class FakeResponse:
    status, reason = 200, 'OK'
    data = json.dumps([{'entityType': 'EDGE', 'id': U}, {'entityType': 'DEVICE', 'id': U}]).encode()

    def getheaders(self):
        return {}


rest.api_client.request = lambda *args, **kwargs: FakeResponse()
ids = rest.get_managed_related_entity_ids('EDGE')
check('managed related entity ids are EntityId subclasses', [type(i).__name__ for i in ids] == ['EdgeId', 'DeviceId'],
      [type(i).__name__ for i in ids])

print('%d/%d OK' % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
