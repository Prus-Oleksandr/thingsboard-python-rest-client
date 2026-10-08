# Client generation

| Path | What it is |
|---|---|
| `tb_rest_client/` | Current released client. Not touched by generation. |
| `codegen/spec/thingsboard-swagger.json` | OpenAPI spec the draft is generated from. |
| `codegen/config.json` | swagger-codegen options for the Python generator. |
| `codegen/generate.sh` | Downloads the pinned swagger-codegen v3 CLI, generates the client and runs `postprocess.py`. |
| `codegen/postprocess.py` | Idempotent fixes for known generator bugs, applied after every generation. |
| `codegen/check_spec.py` | Compares a generated client with the spec and reports what is lost or wrong. |
| `codegen/check_wrappers.py` | Maps every `rest_client_*.py` wrapper call to the new client and reports what breaks. |
| `codegen/apply_wrapper_renames.py` | Applies the renames from `check_wrappers.py --json` to copies of the wrappers. |
| `codegen/client_parser.py` | Shared parser of generated api and model code used by the scripts above. |
| `draft/` | Generated draft that is reviewed and edited by hand. |

Generate the draft (requires Java and curl):

```bash
codegen/generate.sh            # into draft/
codegen/generate.sh /tmp/gen   # into another dir, e.g. to diff a fresh generation against the edited draft
```

The script refuses to write into an existing directory, so the edited draft is never overwritten.

Check the draft against the spec:

```bash
python3 codegen/check_spec.py                                # summary with examples
python3 codegen/check_spec.py --full                         # every finding
python3 codegen/check_spec.py --package /tmp/gen/tb_rest_client --json report.json
```

Operations are matched by HTTP method + path and models by schema name. `ERROR` means something
from the spec is lost or wrong in the client; `WARN` lists known generator limitations and spots
where the spec itself looks wrong and should be checked on a server.

Check the hand-written wrappers of the current client against the draft:

```bash
python3 codegen/check_wrappers.py                            # summary with examples
python3 codegen/check_wrappers.py --full --json calls.json   # every finding + old -> new mapping of each call
```

Each wrapper call is resolved to the old generated method, its HTTP method + path, and the new
method with the same HTTP method + path. `ERROR` means the wrapper breaks even after renaming
(endpoint or param gone, new required param, or the call was already broken); `RENAME` lists
mechanical renames; `INFO` lists new operations without a wrapper.

Migrate the wrappers to the draft: copy them unmodified, apply the renames, then check the result
against the draft itself (no renames should be left, only the errors kept for manual review):

```bash
cp tb_rest_client/rest_client_{base,ce,pe}.py draft/tb_rest_client/
python3 codegen/check_wrappers.py --json calls.json
python3 codegen/apply_wrapper_renames.py calls.json draft/tb_rest_client
python3 codegen/check_wrappers.py --old-package draft/tb_rest_client
```
