# Client generation

| Path | What it is |
|---|---|
| `tb_rest_client/` | Current released client. Not touched by generation. |
| `codegen/spec/thingsboard-swagger.json` | OpenAPI spec the draft is generated from. |
| `codegen/config.json` | swagger-codegen options for the Python generator. |
| `codegen/generate.sh` | Downloads the pinned swagger-codegen v3 CLI, generates the client and runs `postprocess.py`. |
| `codegen/postprocess.py` | Idempotent fixes for known generator bugs, applied after every generation. |
| `codegen/check_spec.py` | Compares a generated client with the spec and reports what is lost or wrong. |
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
from the spec is lost or wrong in the client; `WARN` lists known generator limitations.
