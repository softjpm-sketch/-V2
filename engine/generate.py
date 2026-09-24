# -*- coding: utf-8 -*-
"""
오케스트레이터 — 입력 JSON 1개 → 6개 리포트를 01~06 순서로 생성·정리.

사용법:
    python3 -m engine.generate inputs/<병원>.json
    python3 engine/generate.py inputs/<병원>.json

출력:
    outputs/<병원명>/01_<병원명>_상권분석.html ~ 06_<병원명>_12개월마케팅계획.html + index.html
"""
import json
import os
import re
import sys


def _detier_text(s, tier):
    """자기 병원 tier(N차)에 붙은 '급/수준' 같은 근접 표현 제거.
       이미 N차 병원이므로 'N차 병원급/수준'은 부정확 → 'N차 병원'으로 단정.
       (다른 등급, 예: 1차 병원이 '2차급'이라 칭찬받는 경우는 건드리지 않음)"""
    if not tier or not isinstance(s, str):
        return s
    t = re.escape(str(tier))
    s = re.sub(rf"{t}\s*차\s*병원\s*수준의", f"{tier}차 병원의", s)
    s = re.sub(rf"{t}\s*차\s*병원급으로", f"{tier}차 병원답게", s)
    s = re.sub(rf"{t}\s*차\s*병원\s*(?:급|수준)", f"{tier}차 병원", s)
    s = re.sub(rf"{t}\s*차\s*진료\s*급", f"{tier}차 진료", s)
    return s


def _walk_detier(obj, tier):
    if isinstance(obj, str):
        return _detier_text(obj, tier)
    if isinstance(obj, list):
        return [_walk_detier(x, tier) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk_detier(v, tier) for k, v in obj.items()}
    return obj

# 패키지/직접 실행 모두 지원
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from engine import scoring, policy, insights
    from engine.design import esc
    from engine.reports import (r01_trade_area, r02_competition, r03_marketing,
                                r04_review, r05_strengths, r06_plan, r07_emr)
else:
    from . import scoring, policy, insights
    from .design import esc
    from .reports import (r01_trade_area, r02_competition, r03_marketing,
                          r04_review, r05_strengths, r06_plan, r07_emr)

# 리포트 순서 고정: 01 상권 → 02 경쟁 → 03 마케팅 → 04 리뷰 → 05 강점 → 06 12개월계획
REPORTS = [
    ("01", "상권분석", r01_trade_area),
    ("02", "경쟁분석", r02_competition),
    ("03", "마케팅", r03_marketing),
    ("04", "리뷰분석", r04_review),
    ("05", "강점", r05_strengths),
    ("06", "12개월마케팅계획", r06_plan),
]
# 07 진료데이터분석: EMR 업로드가 있을 때만 추가되는 내부 데이터축(방법론 §8)
EMR_REPORT = ("07", "진료데이터분석", r07_emr)


def _reports_for(data):
    """data에 emr가 있으면 07을 포함한 리포트 목록."""
    return list(REPORTS) + ([EMR_REPORT] if data.get("emr") else [])


def make_filenames(name, data=None):
    reps = _reports_for(data) if data is not None else REPORTS
    return {no: f"{no}_{name}_{label}.html" for no, label, _ in reps}


