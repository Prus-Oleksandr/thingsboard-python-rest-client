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
- Hidden endpoints (served by the server but not in the spec) are considered relevant; how to keep
  them is still open (Q1 below).
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

## Current state

- `check_spec.py`: 824/824 operations, 0 errors, 66 warnings (see Q3, Q8).
- `check_wrappers.py --old-package draft/tb_rest_client`: 695 controller calls, 690 work, 5 errors
  (the hidden endpoints of Q1), 36 annotation warnings (Q7), 154 new operations without a wrapper (Q5).
- `codegen/tests/run_all.py`: all 5 test files pass.

## Open questions (need the user's decision)

- **Q1. Hidden endpoints (5 wrappers).** Not in the spec, but the server serves them (checked with
  `codegen/probes/hidden_endpoints.json`). The generator cannot produce them, and OpenAPI allows one
  operation per path + method, so they cannot be added to the spec either.
  - `get_events_get`: `GET /api/events/{entityType}/{entityId}` works (200). 4.3 docs: deprecated,
    returns lifecycle events only. Documented equivalent: getEventsByType with `LC_EVENT`.
  - `get_bundle_widget_types[_details|_infos]_by_bundle_alias`: `?isSystem&bundleAlias` works (200).
    Deprecated in 4.3. Documented ops take `widgetsBundleId`.
  - `get_widget_type_by_bundle_alias_and_type_alias`: route exists, finds nothing (404 "Requested
    item wasn't found!"). Documented: `get_widget_type(fqn='system.<fqn>')`.
  - Proposal made: keep the 4 working ones via `self.api_client.call_api(...)` with a comment that
    the endpoint is hidden from the spec; delete the widget_type one. Not confirmed yet.
- **Q2. Deprecated operations in the 4.4 spec** used by wrappers: `get_asset_types`
  (-> getAssetProfileNames), `get_device_types` (-> getDeviceProfileNames),
  `find_available_entity_keys_by_query` (-> `POST /api/v2/entitiesQuery/find/keys`),
  `save_resource`, `get_resource_by_id`. Proposal: a WARN in check_wrappers, then decide on switching.
- **Q3. JSON responses typed as `string` in the spec** (43 ops, e.g. `get_device_attributes`,
  `get_persisted_rpc_by_device`): the client then returns a Python repr string of the JSON. Needs a
  fix approach (e.g. postprocess response_type to `object`) and a check on a live server.
- **Q4. Deserialization errors.** 4.3 returned the exception object instead of raising. Not
  ported: currently raises (e.g. when the server returns null in a field the spec marks required).
  Decide: raise, or log a warning and return the raw dict.
- **Q5. 154 new 4.4 operations without wrappers** (`check_wrappers.py --full`, INFO): which to add
  (e.g. `update_mobile_app_bundle_oauth2_clients`, AI, agents, trendz views).
- **Q6. Params coverage.** Some wrappers do not expose every spec param (found: `get_widget_types`
  lacks `scada_first`). Proposal: check_wrappers lists spec params a wrapper does not accept, then align.
- **Q7. 36 annotations name models that 4.4 does not have** (hidden by
  `from __future__ import annotations`). Fix to the new response types.
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
python3 codegen/probe_endpoints.py codegen/probes/calibration.json        # how this server answers
python3 codegen/probe_endpoints.py codegen/probes/hidden_endpoints.json   # Q1
python3 codegen/probe_endpoints.py codegen/probes/removed_endpoints.json  # all 34 must say "No static resource"
```

Reading answers: 404 "No static resource" = no such route; 404 "... is not found" = route exists,
entity does not; 405 = path exists for another HTTP method; 400 "Parameter conditions ... not met" =
path exists and the message lists the accepted param variants; 200 = works. Write requests
(POST/PUT/DELETE) must only use `{randomId}` or a malformed JSON body, so nothing on the server
changes. Placeholders: `{tenantId}`, `{deviceId}` (first tenant device), `{randomId}`.

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
