#!/usr/bin/env bash
# mod_php pad sweep, inside one container. Restarts Apache per pad so each
# request meets a freshly forked child with a known heap, then reports the
# HTTP status, the second request, and whether Apache logged a dead child.
#   modscan.sh [memory_limit] [from_kb] [to_kb] [step_kb]
set -u
LIMIT="${1:-8M}"; FROM="${2:-200}"; TO="${3:-1400}"; STEP="${4:-100}"
cp /lab/target.php /var/www/html/target.php
{
  echo "memory_limit=$LIMIT"; echo "post_max_size=1G"; echo "upload_max_filesize=1G"
  echo "max_input_vars=10000000"; echo "max_file_uploads=1000000"
  echo "max_multipart_body_parts=10000000"; echo "max_input_time=-1"
  echo "display_errors=1"; echo "html_errors=0"; echo "log_errors=0"
} > /usr/local/etc/php/conf.d/zz-lab.ini

printf '%-6s %-7s %-9s %-30s %s\n' pad http worker r2 sig
for pad in $(seq "$FROM" "$STEP" "$TO"); do
  php /lab/mkbody.php padded_registration 6 "$pad" > /tmp/b || exit 90
  : > /tmp/apache.log
  apache2-foreground > /tmp/apache.log 2>&1 &
  AP=$!
  for _ in $(seq 1 60); do
    php -r '$f=@fsockopen("127.0.0.1",80,$e,$s,0.2); if($f){fclose($f);exit(0);} exit(1);' && break
    sleep 0.2
  done

  R1=$(php -n -d memory_limit=256M /lab/post.php --port 80 /tmp/b | tr '\n' ' ' | tr -s ' ')
  ST=$(printf '%s' "$R1" | sed -n 's/.*HTTP=\([0-9]*\).*/\1/p' | head -1)
  R2=$(php -n -d memory_limit=256M /lab/post.php --port 80 --get | tr '\n' ' ' | tr -s ' ' | cut -c1-30)

  SIG=$(grep -icE 'segmentation|signal|child process.*exit' /tmp/apache.log)
  if pgrep -f 'apache2' > /dev/null; then W=alive; else W=dead; fi

  printf '%-6s %-7s %-9s %-30s %s\n' "$pad" "${ST:-?}" "$W" "$R2" "$SIG"
  kill "$AP" 2>/dev/null; wait "$AP" 2>/dev/null
  pkill -f apache2 2>/dev/null; sleep 0.4
done