def build_index(data, ctx, results):
    clinic = data["clinic"]
    t = ctx["trade"]; k = ctx["comp"]; ov = ctx["overall"]
    from .design import CSS  # 재사용
    # 진단축 종합 등급 배너
    grade_banner = ""
    if ov["score100"] is not None:
        axis_chips = " · ".join(f"{esc(lab)} {s}" for lab, s in ov["axes"] if s is not None)
        grade_banner = (
            f'<div class="callout g" style="margin:18px 0;display:flex;align-items:center;gap:14px">'
            f'<b style="font-size:26px">{esc(ov["grade"])}등급</b>'
            f'<span>진단축 종합 <b>{ov["score100"]}/100</b> (충실도 {ov["coverage"]}%) · {axis_chips}'
            f'<br><span style="font-size:12px;color:#5b6675">A≥80 · B≥65 · C≥50 · D&lt;50 (상권·경쟁·마케팅·리뷰 평균, 강점은 제언)</span></span></div>')
    # 리포트별 한 줄 요약(대시보드)
    rv_chs = data.get("review", {}).get("channels", [])
    tot_rv = sum((c.get("review_count") or 0) for c in rv_chs)
    mk_ch = [c for c in data.get("marketing", {}).get("channels", []) if c.get("score") is not None]
    avg_ch = round(sum(c["score"] for c in mk_ch) / len(mk_ch)) if mk_ch else None
    n_axes = len(insights.derive_strengths(data, ctx))
    summ = {
        "01": f"시장 포화도 {t['saturation']:,} · {t['grade']}등급" if t.get("saturation") else "상권 진단",
        "02": f"동급 {k['rival_count']}곳 · 의뢰처 {k['referral_count']}곳 · 포지션 {k['co_density']}점",
        "03": f"채널 {len(data.get('marketing',{}).get('channels',[]))}개 · 평균 {avg_ch}점" if avg_ch is not None else "온라인 8채널 진단",
        "04": f"리뷰 {tot_rv:,}개 분석" if tot_rv else "리뷰 평판 분석",
        "05": f"강점 축 {n_axes}개 통합",
        "06": "9월 시작 12개월 로드맵",
    }
    if data.get("emr"):
        an = data["emr"].get("analysis", {})
        rev = an.get("revisit", {})
        dorm = an.get("dormant", {})
        if an.get("error"):
            summ["07"] = "진료데이터 분석(입력 확인 필요)"
        else:
            bits = [f"방문 {an.get('total_visits',0):,}"]
            if rev.get("revisit_rate") is not None:
                bits.append(f"재진율 {rev['revisit_rate']*100:.0f}%")
            if dorm.get("recall_target"):
                bits.append(f"휴면 {dorm['recall_target']}명")
            summ["07"] = " · ".join(bits) + " · 🔒익명화"
    cards = []
    for no, label, _ in _reports_for(data):
        fn = ctx["filenames"][no]
        cards.append(
            f'<a class="rcard" href="{esc(fn)}">'
            f'<div class="rno">{no}</div>'
            f'<div style="flex:1"><h3>{esc(label)}</h3>'
            f'<p style="color:var(--navy);font-weight:600;font-size:13px">{esc(summ.get(no,""))}</p></div>'
            f'<span class="hint" style="align-self:center">열기 →</span></a>')
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(clinic['name'])} 마케팅 진단 리포트</title>
<style>{CSS}
.rcard{{display:flex;gap:16px;align-items:center;text-decoration:none;color:inherit;
  background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 22px;
  box-shadow:var(--shadow);margin:10px 0;transition:.15s}}
.rcard:hover{{border-color:var(--blue);transform:translateY(-1px)}}
.rno{{flex:0 0 auto;width:46px;height:46px;border-radius:11px;background:var(--navy);color:#fff;
  font-weight:800;font-size:18px;display:flex;align-items:center;justify-content:center}}
.rcard h3{{margin:0;font-size:16px}}.rcard p{{margin:2px 0 0;font-size:12px;color:var(--muted)}}
</style></head><body>
<div class="printbar"><button onclick="window.print()">🖨 요약 PDF</button></div>
<header class="hero" style="background:{'linear-gradient(135deg,#152B54,#20406f)'}"><div class="wrap">
  <div class="kicker">{esc(policy.TOOL_LABEL)}</div>
  <h1>{esc(clinic['name'])} 마케팅 진단 리포트</h1>
  <p class="sub">{len(_reports_for(data))}개 리포트{' (+진료데이터분석)' if data.get('emr') else ''} · {esc(clinic.get('date',''))}</p>
  <div class="meta"><span>상권 {esc(t['grade'] or '–')}등급</span>
    <span>경쟁 {k['co_density']}점</span>
    <span>{esc(clinic.get('address',''))}</span></div>
</div></header>
<main class="wrap">
  {grade_banner}
  <div class="callout g" style="margin:18px 0">아래 순서대로 읽으면 진단 → 강점 → 실행이 한 흐름으로 이어집니다.</div>
  {''.join(cards)}
