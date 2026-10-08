# Client generation

| Path | What it is |
|---|---|
| `tb_rest_client/` | Current released client. Not touched by generation. |
| `codegen/spec/thingsboard-swagger.json` | OpenAPI spec the draft is generated from. |
| `codegen/config.json` | swagger-codegen options for the Python generator. |
| `codegen/generate.sh` | Downloads the pinned swagger-codegen v3 CLI and generates the client. |
| `draft/` | Generated draft that is reviewed and edited by hand. |

Generate the draft (requires Java and curl):

```bash
codegen/generate.sh            # into draft/
codegen/generate.sh /tmp/gen   # into another dir, e.g. to diff a fresh generation against the edited draft
```

The script refuses to write into an existing directory, so the edited draft is never overwritten.
