#!/bin/bash
# 전국 동물병원 채널 센서스 — 야간 자동 배치.
# 매 실행마다 미수집(체크포인트) 병원 CAP곳씩 이어서 수집한다.
# 사용: nightly.sh [CAP]   (기본 600)
set -u
PROJ="/Users/parkjungma/병원마케팅V2"
CAP="${1:-600}"
LOG="$PROJ/data/census_nightly.log"
LOCK="/tmp/petamos_census.lock"
PY="/usr/bin/python3"

cd "$PROJ" || { echo "$(date '+%F %T') PROJ 없음" >> "$LOG"; exit 1; }
mkdir -p "$PROJ/data"

# 중복 실행 방지(이전 배치가 아직 돌면 건너뜀)
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "$(date '+%F %T') 이전 배치 실행중 — 건너뜀" >> "$LOG"; exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

echo "===== $(date '+%F %T') 야간 배치 시작 (cap $CAP) =====" >> "$LOG"
"$PY" -m census.batch collect "$CAP" >> "$LOG" 2>&1
"$PY" -m census.batch stats 2>> "$LOG" | head -1 >> "$LOG"
echo "===== $(date '+%F %T') 종료 =====" >> "$LOG"
