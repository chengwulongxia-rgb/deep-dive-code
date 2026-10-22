#!/usr/bin/env bash
# Run one multipart OOM case against a pinned PHP image.
#   ./run_case.sh <image> <shape> [size] [memory_limit] [extra php-cgi -d args...]
# Body is generated on the host, streamed to php-cgi inside the container.
# The container has no network, a read-only lab mount, and is removed after.
set -uo pipefail
IMAGE="$1"; SHAPE="$2"; SIZE="${3:-6}"; LIMIT="${4:-8M}"; shift 4 2>/dev/null || shift $#
HERE="$(cd "$(dirname "$0")" && pwd)"
BODY="$(mktemp "${TMPDIR:-/tmp}/php2shell-body.XXXXXX")"
trap 'rm -f "$BODY"' EXIT
python3 "$HERE/mkbody.py" "$SHAPE" -o "$BODY" --size "$SIZE" >/dev/null || exit 90
BYTES=$(wc -c < "$BODY")
BOUNDARY='---------------------------12345'
docker run --rm -i --network none \
  --memory 512m --pids-limit 256 \
  -v "$HERE":/lab:ro \
  -e REDIRECT_STATUS=1 -e REQUEST_METHOD=POST \
  -e "CONTENT_TYPE=multipart/form-data; boundary=$BOUNDARY" \
  -e "CONTENT_LENGTH=$BYTES" -e SCRIPT_FILENAME=/lab/target.php \
  "$IMAGE" \
  php-cgi -C -n \
    -d "memory_limit=$LIMIT" -d post_max_size=1G -d upload_max_filesize=1G \
    -d max_input_vars=10000000 -d max_file_uploads=1000000 \
    -d max_multipart_body_parts=10000000 -d max_input_time=-1 \
    -d html_errors=0 -d display_errors=1 -d log_errors=0 \
    "$@" < "$BODY"
echo "EXIT=$?"
