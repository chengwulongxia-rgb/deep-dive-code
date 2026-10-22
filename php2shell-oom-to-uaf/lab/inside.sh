#!/usr/bin/env bash
# Everything runs INSIDE one container: body generation, the long-lived PHP
# worker, both requests, and the survival check. The host only does `docker run`.
#   inside.sh <shape> [size] [memory_limit]
set -u
SHAPE="${1:-huge_field_name}"; SIZE="${2:-6}"; LIMIT="${3:-8M}"
BODY=/tmp/body.bin

php /lab/mkbody.php "$SHAPE" "$SIZE" > "$BODY" || exit 90
echo "body=$(wc -c < "$BODY") bytes  shape=$SHAPE  memory_limit=$LIMIT"

php -d "memory_limit=$LIMIT" -d post_max_size=1G -d upload_max_filesize=1G \
    -d max_input_vars=10000000 -d max_file_uploads=1000000 \
    -d max_multipart_body_parts=10000000 -d max_input_time=-1 \
    -d html_errors=0 -d display_errors=1 -d log_errors=0 \
    -S 127.0.0.1:8080 -t /lab > /tmp/server.log 2>&1 &
SRV=$!

ready=0
for _ in $(seq 1 60); do
  if php -r '$f=@fsockopen("127.0.0.1",8080,$e,$s,0.2); if($f){fclose($f);exit(0);} exit(1);'; then
    ready=1; break
  fi
  sleep 0.2
done
[ "$ready" = 1 ] || { echo "SERVER_DID_NOT_START"; cat /tmp/server.log; exit 91; }

echo "--- baseline GET ---"
php -n -d memory_limit=256M /lab/post.php --get | tail -3

echo "--- request 1: POST $SHAPE ---"
php -n -d memory_limit=256M /lab/post.php "$BODY" | tail -5

echo "--- request 2: GET, same worker ---"
php -n -d memory_limit=256M /lab/post.php --get | tail -3

echo "--- worker state ---"
if kill -0 "$SRV" 2>/dev/null; then
  echo "worker=alive"
  kill "$SRV" 2>/dev/null
  wait "$SRV" 2>/dev/null
else
  wait "$SRV"; echo "worker=dead exit=$?"
fi

echo "--- server log tail ---"
tail -8 /tmp/server.log
