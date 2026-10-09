# ThingsBoard Python REST client: migration to 4.4 (branch `codegen/4.4`)

This branch is a working draft. It rebuilds the client for ThingsBoard 4.4 from the OpenAPI spec
with swagger-codegen and verifies every generated or migrated piece against the spec and a live
server. Read this file fully before changing anything. The user communicates in Ukrainian; answer
in Ukrainian.

## Goal

ThingsBoard 4.4 is a single product: CE and PE were merged (the PE model won: entity groups and
owners). The 4.3 client was split into CE and PE everywhere (api_ce/api_pe, models_ce/models_pe,
RestClientCE/RestClientPE). The goal is one client, `RestClient`, generated from the 4.4 spec and
matching it as closely as possible, with the 4.3 hand-written wrappers migrated onto it.

## Layout

| Path | What it is |
|---|---|
| `tb_rest_client/` | Released 4.3 client. Reference only: do not modify until the final swap. |
| `draft/tb_rest_client/` | New 4.4 client: generated `api/` (93 controllers) and `models/`, hand-edited `api_client.py`, `configuration.py`, and `rest_client.py` (class `RestClient`, 721 wrappers). |
| `draft/` (other files) | Generator boilerplate (setup.py, tox.ini, .travis.yml, git_push.sh, README.md, ...), not used. |
| `codegen/spec/thingsboard-swagger.json` | ThingsBoard 4.4.0 OpenAPI 3.1 spec, pretty-printed. |
| `codegen/generate.sh`, `config.json` | Reproducible generation (swagger-codegen v3 3.0.82, Python). |
| `codegen/postprocess.py` | Idempotent fixes of generator output, run by generate.sh. |
| `codegen/check_spec.py` | Generated client vs spec: lost params, types, fields, enums, discriminators. |
| `codegen/check_wrappers.py` | Wrapper calls vs generated API: renamed, moved, removed endpoints, params. |
| `codegen/apply_wrapper_renames.py` | Applied the 4.3 -> 4.4 renames to the copied wrappers (done once). |
| `codegen/client_parser.py` | Shared ast parser of generated api/model code. |
| `codegen/tests/` | Tests with the HTTP layer faked (no server needed). |
| `codegen/probe_endpoints.py`, `codegen/probes/` | Raw requests to a live server to find hidden or removed endpoints. |
| `codegen/probe_deserialization.py` | Real GET answers of a live server through the draft models. |
| `codegen/README.md` | Short description of the codegen tools. |

## How the draft was produced

1. `codegen/generate.sh` downloads the pinned swagger-codegen CLI jar into `codegen/bin/`
   (gitignored), copies the spec with `"openapi": "3.0.3"` (the generator mishandles 3.1 input:
   primitive types became `object`, allOf inheritance and all ID fields were lost; the spec uses
   no 3.1-only features), generates, then runs `postprocess.py`.
2. The unmodified output was committed as a baseline (commit `1698d2d6`), so `git diff` shows every
   manual change. `generate.sh` refuses to write into an existing directory: never regenerate over
   `draft/`. To compare, generate into another dir: `codegen/generate.sh /tmp/gen`.
3. The 4.3 wrappers were copied unchanged (`3981023d`), migrated with `apply_wrapper_renames.py`,
   fixed by hand, then merged into one `RestClient` class (`9463a5f6`).

## Decisions already made (do not reopen without the user)

- One class `RestClient` in `draft/tb_rest_client/rest_client.py`; import is
  `from tb_rest_client.rest_client import RestClient`. No `RestClientCE`/`RestClientPE` aliases.
- Wrappers must match the spec as closely as possible: params, their order (required first, spec
  order), required-ness, response type annotation. Wrapper names stay as in 4.3 unless they clash.
