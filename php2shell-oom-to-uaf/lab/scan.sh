#!/usr/bin/env bash
# Pad sweep, entirely inside one container.
# Vary how full the heap is when the $_FILES registration allocation happens,
# then look for the vulnerable build diverging from the fixed one:
# worker death, a different exit code, or a corrupted second response.
#   scan.sh [memory_limit] [from_kb] [to_kb] [step_kb]
set -u
LIMIT="${1:-8M}"; FROM="${2:-200}"; TO="${3:-1400}"; STEP="${4:-50}"
PORT=8080
printf '%-6s %-8s %-9s %-34s %s\n' pad r1_kind worker r2 note
for pad in $(seq "$FROM" "$STEP" "$TO"); do
  PORT=$((PORT + 1))
  php /lab/mkbody.php padded_registration 6 "$pad" > /tmp/b || exit 90

  php -d "memory_limit=$LIMIT" -d post_max_size=1G -d upload_max_filesize=1G \
      -d max_input_vars=10000000 -d max_file_uploads=1000000 \
      -d max_multipart_body_parts=10000000 -d max_input_time=-1 \
      -d html_errors=0 -d display_errors=1 -d log_errors=0 \
      -S "127.0.0.1:$PORT" -t /lab > /tmp/s.log 2>&1 &
  SRV=$!

  for _ in $(seq 1 40); do
    php -r "\$f=@fsockopen('127.0.0.1',$PORT,\$e,\$s,0.2); if(\$f){fclose(\$f);exit(0);} exit(1);" && break
    sleep 0.1
  done

  R1=$(php -n -d memory_limit=256M /lab/post.php --port "$PORT" /tmp/b | tr '\n' ' ' | tr -s ' ')
  case "$R1" in
    *"Fatal error"*) K=oom ;;
    *"post=1"*)      K=ok_post1 ;;
    *"post=0"*)      K=ok_post0 ;;
    *)               K=other ;;
  esac
  R2=$(php -n -d memory_limit=256M /lab/post.php --port "$PORT" --get | tr '\n' ' ' | tr -s ' ')

  if kill -0 "$SRV" 2>/dev/null; then
    W=alive; kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
  else
    wait "$SRV"; W="dead:$?"
  fi

  printf '%-6s %-8s %-9s %-34s %s\n' "$pad" "$K" "$W" "${R2:0:34}" "${R1:0:44}"
done
