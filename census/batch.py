# -*- coding: utf-8 -*-
"""전국 채널 센서스 배치 러너 (CLI).

  python3 -m census.batch seed "인천 남동구"      # 지역 명단 시드(카카오)
  python3 -m census.batch import roster.csv        # 행안부 CSV 명단 임포트
  python3 -m census.batch collect 50               # 미수집 50곳 채널 수집(이어하기)
  python3 -m census.batch collect 500 --sido 인천  # 특정 시도만
  python3 -m census.batch stats                    # 진행현황 + 지역 통계
  python3 -m census.batch stats --sido 인천

수집은 체크포인트(채널 없는 행만)라 몇 번을 돌리든 이어집니다. 사람 속도로 간격을 둡니다.
"""
import sys
import time

from . import db, collect, stats as stats_mod

GAP_SEC = 2.0          # 요청 간 간격(봇 감지 완화)


def cmd_seed(region):
    added, total = __import__("census.roster", fromlist=["seed_kakao"]).seed_kakao(region)
    print(f"[시드] '{region}' 카카오 검색 {total}곳 중 신규 {added}곳 추가")


def cmd_import(path):
    added, n = __import__("census.roster", fromlist=["import_mois_csv"]).import_mois_csv(path)
    print(f"[임포트] {path} — {n}행 중 신규 {added}곳 추가")


def cmd_collect(limit, sido=None):
    conn = db.connect()
    rows = db.pending_hospitals(conn, limit, sido=sido)
    print(f"[수집] 대상 {len(rows)}곳{' · '+sido if sido else ''} 시작", flush=True)
    ok = nf = err = 0
    for i, h in enumerate(rows, 1):
        ch = collect.collect_one(h["name"], h["address"] or "")
        db.save_channels(conn, h["id"], ch)
        st = ch.get("collect_status")
        ok += st == "ok"
        nf += st == "not_found"
        err += st == "error"
        flags = "".join(k[0].upper() for k in ("homepage", "blog", "instagram")
                        if ch.get(k))
        if i % 10 == 0 or i == len(rows):
            print(f"  {i}/{len(rows)} · ok{ok}/nf{nf}/err{err}", flush=True)
        time.sleep(GAP_SEC)
    conn.close()
    print(f"[수집 완료] ok {ok} · not_found {nf} · error {err}")


def cmd_stats(sido=None):
    conn = db.connect()
    p = db.progress(conn)
    print(f"[진행] 명단 {p['total']} · 수집 {p['done']} · 미발견 {p['not_found']} "
          f"· 에러 {p['error']} · 남음 {p['remaining']}")
    for r in stats_mod.by_region(conn, sido=sido):
        print(f"  {r['region']:12s} n={r['n']:4d} | 홈피 {r['homepage']:3.0f}% "
              f"블로그 {r['blog']:3.0f}% 인스타 {r['instagram']:3.0f}% "
              f"| 리뷰중앙값 {r['review_median']}")
    conn.close()


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd = argv[0]
    if cmd == "seed" and len(argv) > 1:
        cmd_seed(" ".join(argv[1:]))
    elif cmd == "import" and len(argv) > 1:
        cmd_import(argv[1])
    elif cmd == "collect":
        limit = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 50
        sido = argv[argv.index("--sido") + 1] if "--sido" in argv else None
        cmd_collect(limit, sido=sido)
    elif cmd == "stats":
        sido = argv[argv.index("--sido") + 1] if "--sido" in argv else None
        cmd_stats(sido=sido)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