- A wrapper whose endpoint is neither in the spec nor served by the server (404 "No static
  resource" from `probe_endpoints.py`) is deleted. No stubs, no "removed in 4.4" errors.
- Hidden endpoints (served by the server but not in the spec) get no wrapper either: the 5 4.3
  wrappers on them were deleted (Q1). Upstream precedent: wrappers of operations gone from the spec
  were always deleted, legacy kept only while the spec still listed it, no raw `call_api` in wrappers.
- Deviate from the spec only where the server behaves differently (upstream did: `str` body ->
  `Dict` in `6d62481d`, hand-added `type` query param in `0569d384`).
- `EntityId(id, entity_type)` argument order from 4.3 is restored by `postprocess.py` (4.4 spec
  order would silently swap the fields of code like `DeviceId(uuid, 'DEVICE')`).
- 4.3 CE "assign/unassign X to/from customer" wrappers are kept on top of the owner API
  (changeOwnerToCustomer / changeOwnerToTenant) and still return the updated entity.
- Paged wrappers mirror the same-path paged operation (`get_widgets_bundles`,
  `get_scheduler_events`), not the `/all` variants.
- `handle_rule_engine_request*` (CE and PE had clashing names) are named after the 4.4 operations:
  `handle_rule_engine_request_for_entity[_with_timeout|_with_queue_and_timeout]`, `_for_user`.
- Commit author stays as is.
- Wrapper signatures follow the spec even when positional calls break (Q6), as upstream did:
  PR #5 (2020, page_size/page moved before type), `867f168a` (body made optional moved to the end),
  `65e38a77` (save_customer), `24fcd2a1` (get_timeseries got interval_type in the middle). No
  keyword-only tricks or shims; every reorder goes to "Positional order changes" below.

## Done

Generator and runtime (`postprocess.py`, `api_client.py`, `configuration.py`):
- 3.0.3 spec label; discriminator maps held `'#/components/schemas/X'` instead of class names (51
  models, polymorphic responses crashed); EntityId argument order.
- Ported from the 4.3 runtime: `Configuration()` instances no longer share the `api_key` dict
  (two clients overwrote each other's tokens); None query/header/form params are not sent; entity
  id objects can be path params; lazy ThreadPool.
- Comma-separated strings for array (`multi`) params are sent as one value (wrappers pass
  `','.join(ids)`; the generator iterated the string char by char).
- 43 operations typed as JSON `string` in the spec are retyped from what a live server returned
  (`STRING_RESPONSE_TYPES` in `postprocess.py`: 12 -> `None`, 20 -> `object`, 2 firmware -> `bytes`,
  9 stay `str`); `check_spec.py` checks the generated types against `response_type_overrides()`.
- Files (`type: string, format: binary` in the spec, 21 ops: images, reports, OTA, resources,
  translations, certificates) are `bytes`, the raw body; as `str` text files came back decoded and
  JSON files (translations) as a repr string. Their wrappers are annotated `-> bytes`. An empty body of an `object`
  response gives `None`. Wrapper annotations follow: `None`, `Dict` (JSON object seen on the
  server), `Any` (JSON from a device or rule chain, or not seen with data).
- Plain-text bodies of `str` responses are decoded (4.3 and the generator returned `"b'...'"`);
  undecodable (binary) bodies are returned as bytes.
- Not ported on purpose: 4.3 models_ce/models_pe lookup, `{?...}` path templates, Deferred* handling
  (none in 4.4), `return e` on deserialization errors: it came with the CE/PE model guessing
  (`1d8049c4`, 2020) and hid real errors (4.3 `get_rule_chain_meta_data` returned a ValueError
  object for the Root Rule Chain). Decided (Q4): deserialization errors raise; a field the spec
  marks required but the server sends as null goes into `NULLABLE_REQUIRED_FIELDS` in
  `postprocess.py` (its None check is dropped, `check_spec.py` verifies). Found with
  `probe_deserialization.py`: only `RuleChainMetaData.ruleChainConnections` (240 calls, 2634 models).

Wrappers (`rest_client.py`), 1022 calls in the 4.3 wrappers:
- Mechanical renames applied automatically (matched by HTTP method + path, then by the Java
  controller method name at the end of the summary, then by summary title in the same controller;
  HTTP method and response type must agree, because 4.3 summaries were often copy-pasted).
- Moved endpoints and calls already broken in 4.3 fixed by hand (relations use path params now,
  timeseries history, user settings general, `/list` endpoints, rule engine, resources, ...).
- 21 wrappers whose params changed aligned with the spec (type filter gone, inline_images ->
  include_resources, paging, mobile_login platform, ...).
- 33 wrappers deleted: per-entity public customer / edge / dashboard customers assignment (21),
  OAuth2Info settings (2), solution templates (5), and 5 with new counterparts
  (`is_edqs_api_enabled` -> `get_edqs_state`, trendz settings -> trendz config,
  `delete_self_registration_params` -> `delete_web_self_registration_params`,
  `mobile_app_update_oauth2_clients` -> per bundle, no wrapper yet). `save_mobile_app` lost
  `oauth2_client_ids`. All of them answer 404 "No static resource" on a 4.4 server.
- Base/CE/PE merged: for duplicates the most specific 4.3 version wins (PE, then CE, then Base);
  `__init__` and login from Base; `__load_controllers` creates all 78 controllers.
- Q2: 6 wrappers on operations deprecated in the 4.4 spec are kept (the spec still has them, the
  server serves them; upstream kept wrappers while the spec listed the op): `get_asset_types`
  (-> `get_asset_profile_by_names`), `get_device_types` (-> `get_device_profile_names`),
  `find_entity_timeseries_and_attributes_keys_by_query` / `find_available_entity_keys_by_query`
  (-> `POST /api/v2/entitiesQuery/find/keys`, no wrapper yet, Q5), `save_resource`,
  `get_resource_by_id`. `check_wrappers.py` WARNs about them; mention them in the release notes.
- Q6: wrappers aligned with the spec of the op they call (`check_wrappers.py` WARNs otherwise):
  63 calls got the spec params they lacked (optional, at the end), 24 params optional in the spec
  got `= None`, 91 params required in the spec (88 `body`) lost their default. Enum query params
  are typed `str`. Tested in `test_spec_params.py`.
- Q5: 136 wrappers added for 4.4 operations (generated in the style of the existing ones: required
  params first, ids as *Id objects via get_id, entity_type + entity_id as one EntityId, enum params
  as `str`) and 13 controllers loaded. Names taken where the operation name was already used:
  `claim_device_by_name`, `get_scheduler_events_all`, `get_user_settings_by_type`,
  `put_user_settings_by_type`. Not wrapped on purpose (17): login/refresh_token (RestClient does it),
  4 QR/mobile (upstream removed them in 4.3), `save_lwm2m_device_with_credentials` ("Deprecated."),
  `send_chat_message` (text/event-stream), 9 system-setup (setup wizard). Checked against the spec
  and on a live server (every route exists). `get_activation_link_info` called getActivationLink.
- `create_report`: the spec says application/json, the server takes only multipart/form-data
  (`file`, `info` as JSON); fixed by hand in `report_controller_api.py`, the wrapper accepts `info`
  as a dict too. `check_spec.py` knows it (`SERVER_CONTENT_TYPES`).
- `rest.py` sent `'{}'` for a JSON request without a body (also in 4.3); now it sends none (an
  optional body has a meaning, e.g. mergeAgentApplicationForPreview creates from the template).
- `AgentApplication.agentId` in `NULLABLE_REQUIRED_FIELDS` (null in a merge preview).
- Q10: fields the server sends that the spec (so the model) does not have are kept on the object in
  `additional_properties` (JSON names, only when there are any) and sent back by
  `sanitize_for_serialization` (None left out, like known fields). Before (4.3 and every version since
  3.6) they were dropped silently: `externalId` (hidden in the spec since 3.5; hand-added to ~13
  models in 2023, wiped by the 3.6 regeneration), the fields of `NotificationInfo` subtypes (entityId,
  entityName, actionType, user...), the tenant fields of `get_owners`, `DeviceProfileData.alarms`.
  Not in `to_dict()`/`print`; `external_id` is not a typed attribute (user's choice: only option 1).
  `probe_deserialization.py` fails if any field is dropped.
- Q8 (generator limitations, fixed by hand in the draft and checked on a 4.4 server; the generator
  is treated as a draft, the client result is what counts):
  - Discriminators without a mapping in the spec (`AgentAppConfig`, `AgentAppStep`,
    `AgentAppStepState`): the generator keyed the map by class name, the server sends the enum
    value (`COMPOSE`, `RUN_JOB`, `DOCKER_COMPOSE`, ...), so nothing resolved. Maps set by hand from
    the AgentAppConfigType/AgentAppStepType enums, matched by fields against 67 server templates.
  - oneOf fields typed as the discriminator base instead of empty `OneOf*` classes (deleted, they
    returned raw dicts) or `object`: config -> `AgentAppConfig`, steps -> `list[AgentAppStep]`,
    step states/inputs -> `dict(str, AgentAppStepState)`, getManagedRelatedEntityIds ->
    `list[EntityId]`.
  - `DeviceExportData`, `EntityGroupExportData`, `RuleChainExportData`, `WidgetsBundleExportData`
    inherit `EntityExportData` (the generator flattened them; constructor order kept).
  - `output` required in the geofencing / entity aggregation / related entities aggregation CF
    configurations (declared in the parent, required in the subclass).
  - `ThingsboardErrorCode` constants are numbers (the server sends errorCode as a number).
  - `check_spec.py` now also checks discriminator keys (lowercase, enum values, every subclass),
    oneOf typed as a common discriminator base, and enum constant types. `test_models.py` covers it.
- Q1: 5 wrappers of hidden endpoints deleted (`get_events_get`,
  `get_bundle_widget_types[_details|_infos]_by_bundle_alias`,
  `get_widget_type_by_bundle_alias_and_type_alias`). Replacements: `get_events_v1_get1` with
  `LC_EVENT`, the `widgets_bundle_id` variants, `get_widget_type(fqn=...)`.
- Q7: 36 annotations naming models 4.4 does not have replaced with the spec types (Deferred* ->
  the wrapped type, `ByteArrayResource` -> `str`, `ObjectNode` -> `JwtPair`, ...); every
  `RestClient` annotation resolves with `typing.get_type_hints`. The `str` ones of JSON and binary
  responses follow the spec and are revisited with Q3.

## Current state

- `check_spec.py`: 824/824 operations, 0 errors, 0 warnings.
- `check_wrappers.py --old-package draft/tb_rest_client`: 826 controller calls, all work; WARN 6
  deprecated ops (Q2, kept on purpose); INFO 17 operations not wrapped on purpose (Q5).
- `codegen/tests/run_all.py`: all 8 test files pass.

## Positional order changes (for the release notes)

Calls by keyword keep working; positional calls of these wrappers must be updated.
- `get_timeseries(entity_id, keys, start_ts, end_ts, ...)` -> `(entity_id, start_ts, end_ts, keys, ...)`:
  `keys` is optional in 4.4 (alternative: repeatable `key`).
- `upload_image(title, file, ...)` -> `(file, title, ...)`: only `file` is required.
- `upload_resource(title, resource_type, descriptor, resource_sub_type, file)` ->
  `(resource_type, file, title, descriptor, resource_sub_type)`.
- `save_ota_package_data(ota_package_id, checksum, checksum_algorithm, file)` ->
  `(ota_package_id, checksum_algorithm, file, checksum)`.

Also breaking: 88 wrappers no longer default `body` to None (the spec requires the body), e.g.
`save_entity_telemetry(entity_id, scope)` now raises TypeError instead of sending an empty request;
the same for `is_public` in `update_image_public_status`. All of them:
`git log -1 -p --grep "Require wrapper params" -- draft/tb_rest_client/rest_client.py`.

## Open questions (need the user's decision)

- **Q3 (resolved). Responses typed as `string` in the spec** (43 ops). Checked on the server (GETs with
  `probes/string_responses.json`; writes on a temporary device that was deleted afterwards):
  - empty body (200, no Content-Type): telemetry/attribute save and delete (8), device API
    `postTelemetry`, `postDeviceAttributes`, `replyToCommand`, `saveClaimingInfo` -> `None`;
  - JSON object: `getPersistedRpcByDevice`, `getDeviceAttributes`, `findMissingToRelatedRuleChains`,
    `provisionDevice` (errors too: 200 `{"status":"NOT_FOUND"}`) -> `object`;
  - JSON only when a device or rule answers, else 408/504/409 with an empty body:
    `subscribeTo{Attributes,Commands}`, device API `postRpcRequest`, two-way RPC v1/v2, rule-engine
    (4) -> `object` (200 not seen, no device connected);
  - JSON string: `getLoginProcessingUrl`, `getMailProcessingUrl` -> `str` (already works);
  - plain text or empty: `getHelpBaseUrl`, `getLatestAgentImageRef`, `getPrivacyPolicy`,
    `getTermsOfUse` -> `str` (works since the decode fix);
  - binary: `getFirmware`, `getSoftware` and the 8 `download_*` wrappers -> `bytes`;
  - not determined (500/404/409/400 on test data): edge missing attributes (2),
    `getAgentUpgradeTarget`, one-way RPC, `activateEmail`, `mobileLogin`, `syncEdge`,
    `claimDevice`/`reClaimDevice`: decide from the ThingsBoard controller code.
  Done, see Done above. The 9 ops typed from the spec descriptions can be confirmed on a server
  with an edge, an agent, claiming or a connected device.
- **Q9. License header.** 4.3 files had the Apache header; generated files do not.

## Remaining work to the final result

1. Resolve Q1-Q9.
2. Replace `tb_rest_client/` with `draft/tb_rest_client/` (drop the generator boilerplate), update
   `pyproject.toml` (version 4.4.0, dependencies: certifi, six, python-dateutil, urllib3, requests,
   pyjwt) and add a `.swagger-codegen-ignore` if future generations target the package directly.
3. Migrate `examples/` (CE/PE pairs -> one version) and `test/` (`tests_ce.py`, `tests_pe.py` -> one
   suite on `RestClient`), run them against a live 4.4 server.
4. Update the root README (single edition, new import) and list the breaking changes for the
   release notes (import, removed and renamed wrappers, changed signatures; see commit messages).
5. Open a PR from `codegen/4.4`.

## How to verify

Run all of these after every change in `draft/`:

```bash
python3 codegen/check_spec.py                                   # generated code vs spec (--full for all)
python3 codegen/check_wrappers.py --old-package draft/tb_rest_client   # RestClient vs generated API
python3 codegen/tests/run_all.py                                # fake-HTTP tests, no server needed
```

- `check_wrappers.py` without `--old-package` compares the 4.3 wrappers with the draft (how the
  migration was planned). `--json calls.json` writes the old -> new mapping of every call.
- A single test: `python3 codegen/tests/test_aligned.py` (each prints OK/FAIL per request).
- Fresh generation for comparison: `codegen/generate.sh /tmp/gen && diff -r draft /tmp/gen`
  (differences = manual edits; `postprocess.py` fixes are applied in both).

### Live server: hidden and removed endpoints

A local ThingsBoard 4.4 at `http://localhost:8080` was used. Credentials only via environment
variables, never in files:

```bash
export TB_URL=http://localhost:8080
export TB_TENANT_USERNAME=... TB_TENANT_PASSWORD=...
export TB_SYSADMIN_USERNAME=... TB_SYSADMIN_PASSWORD=...     # only for sysadmin requests
# or TB_TENANT_TOKEN / TB_SYSADMIN_TOKEN: a JWT from Swagger UI instead of a password
python3 codegen/probe_endpoints.py codegen/probes/calibration.json        # how this server answers
python3 codegen/probe_endpoints.py codegen/probes/hidden_endpoints.json   # Q1
python3 codegen/probe_endpoints.py codegen/probes/removed_endpoints.json  # all 34 must say "No static resource"
python3 codegen/probe_endpoints.py codegen/probes/string_responses.json   # Q3: GETs typed as string
python3 codegen/probe_deserialization.py   # real GET answers through the draft models (read-only)
```

Reading answers: 404 "No static resource" = no such route; 404 "... is not found" = route exists,
entity does not; 405 = path exists for another HTTP method; 400 "Parameter conditions ... not met" =
path exists and the message lists the accepted param variants; 200 = works. Write requests
(POST/PUT/DELETE) must only use `{randomId}` in an id path param or a malformed body for a typed
model, so nothing on the server changes. A string is a valid JsonNode/object body, and enum or name
path params are not ids: save_mail_templates, sendAddonAccessRequest and sendPlanUpgradeRequest were
executed this way by mistake during the Q5 check. Placeholders: `{tenantId}`, `{deviceId}` (first tenant device), `{deviceToken}` (its
access token), `{randomId}`. `"user": "none"` sends no JWT (noauth and device API). Each line shows
status, Content-Type and the start of the body.

### Manual check in Swagger UI or curl

- Swagger UI: `http://localhost:8080/swagger-ui.html`, Authorize with the tenant login. It only
  shows documented operations and params; hidden variants need curl.
- curl:
  ```bash
  TOKEN=$(curl -s -X POST "$TB_URL/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$TB_TENANT_USERNAME\",\"password\":\"$TB_TENANT_PASSWORD\"}" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')
  curl -i "$TB_URL/api/widgetTypes?isSystem=true&bundleAlias=charts" -H "X-Authorization: Bearer $TOKEN"
  ```
- What a wrapper would send, without a server: `ApiClient().sanitize_for_serialization(obj)` shows
  the JSON body; the tests in `codegen/tests/` show how to fake `api_client.request`.

## Environment

- Linux: `generate.sh` uses GNU `mktemp --suffix` and `sha1sum` (fails on macOS as is).
- Java 8+ (tested with 25), curl, python3; Python packages for the draft and tests:
  `requests pyjwt six urllib3 python-dateutil`.
- `.claude/settings.local.json` is local and must not be committed (in .gitignore).

## Working conventions

- Explain findings and propose before larger changes; the user decides and often checks things
  manually in Swagger UI. Keep commits small, one logical step each, with a one-line commit
  message (no body, no Co-Authored-By trailer).
- Keep the generated baseline separate from manual edits; put reusable scripts in `codegen/`,
  one-off scripts in the session scratchpad.
- Never put credentials, tokens or ids from a real server into the repository.
