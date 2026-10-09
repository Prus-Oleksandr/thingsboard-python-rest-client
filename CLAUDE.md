# ThingsBoard Python REST client: migration to 4.4 (branch `codegen/4.4`)

This branch rebuilds the client for ThingsBoard 4.4 from the OpenAPI spec and verifies every
generated or migrated piece against the spec and a live 4.4 server. Read this file fully before
changing anything.

**Always answer the user in Ukrainian** (replies, status lines between tool calls, questions).
Never switch to Russian, also not in long technical turns. Code, identifiers and commit messages
stay in English.

## Status at the end of 2026-10-09

- One client class `RestClient` in `draft/tb_rest_client/rest_client.py`: 835 public wrappers
  (the 4.3 ones migrated and aligned with the 4.4 spec, plus 136 new ones), 91 controllers loaded.
- `check_spec.py`: 824/824 operations, 0 errors, 0 warnings. `check_wrappers.py --old-package
  draft/tb_rest_client`: 826 calls, all match the spec; WARN 6 deprecated ops (kept on purpose);
  INFO 17 ops not wrapped on purpose. `codegen/tests/run_all.py`: 8 test files pass.
- Live server (read only): `probe_deserialization.py` 240 calls, 0 errors, 0 dropped fields;
  `smoke_scenario.py` 13/13 OK. `smoke_scenario.py --write` was **never run** on a server (needs the
  user's consent); only its calls were checked against the wrapper signatures.
- Open: Q9 (license header), then the final steps under "Remaining work".
- The user keeps a personal Ukrainian report `MIGRATION_REPORT_UK.md` (history + practical check
  instructions). It is local only (listed in `.git/info/exclude`): never commit or push it.

## Working conventions (from the user)

- The generator only produced a draft; what counts is how the final client behaves. Fix whatever
  the generator got wrong directly in `draft/tb_rest_client`, and verify it by hand on a live server,
  not only with tests. Do not spend effort on making `generate.sh` reproduce hand fixes.
- The spec is the reference. Deviate only where the server behaves differently, with evidence (a
  live answer via Swagger UI, curl or the probes), and record the deviation where a check enforces it
  (see "Deviations from the spec").
- For disputed choices look at how the upstream maintainers solved it before (git history of
  `master`, the upstream remote is `thingsboard/thingsboard-python-rest-client`), and follow that.
- Explain findings and propose before larger changes; the user decides and often checks things
  manually in Swagger UI. Small commits, one logical step each, one-line message, no body, no
  Co-Authored-By trailer. Commit author stays as is.
- **Never commit or push without the user's explicit "yes".** Push only to `origin` (the user's fork).
- **Never write to the user's server without consent.** Read requests are fine. A write probe is
  safe only with a random id in an id path param (404) or a string body for a typed model; enum or
  name path params are not ids, and JsonNode/object/string/array bodies accept a string. During the
  Q5 check this went wrong once: `save_mail_templates` stored a string (restored to `{}`) and
  `sendAddonAccessRequest` / `sendPlanUpgradeRequest` sent notifications. Report any state change at
  once and ask before repairing it.
- Credentials only via environment variables; never put credentials, tokens, emails or ids from a
  real server into the repository (tests use the spec example id `784f394c-...`).
- Reusable scripts go to `codegen/`, one-off scripts to the session scratchpad.

## Layout

| Path | What it is |
|---|---|
| `tb_rest_client/` | Released 4.3 client (CE/PE split). Reference only until the final swap. |
| `draft/tb_rest_client/` | The 4.4 client: generated `api/` and `models/` (with hand fixes), hand-edited `api_client.py`, `rest.py`, `configuration.py`, `rest_client.py` (`RestClient`). |
| `draft/` (other files) | Generator boilerplate (setup.py, tox.ini, README.md, ...), not used; drop at the swap. |
| `codegen/spec/thingsboard-swagger.json` | ThingsBoard 4.4.0 OpenAPI 3.1 spec, pretty-printed. |
| `codegen/generate.sh`, `config.json`, `postprocess.py` | Reproducible generation (swagger-codegen v3 3.0.82) and its idempotent fixes. |
| `codegen/check_spec.py` | Generated client vs spec, including the deliberate deviations. |
| `codegen/check_wrappers.py` | Every `RestClient` wrapper call vs the generated API and the spec. |
| `codegen/client_parser.py` | Shared ast parser of generated api/model code. |
| `codegen/tests/` | 8 test files with the HTTP layer faked (`run_all.py`). |
| `codegen/smoke_scenario.py` | Practical end-to-end check on a live server (read only; `--write` creates and deletes `smoke-*` entities). |
| `codegen/probe_deserialization.py` | Real GET answers through the models: errors, dropped fields, unresolved subclasses. |
| `codegen/probe_endpoints.py`, `codegen/probes/` | Raw requests: route exists or not, status, content type. |
| `codegen/apply_wrapper_renames.py` | The one-time 4.3 -> 4.4 rename of wrapper calls (done). |

