# -*- coding: utf-8 -*-
"""센서스 집계 — 지역·규모별 채널 운영률/리뷰 분포(벤치마크용).

리포트의 '동종 평균/상위%'를 추정치가 아닌 실측으로 교체할 때 이 통계를 쓴다.
"""
import statistics

from . import db


def _median(vals):
    vals = [v for v in vals if v is not None]
    return int(statistics.median(vals)) if vals else 0


def by_region(conn, sido=None, level="sido", min_n=1):
    """지역별 채널 운영률 + 리뷰 중앙값. level='sido' 또는 'sigungu'."""
    col = "sigungu" if level == "sigungu" else "sido"
    where = "c.collect_status='ok'"
    params = []
    if sido:
        where += " AND h.sido=?"
        params.append(sido)
        col = "sigungu"
    rows = conn.execute(
        f"SELECT h.{col} AS region, c.homepage, c.blog, c.instagram, c.review_count"
        f" FROM channels c JOIN hospitals h ON h.id=c.hospital_id"
        f" WHERE {where}", params).fetchall()
    agg = {}
    for r in rows:
        g = agg.setdefault(r["region"] or "(미상)",
                           {"n": 0, "hp": 0, "bl": 0, "ig": 0, "rv": []})
        g["n"] += 1
        g["hp"] += r["homepage"] or 0
        g["bl"] += r["blog"] or 0
        g["ig"] += r["instagram"] or 0
        g["rv"].append(r["review_count"])
    out = []
    for region, g in sorted(agg.items(), key=lambda x: -x[1]["n"]):
        if g["n"] < min_n:
            continue
        out.append({"region": region, "n": g["n"],
                    "homepage": 100 * g["hp"] / g["n"],
                    "blog": 100 * g["bl"] / g["n"],
                    "instagram": 100 * g["ig"] / g["n"],
                    "review_median": _median(g["rv"])})
    return out


def benchmark(conn, sido=None):
    """단일 벤치마크(전국 또는 시도) — 리포트 배선용 요약."""
    r = by_region(conn, sido=sido, level="sido")
    if sido:
        rows = [x for x in r]  # sigungu breakdown
    tot = conn.execute(
        "SELECT c.homepage,c.blog,c.instagram,c.review_count FROM channels c"
        " JOIN hospitals h ON h.id=c.hospital_id WHERE c.collect_status='ok'"
        + (" AND h.sido=?" if sido else ""), ([sido] if sido else [])).fetchall()
    n = len(tot) or 1
    return {"scope": sido or "전국", "n": len(tot),
            "homepage_pct": round(100 * sum(x["homepage"] or 0 for x in tot) / n, 1),
            "blog_pct": round(100 * sum(x["blog"] or 0 for x in tot) / n, 1),
            "instagram_pct": round(100 * sum(x["instagram"] or 0 for x in tot) / n, 1),
            "review_median": _median([x["review_count"] for x in tot])}
