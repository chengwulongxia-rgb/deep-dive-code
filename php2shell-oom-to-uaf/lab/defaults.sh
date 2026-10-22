#!/usr/bin/env bash
# Does a single POST that fits under the *stock* post_max_size (8M) still push
# the request parser past the *stock* memory_limit (128M)?
# Everything inside one container, mod_php, defaults only.
#   defaults.sh [part_count] [memory_limit] [post_max_size]
set -u
COUNT="${1:-85000}"; LIMIT="${2:-128M}"; PMS="${3:-8M}"
cp /lab/target.php /var/www/html/target.php
{
  echo "memory_limit=$LIMIT"; echo "post_max_size=$PMS"; echo "upload_max_filesize=2M"
  echo "display_errors=1"; echo "html_errors=0"; echo "log_errors=0"
} > /usr/local/etc/php/conf.d/zz-lab.ini

php /lab/mkbody.php many_parts "$COUNT" > /tmp/b || exit 90
BYTES=$(wc -c < /tmp/b)
printf 'parts=%s body=%s bytes (%.2f MiB)  post_max_size=%s  memory_limit=%s\n' \
  "$COUNT" "$BYTES" "$(echo "$BYTES" | awk '{print $1/1048576}')" "$PMS" "$LIMIT"

apache2-foreground > /tmp/apache.log 2>&1 &
AP=$!
for _ in $(seq 1 60); do
  php -r '$f=@fsockopen("127.0.0.1",80,$e,$s,0.2); if($f){fclose($f);exit(0);} exit(1);' && break
  sleep 0.2
done

R1=$(php -n -d memory_limit=256M /lab/post.php --port 80 /tmp/b | tr '\n' ' ' | tr -s ' ')
case "$R1" in
  *"Fatal error"*)                     V=OOM_BEFORE_USERLAND ;;
  *"exceeds the limit"*)               V=REJECTED_BY_POST_MAX_SIZE ;;
  *"post="*)                           V=REACHED_USERLAND ;;
  *)                                   V=OTHER ;;
esac
echo "verdict=$V"
echo "$R1" | cut -c1-200
grep -icE 'segmentation|signal' /tmp/apache.log | sed 's/^/segfault_lines=/'
kill "$AP" 2>/dev/null; wait "$AP" 2>/dev/null; pkill -f apache2 2>/dev/null
