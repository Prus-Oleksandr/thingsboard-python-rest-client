#!/usr/bin/env bash
# Generates a draft Python REST client from the ThingsBoard OpenAPI spec.
#
# Usage: codegen/generate.sh [output_dir]   (default: draft/)
#
# The output dir must not exist: the draft is edited by hand after generation,
# so the script never overwrites it. Generate into another dir to compare.
set -euo pipefail

CODEGEN_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$CODEGEN_DIR")"

CODEGEN_VERSION=3.0.82
JAR="$CODEGEN_DIR/bin/swagger-codegen-cli-$CODEGEN_VERSION.jar"
JAR_URL="https://repo1.maven.org/maven2/io/swagger/codegen/v3/swagger-codegen-cli/$CODEGEN_VERSION/swagger-codegen-cli-$CODEGEN_VERSION.jar"
SPEC="$CODEGEN_DIR/spec/thingsboard-swagger.json"
CONFIG="$CODEGEN_DIR/config.json"
OUT="${1:-$ROOT_DIR/draft}"

if [ -e "$OUT" ]; then
    echo "Output dir '$OUT' already exists, refusing to overwrite it." >&2
    exit 1
fi

if [ ! -f "$JAR" ]; then
    mkdir -p "$(dirname "$JAR")"
    curl -sSfL -o "$JAR" "$JAR_URL"
    echo "$(curl -sSfL "$JAR_URL.sha1")  $JAR" | sha1sum -c -
fi

# swagger-codegen v3 Python generator mishandles OpenAPI 3.1 input: most
# primitive types become 'object' and allOf inheritance is dropped. The spec
# uses no 3.1-only constructs, so generate from a copy labeled 3.0.3.
SPEC_30="$(mktemp --suffix=.json)"
trap 'rm -f "$SPEC_30"' EXIT
python3 -I -c '
import json, sys
spec = json.load(open(sys.argv[1]))
spec["openapi"] = "3.0.3"
json.dump(spec, open(sys.argv[2], "w"))
' "$SPEC" "$SPEC_30"

java -jar "$JAR" generate \
    -l python \
    -i "$SPEC_30" \
    -c "$CONFIG" \
    -o "$OUT" \
    -DapiTests=false,modelTests=false,apiDocs=false,modelDocs=false

python3 -I "$CODEGEN_DIR/postprocess.py" "$OUT/tb_rest_client"
