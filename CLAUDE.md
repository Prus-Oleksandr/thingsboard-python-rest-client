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
  (`STRING_RESPONSE_TYPES` in `postprocess.py`: 12 -> `None`, 20 -> `object`, 11 stay `str`);
  `check_spec.py` checks the generated types against that table. An empty body of an `object`
  response gives `None`. Wrapper annotations follow: `None`, `Dict` (JSON object seen on the
  server), `Any` (JSON from a device or rule chain, or not seen with data).
- Plain-text bodies of `str` responses are decoded (4.3 and the generator returned `"b'...'"`);
  undecodable (binary) bodies are returned as bytes.
- Not ported on purpose: 4.3 models_ce/models_pe lookup, `{?...}` path templates, Deferred* handling
  (none in 4.4), `return e` on deserialization errors (see Q4).

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
- Q1: 5 wrappers of hidden endpoints deleted (`get_events_get`,
  `get_bundle_widget_types[_details|_infos]_by_bundle_alias`,
  `get_widget_type_by_bundle_alias_and_type_alias`). Replacements: `get_events_v1_get1` with
  `LC_EVENT`, the `widgets_bundle_id` variants, `get_widget_type(fqn=...)`.
- Q7: 36 annotations naming models 4.4 does not have replaced with the spec types (Deferred* ->
  the wrapped type, `ByteArrayResource` -> `str`, `ObjectNode` -> `JwtPair`, ...); every
  `RestClient` annotation resolves with `typing.get_type_hints`. The `str` ones of JSON and binary
  responses follow the spec and are revisited with Q3.

## Current state

- `check_spec.py`: 824/824 operations, 0 errors, 23 warnings (Q8).
- `check_wrappers.py --old-package draft/tb_rest_client`: 690 controller calls, all work, 0 warnings, 154 new operations without a wrapper (Q5).
- `codegen/tests/run_all.py`: all 6 test files pass.

## Open questions (need the user's decision)

- **Q2. Deprecated operations in the 4.4 spec** used by wrappers: `get_asset_types`
  (-> getAssetProfileNames), `get_device_types` (-> getDeviceProfileNames),
  `find_available_entity_keys_by_query` (-> `POST /api/v2/entitiesQuery/find/keys`),
  `save_resource`, `get_resource_by_id`. Proposal: a WARN in check_wrappers, then decide on switching.
- **Q3. Responses typed as `string` in the spec** (43 ops). Checked on the server (GETs with
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
  Done: decode fix (step 1), the op -> type table (step 2, see Done). Left (step 3): binary
  responses already come back as bytes, but `get_firmware`, `get_software` and the 8 `download_*`
  wrappers are still annotated `str`.
- **Q4. Deserialization errors.** 4.3 returned the exception object instead of raising. Not
  ported: currently raises (e.g. when the server returns null in a field the spec marks required).
  Decide: raise, or log a warning and return the raw dict.
- **Q5. 154 new 4.4 operations without wrappers** (`check_wrappers.py --full`, INFO): which to add
  (e.g. `update_mobile_app_bundle_oauth2_clients`, AI, agents, trendz views).
- **Q6. Params coverage.** Some wrappers do not expose every spec param (found: `get_widget_types`
  lacks `scada_first`). Proposal: check_wrappers lists spec params a wrapper does not accept, then align.
- **Q8. Generator limitations** (check_spec WARN): `oneOf` fields typed as empty `OneOf*` classes or
  `object` (15, mostly AgentApp*; single-ref oneOf could be fixed in postprocess), 4 `*ExportData`
  models do not inherit `EntityExportData`, 3 required `output` fields not enforced,
  `ThingsboardErrorCode` int enum constants are strings.
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
```

Reading answers: 404 "No static resource" = no such route; 404 "... is not found" = route exists,
entity does not; 405 = path exists for another HTTP method; 400 "Parameter conditions ... not met" =
path exists and the message lists the accepted param variants; 200 = works. Write requests
(POST/PUT/DELETE) must only use `{randomId}` or a malformed JSON body, so nothing on the server
changes. Placeholders: `{tenantId}`, `{deviceId}` (first tenant device), `{deviceToken}` (its
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