</main>
<footer class="wrap"><p class="fn">· {esc(policy.DISCLAIMER_GENERIC)}</p></footer>
</body></html>"""


def run(input_path):
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    clinic = data["clinic"]
    name = clinic.get("slug") or clinic["name"]

    # 진료 특화: 마케팅에서 자동 추출된 특화가 있으면 05 강점 '진료 역량' 축 재료로 채움
    #   (수동 입력 clinic.specialties 우선; 없을 때만 자동)
    _spec = data.get("marketing", {}).get("specialty_analysis", {})
    if _spec.get("specialties") and not clinic.get("specialties"):
        clinic["specialties"] = [
            {"title": s.get("name", ""), "body": s.get("evidence", ""), "emphasis": s.get("emphasis", "")}
            for s in _spec["specialties"] if s.get("name")]

    # 자기 병원 등급 표현 정리: 'N차 병원급/수준' → 'N차 병원'(자기 tier 한정)
    #   자기 분석축(마케팅·리뷰·강점)에만 적용. 경쟁사 서술의 '급'은 의도적일 수 있어 제외.
    _tier = clinic.get("tier")
    for _k in ("marketing", "review", "strengths"):
        if data.get(_k):
            data[_k] = _walk_detier(data[_k], _tier)

    # 입력 정규화: 리뷰 수/별점 불명(null)을 안전값으로 (AI 초안이 null을 낼 수 있음)
    for c in data.get("review", {}).get("channels", []):
        if c.get("review_count") is None:
            c["review_count"] = 0
        if c.get("rating") is None:
            c.pop("rating", None)

    # 경쟁 상대 포지션 비교용 자병원 리뷰수 = 네이버 플레이스 기준(경쟁사와 기준 통일)
    #   구글 등 다른 채널은 04 리뷰 리포트의 감성·키워드 '분석'에만 쓰고 비교엔 넣지 않음.
    subject_reviews = scoring.subject_place_reviews(data.get("review", {}), data.get("marketing", {}))

    # 경쟁사 리뷰수·별점(경쟁사 마케팅 현황/캡처 판독)을 clinics에 병합 → 상대 포지션·리뷰비교
    comp_in = data.get("competition", {})
    rm_rev = {scoring._norm_name(r.get("name", "")): r.get("place_review")
              for r in comp_in.get("rival_marketing", []) if r.get("place_review")}
    rm_rat = {scoring._norm_name(r.get("name", "")): r.get("place_rating")
              for r in comp_in.get("rival_marketing", []) if r.get("place_rating")}
    if rm_rev or rm_rat:
        for c in comp_in.get("clinics", []):
            cn = scoring._norm_name(c.get("name", ""))
            if c.get("review_count") is None and rm_rev.get(cn):
                c["review_count"] = rm_rev[cn]
            if c.get("rating") is None and rm_rat.get(cn):
                c["rating"] = rm_rat[cn]

    # 공용 계산 1회 (01·02·05·06이 공유)
    ctx = {
        "trade": scoring.analyze_trade_area(data.get("trade_area", {})),
        "comp": scoring.analyze_competition(comp_in, clinic,
                                            subject_reviews=subject_reviews),
        "filenames": make_filenames(name, data),
    }
    ctx["overall"] = scoring.overall_grade(ctx["trade"], ctx["comp"], data)
    # 경쟁사 마케팅 분석(02): 채널 3-state·상권 온라인 성숙도·tier별 전략
    ctx["comp_mk"] = scoring.analyze_competition_marketing(
        data.get("competition", {}), clinic, ctx["comp"],
        subject_marketing=data.get("marketing"))

    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", name)
    os.makedirs(out_dir, exist_ok=True)

    results = {}
    for no, label, mod in _reports_for(data):
        html = mod.build(data, ctx)
        fn = ctx["filenames"][no]
        with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as f:
            f.write(html)
        results[no] = fn
        print(f"  ✓ {fn}")

    # index
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_index(data, ctx, results))
    print(f"  ✓ index.html")

    # 콘솔 요약
    t = ctx["trade"]; k = ctx["comp"]
    print(f"\n[요약] {name}")
    print(f"  상권: 포화도 {t['saturation']} · {t['grade']}등급 · 축 {t['axis_score']}/20(충실도 {t['coverage']}%)")
    print(f"  경쟁: 동급 {k['rival_count']}곳 · 의뢰처 {k['referral_count']}곳 · 최근접 {k['nearest_m']}m · "
          f"축 {k['axis_score']}/20(충실도 {k['coverage']}%) · co_density {k['co_density']}")
    ov = ctx["overall"]
    if ov["score100"] is not None:
        print(f"  종합: {ov['grade']}등급 {ov['score100']}/100 (충실도 {ov['coverage']}%)")
    print(f"  출력: outputs/{name}/  (6개 + index.html)")
    return out_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python3 -m engine.generate inputs/<병원>.json")
        sys.exit(1)
    print(f"■ 리포트 생성: {sys.argv[1]}")
    run(sys.argv[1])
