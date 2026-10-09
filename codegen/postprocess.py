"""Fixes known swagger-codegen bugs in a generated client.

Usage: python3 codegen/postprocess.py <package_dir>   (e.g. draft/tb_rest_client)

Every fix is idempotent, so the script can be re-run on an already edited draft.
"""
import os
import re
import sys


def norm(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def load_models(pkg_dir):
    """Returns {path: source} of model files and {normalized name: class name}."""
    models_dir = os.path.join(pkg_dir, 'models')
    sources, classes = {}, {}
    for f in sorted(os.listdir(models_dir)):
        if not f.endswith('.py') or f == '__init__.py':
            continue
        path = os.path.join(models_dir, f)
        sources[path] = open(path).read()
        m = re.search(r'^class (\w+)\(', sources[path], re.M)
        classes[norm(m.group(1))] = m.group(1)
    return sources, classes


def fix_discriminator_maps(pkg_dir):
    """discriminator_value_class_map holds '#/components/schemas/X' instead of the
    class name X, so deserializing any polymorphic model fails with AttributeError."""
    sources, classes = load_models(pkg_dir)
    pattern = re.compile(r"(\.lower\(\): )'#/components/schemas/([^']+)'")

    def class_name(m):
        # reserved words are renamed with a 'Model' prefix, e.g. None -> ModelNone
        cls = classes.get(norm(m.group(2))) or classes.get('model' + norm(m.group(2)))
        if cls is None:
            sys.exit('No model class for schema %s' % m.group(2))
        return "%s'%s'" % (m.group(1), cls)

    changed = {}
    for path, src in sources.items():
        new = pattern.sub(class_name, src)
        if new != src:
            changed[path] = new
    for path, src in changed.items():
        with open(path, 'w') as f:
            f.write(src)
    print('discriminator maps: fixed %d models' % len(changed))


def fix_entity_id_arg_order(pkg_dir):
    """The 4.4 spec lists entityType before id, so the generated constructor is
    EntityId(entity_type, id), while 4.3 had EntityId(id, entity_type). Code written for 4.3,
    DeviceId(uuid, 'DEVICE'), would silently swap the fields and call /api/device/DEVICE.
    All *Id classes pass *args to EntityId.__init__, so fixing it fixes them too."""
    path = os.path.join(pkg_dir, 'models', 'entity_id.py')
    src = open(path).read()
    generated = 'def __init__(self, entity_type=None, id=None):'
    fixed = 'def __init__(self, id=None, entity_type=None):'
    if generated in src:
        with open(path, 'w') as f:
            f.write(src.replace(generated, fixed))
        print('EntityId argument order: restored (id, entity_type)')
    elif fixed in src:
        print('EntityId argument order: already (id, entity_type)')
    else:
        sys.exit('EntityId argument order: unexpected constructor in %s, check the fix' % path)


# Operations the spec types as a JSON 'string' response (mostly DeferredResult in the controller),
# with what a 4.4 server actually returns. 'str' made them come back as a repr string of the JSON
# and an empty body as "b''". None: always an empty body; 'object': JSON parsed to dict/list (an
# empty body, e.g. one-way RPC, gives None); 'str': text or a JSON string.
_T = '/api/plugins/telemetry'
STRING_RESPONSE_TYPES = {
    # empty body, checked on a server
    ('POST', _T + '/{entityType}/{entityId}/timeseries/{scope}'): None,
    ('POST', _T + '/{entityType}/{entityId}/timeseries/{scope}/{ttl}'): None,
    ('POST', _T + '/{entityType}/{entityId}/attributes/{scope}'): None,
    ('POST', _T + '/{entityType}/{entityId}/{scope}'): None,
    ('POST', _T + '/{deviceId}/{scope}'): None,
    ('DELETE', _T + '/{deviceId}/{scope}'): None,
    ('DELETE', _T + '/{entityType}/{entityId}/{scope}'): None,
    ('DELETE', _T + '/{entityType}/{entityId}/timeseries/delete'): None,
    ('POST', '/api/v1/{deviceToken}/telemetry'): None,
    ('POST', '/api/v1/{deviceToken}/attributes'): None,
    ('POST', '/api/v1/{deviceToken}/rpc/{requestId}'): None,
    ('POST', '/api/v1/{deviceToken}/claim'): None,
    # JSON, checked on a server
    ('GET', '/api/rpc/persistent/device/{deviceId}'): 'object',
    ('GET', '/api/v1/{deviceToken}/attributes'): 'object',
    ('GET', '/api/edge/missingToRelatedRuleChains/{edgeId}'): 'object',
    ('POST', '/api/v1/provision'): 'object',
    # JSON when a device or rule chain answers (seen on a server: timeouts with an empty body)
    ('GET', '/api/v1/{deviceToken}/attributes/updates'): 'object',
    ('GET', '/api/v1/{deviceToken}/rpc'): 'object',
    ('POST', '/api/v1/{deviceToken}/rpc'): 'object',
    ('POST', '/api/rpc/twoway/{deviceId}'): 'object',
    ('POST', '/api/plugins/rpc/twoway/{deviceId}'): 'object',
    ('POST', '/api/rule-engine/'): 'object',
    ('POST', '/api/rule-engine/{entityType}/{entityId}'): 'object',
    ('POST', '/api/rule-engine/{entityType}/{entityId}/{timeout}'): 'object',
    ('POST', '/api/rule-engine/{entityType}/{entityId}/{queueName}/{timeout}'): 'object',
    # JSON or empty, from the spec descriptions (not seen with data on a server)
    ('POST', '/api/rpc/oneway/{deviceId}'): 'object',  # persistent RPC returns {"rpcId": ...}
    ('POST', '/api/plugins/rpc/oneway/{deviceId}'): 'object',
    ('GET', '/api/edge/integration/{edgeId}/missingAttributes'): 'object',
    ('GET', '/api/edge/integration/{integrationId}/allMissingAttributes'): 'object',
    ('POST', '/api/edge/sync/{edgeId}'): 'object',
    ('POST', '/api/customer/device/{deviceName}/claim'): 'object',
    ('DELETE', '/api/customer/device/{deviceName}/claim'): 'object',
    # text or a JSON string, checked on a server (activateEmail, mobileLogin: redirects)
    ('GET', '/api/uiSettings/helpBaseUrl'): 'str',
    ('GET', '/api/agent/upgrade/latest'): 'str',
    ('GET', '/api/agent/{agentId}/upgrade/target'): 'str',
    ('GET', '/api/noauth/selfRegistration/privacyPolicy'): 'str',
    ('GET', '/api/noauth/selfRegistration/termsOfUse'): 'str',
    ('GET', '/api/oauth2/loginProcessingUrl'): 'str',
    ('GET', '/api/admin/mail/oauth2/loginProcessingUrl'): 'str',
    ('GET', '/api/noauth/activateEmail'): 'str',
    ('GET', '/api/noauth/login'): 'str',
    # binary file; ApiClient returns bytes when the body is not text
    ('GET', '/api/v1/{deviceToken}/firmware'): 'str',
    ('GET', '/api/v1/{deviceToken}/software'): 'str',
}


def fix_string_response_types(pkg_dir):
    """Sets the response type of the operations in STRING_RESPONSE_TYPES."""
    api_dir = os.path.join(pkg_dir, 'api')
    found, changed = set(), 0
    for f in sorted(os.listdir(api_dir)):
        if not f.endswith('_api.py'):
            continue
        path = os.path.join(api_dir, f)
        src = open(path).read()
        # methods of the class: '    def name(' up to the next one
        parts = re.split(r'(?m)^(?=    def )', src)
        names = [re.match(r'    def (\w+)', p).group(1) if p.startswith('    def ') else None for p in parts]
        for i, part in enumerate(parts):
            call = re.search(r"call_api\(\s*'([^']+)', '([A-Z]+)'", part)
            if not call or (call.group(2), call.group(1)) not in STRING_RESPONSE_TYPES:
                continue
            key = (call.group(2), call.group(1))
            found.add(key)
            new_type = STRING_RESPONSE_TYPES[key]
            public = names.index(names[i][:-len('_with_http_info')])
            for j in (public, i):
                parts[j] = parts[j].replace(':return: str\n', ':return: %s\n' % new_type)
            parts[i] = re.sub(r"response_type=(?:'str'|'object'|None),",
                              'response_type=%s,' % (repr(new_type) if new_type else 'None'), parts[i])
        new = ''.join(parts)
        if new != src:
            changed += 1
            with open(path, 'w') as fh:
                fh.write(new)
    missing = set(STRING_RESPONSE_TYPES) - found
    if missing:
        sys.exit('string response types: operations not found: %s' % sorted(missing))
    print('string response types: %d operations, %d files changed' % (len(found), changed))


FIXES = [fix_discriminator_maps, fix_entity_id_arg_order, fix_string_response_types]

if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for fix in FIXES:
        fix(sys.argv[1])
