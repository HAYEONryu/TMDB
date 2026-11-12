#!/usr/bin/env bash
# Existing Ubuntu stack, with HTTPS isolation ALWAYS applied last.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ ! -f compose.server.yaml ]]; then
  echo '기존 서버의 compose.server.yaml이 필요합니다. 파일을 새 예시로 덮어쓰지 마세요.' >&2
  exit 2
fi
unset TM_SERVER_SECRET TM_DB_PASSWORD
exec docker compose -f compose.yaml -f compose.server.yaml -f compose.https.yaml --profile proxy "$@"