## Decisions already made (do not reopen without the user)

- One class `RestClient`; import `from tb_rest_client.rest_client import RestClient`; no CE/PE aliases.
- Wrappers match the spec of the operation they call: all its params, required ones first in spec
  order, required-ness as in the spec, response type annotation. Names stay as in 4.3 unless they
  clash. Signatures follow the spec even when positional calls break (upstream did the same:
  PR #5, `867f168a`, `65e38a77`, `24fcd2a1`); every reorder is listed for the release notes.
- No wrapper for an endpoint the spec does not have, even if the server serves it (Q1); no stubs, no
  raw `call_api` in wrappers. Wrappers of ops deprecated in the spec are kept while the spec lists them (Q2).
- Not wrapped on purpose (17 INFO in check_wrappers): login/refresh_token (RestClient does it), 4
  QR/mobile ops (upstream removed them in 4.3), `save_lwm2m_device_with_credentials` ("Deprecated."),
  `send_chat_message` (text/event-stream), 9 system-setup ops (first-start wizard).
- `EntityId(id, entity_type)` argument order of 4.3 is kept (`postprocess.py`).
- 4.3 CE "assign/unassign X to/from customer" wrappers run on the owner API and return the entity.
- Deserialization errors raise (4.3's `return e` hid real errors). Fields the spec marks required but
  the server sends as null go into `NULLABLE_REQUIRED_FIELDS`.
- Fields the server sends that the spec does not describe are kept in `obj.additional_properties`
  (JSON names, only set when there are any) and sent back on serialization (None left out). Not
  shown by `to_dict()`/`print`; no typed `external_id` attribute (user's choice).
- Enum path/query params are typed `str` in wrappers; ids accept `*Id` objects (via `get_id`).
- Names chosen for clashes: `claim_device_by_name`, `get_scheduler_events_all`,
  `get_user_settings_by_type`, `put_user_settings_by_type`; `handle_rule_engine_request_for_entity[...]`.

## Deviations from the spec (each enforced by a check)

| Deviation | Why (server evidence) | Where / enforced by |
|---|---|---|
| 43 ops typed `string` retyped: 12 `None`, 20 `object`, 2 firmware `bytes`, 9 `str` | JSON, empty, text or file bodies seen on the server | `STRING_RESPONSE_TYPES` in `postprocess.py`; `check_spec` |
| 21 `format: binary` responses -> `bytes`, raw body | files (JSON/JS/SVG files were decoded or repr'd) | `response_type_overrides()`; `check_spec` |
| `RuleChainMetaData.ruleChainConnections`, `AgentApplication.agentId` nullable | null in Root Rule Chain metadata / merge preview | `NULLABLE_REQUIRED_FIELDS` in `postprocess.py`; `check_spec` |
| `createReport` sent as multipart (`file`, `info` JSON) | server: "not a multipart request" | hand-edited `report_controller_api.py`; `SERVER_CONTENT_TYPES` in `check_spec` |
| `ContactBasedObject.id` -> `EntityId` | spec `{}`, server sends `{"entityType": "TENANT", ...}` | hand-edited model; `SERVER_TYPES` in `check_spec` |
| Agent discriminator maps keyed by enum values (`COMPOSE`, `RUN_JOB`, `DOCKER_COMPOSE`, ...) | spec has no mapping; server sends the enum value | hand-edited `agent_app_config.py`, `agent_app_step.py`, `agent_app_step_state.py`; `check_spec` |

## Hand fixes a fresh generation would NOT reproduce

`postprocess.py` re-applies the response types, nullable fields, discriminator `#/components`
refs and the EntityId order. Everything else was edited by hand in `draft/` and is lost if the draft
is regenerated: never regenerate over `draft/` (`generate.sh` refuses an existing dir); for a newer
spec generate into `/tmp/gen`, diff, and port. Hand fixes:
- `api_client.py`: shared-nothing `Configuration`, None params not sent, id objects in paths, lazy
  pool, comma-joined array params, plain-text decode, `bytes` raw body, empty body -> None for
  `object`, `additional_properties` keep/send back, `select_header_accept` sends every listed type
  (4.4 adds `application/json` for errors to file/text answers; JSON-only made 24 ops answer 406).
- `rest.py`: no body for a JSON request without one (the generator sent `'{}'`).
- `report_controller_api.py` `create_report`; `agent_application_controller_api.py`
  `get_managed_related_entity_ids` -> `list[EntityId]`.
- Models: agent discriminator maps; oneOf fields typed as the discriminator base (config ->
  `AgentAppConfig`, steps -> `list[AgentAppStep]`, states -> `dict(str, AgentAppStepState)`) and the
  10 empty `OneOf*` classes deleted; `DeviceExportData`, `EntityGroupExportData`,
  `RuleChainExportData`, `WidgetsBundleExportData` inherit `EntityExportData`; `output` required in
  the geofencing / entity aggregation / related entities aggregation CF configurations;
  `ThingsboardErrorCode` constants are numbers; `ContactBasedObject.id` is `EntityId`.
- `rest_client.py` (all wrappers).

## History (commits on `codegen/4.4`)

- 2026-10-08: generation baseline `1698d2d6`; discriminator refs `9c8f5141`; runtime ports
  `bed5f256`, `29e74e9e`; EntityId order `b2ef2657`; 4.3 wrappers copied `3981023d` and renamed
  `31e75244`, `73d28d42`, `1cc347ce`; hand fixes `89664cae`, `07c729c8`; owner-API assignment
  `5478c49f`; Base/CE/PE merged `9463a5f6`; 33 wrappers of gone endpoints removed `18357351`, `98f9ef96`.
- 2026-10-09: Q1 hidden endpoints `486ef1b0`; Q7 annotations `dfd45a51`; Q3 string responses
  `721951a8`, `d5e8ea1d`, `7bde572c`; Q4 `4bd54c8c`; Q6 params `f511b1c6`, `3c440122`, `1714f530`;
  Q5 new wrappers and fixes `1aa8ef3b` (no `'{}'`), `25da4bd0`, `5e58e5fc`, `9f4c3efe`
  (createReport), `b3ca07d6`; Q8 generator limitations `99bc1855`, `ada132fc`, `a7695721`,
  `f87d2554`, `5fcd9ad2`; probes `701cd28b`, `a79e5d2c`; Q10 `cfaf1e66`; then the Accept header
  (406) fix, `ContactBasedObject.id`, and `smoke_scenario.py`.

## Release notes material

Breaking:
- Import `from tb_rest_client.rest_client import RestClient` (no RestClientCE/RestClientPE).
- 38 wrappers removed: 33 endpoints gone in 4.4 (`18357351`, `98f9ef96`; replacements in the commit
  messages), 5 on endpoints hidden from the spec (`486ef1b0`: `get_events_get` -> `get_events_v1_get1`
  with `LC_EVENT`, `*_by_bundle_alias` -> the `widgets_bundle_id` variants, `get_widget_type(fqn=...)`).
- Positional order changed (keyword calls keep working):
  `get_timeseries(entity_id, start_ts, end_ts, keys, ...)` (keys was 2nd; optional in 4.4),
  `upload_image(file, title, ...)`, `upload_resource(resource_type, file, title, descriptor,
  resource_sub_type)`, `save_ota_package_data(ota_package_id, checksum_algorithm, file, checksum)`.
- 88 wrappers require `body` (was `None` by default and sent an empty request); also `is_public` in
  `update_image_public_status`. List: `git log -1 -p --grep "Require wrapper params"`.
- Deserialization errors raise instead of returning the exception object.
New behaviour: JSON answers the spec calls string come back as dict, empty answers as None, files as
bytes, text decoded; unknown fields in `additional_properties`; polymorphic models resolve to
subclasses; 136 new wrappers (agents, AI, reports v2, alarm rules, API keys, ...); deprecated but kept:
`get_asset_types`, `get_device_types`, `find_*_keys_by_query` (v2: `find_available_entity_keys_by_query_v2`),
`save_resource`, `get_resource_by_id`.

## Remaining work to the final result

1. Q9: license header. 4.3 files had the Apache header, generated files do not. Ask the user.
2. Optional: 62 wrappers have no return annotation (e.g. `get_timeseries`, `get_attributes`); the
   spec types are known (`dict(str, list[TsData])`, `list[AttributeData]`).
3. With the user's consent run `python3 codegen/smoke_scenario.py --write` once on a test server.
4. Swap: `draft/tb_rest_client/` replaces `tb_rest_client/` (drop the boilerplate in `draft/`);
   `pyproject.toml` version 4.4.0, dependencies certifi, six, python-dateutil, urllib3, requests,
   pyjwt; tools in `codegen/` must then point at the new location (their `--package`/default paths).
5. Migrate `examples/` (14 files, CE/PE pairs -> one) and `test/` (`tests_ce.py` + `tests_pe.py` ->
   one suite on `RestClient`, mind the positional changes), run them against a 4.4 server.
6. Root README (single edition, new import) and the release notes from the section above.
7. PR from `codegen/4.4` to upstream `master`.
Not verified with data on a server (decide when evidence appears): 9 of the 43 string ops typed from
the spec descriptions (edge missing attributes, agent upgrade target, one-way RPC, activateEmail,
mobileLogin, syncEdge, claim/reclaim); `HasIdObject.id`, `MicrosoftTeamsNotificationTargetConfig.id`
left as `object`.

## How to verify

After every change in `draft/`:

```bash
python3 codegen/check_spec.py                                          # --full for every finding
python3 codegen/check_wrappers.py --old-package draft/tb_rest_client   # --full, --json calls.json
python3 codegen/tests/run_all.py
```

Live server (a local ThingsBoard 4.4, e.g. `http://localhost:8080`); credentials only via env:

```bash
export TB_URL=http://localhost:8080
export TB_TENANT_USERNAME=... TB_TENANT_PASSWORD=...   # or TB_TENANT_TOKEN (a JWT from Swagger UI)
export TB_SYSADMIN_USERNAME=... TB_SYSADMIN_PASSWORD=...   # or TB_SYSADMIN_TOKEN, only for sysadmin probes
python3 codegen/smoke_scenario.py            # practical check, read only (13 steps)
python3 codegen/smoke_scenario.py --write    # also creates/deletes smoke-* entities: only with consent
python3 codegen/probe_deserialization.py     # every paging-only/id GET through the models
python3 codegen/probe_endpoints.py codegen/probes/removed_endpoints.json  # all 34: "No static resource"
python3 codegen/probe_endpoints.py codegen/probes/string_responses.json   # content type of string ops
python3 codegen/probe_endpoints.py codegen/probes/hidden_endpoints.json   # Q1 evidence
```

Reading probe answers: 404 "No static resource" = no such route; 404 "... is not found" = route
exists, entity does not; 405 = path exists for another method; 400 "Parameter conditions ... not
met" = the message lists the accepted param variants; 200 = works. Probe placeholders: `{tenantId}`,
`{deviceId}` (first tenant device), `{deviceToken}`, `{randomId}`; `"user": "none"` sends no JWT.

Manual check: Swagger UI `http://localhost:8080/swagger-ui.html` (Authorize with the tenant), or
curl with a token from `POST /api/auth/login`. What a wrapper sends without a server:
`ApiClient().sanitize_for_serialization(obj)`; the tests show how to fake `api_client.request`.

## Environment (new machine)

```bash
git pull                                   # branch codegen/4.4 from origin
python3 -m venv .venv && source .venv/bin/activate
pip install requests pyjwt six urllib3 python-dateutil
```

- Java 8+ and curl only for `codegen/generate.sh` (Linux: GNU `mktemp --suffix`, `sha1sum`); the
  generator jar is downloaded into `codegen/bin/` (gitignored).
- `.claude/settings.local.json` is local and must not be committed (in .gitignore).
