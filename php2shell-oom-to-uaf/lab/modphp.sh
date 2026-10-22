#!/usr/bin/env bash
# mod_php harness — everything inside one container.
# Apache + mod_php is where the advisory reports a validated exploit, and it is
# the only SAPI where the request parser runs before any application code.
#   modphp.sh <shape> [size] [memory_limit] [pad_kb]
set -u
SHAPE="${1:-huge_field_name}"; SIZE="${2:-6}"; LIMIT="${3:-8M}"; PAD="${4:-1344}"

php /lab/mkbody.php "$SHAPE" "$SIZE" "$PAD" > /tmp/b || exit 90
cp /lab/target.php /var/www/html/target.php
echo "body=$(wc -c < /tmp/b) bytes  shape=$SHAPE  memory_limit=$LIMIT  sapi=mod_php"

CONF=/usr/local/etc/php/conf.d/zz-lab.ini
{
  echo "memory_limit=$LIMIT"
  echo "post_max_size=1G"
  echo "upload_max_filesize=1G"
  echo "max_input_vars=10000000"
  echo "max_file_uploads=1000000"
  echo "max_multipart_body_parts=10000000"
  echo "max_input_time=-1"
  echo "display_errors=1"
  echo "html_errors=0"
  echo "log_errors=0"
} > "$CONF"

apache2-foreground > /tmp/apache.log 2>&1 &
AP=$!
for _ in $(seq 1 60); do
  php -r '$f=@fsockopen("127.0.0.1",80,$e,$s,0.2); if($f){fclose($f);exit(0);} exit(1);' && break
  sleep 0.2
done

echo "--- baseline GET ---"
php -n -d memory_limit=256M /lab/post.php --port 80 --get | tail -3

echo "--- request 1: POST $SHAPE ---"
R1=$(php -n -d memory_limit=256M /lab/post.php --port 80 /tmp/b); echo "$R1" | tail -5

echo "--- request 2: GET ---"
R2=$(php -n -d memory_limit=256M /lab/post.php --port 80 --get); echo "$R2" | tail -3

echo "--- apache children ---"
ps -eo pid,stat,comm | grep -E 'apache2|httpd' | head -6

echo "--- apache error log tail ---"
tail -6 /tmp/apache.log

kill "$AP" 2>/dev/null; wait "$AP" 2>/dev/null
