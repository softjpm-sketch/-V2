# -*- coding: utf-8 -*-
"""02 경쟁분석 — 방법론 §2 / 프롬프트 B안 경쟁 규칙."""
from .. import components as C
from .. import policy
from .. import scoring
from ..design import page, esc, HERO_NAVY

REPORT_NO = "02"
REPORT_LABEL = "경쟁분석"


def _rival_rows(rivals, limit=5):
    rows = []
    for r in rivals[:limit]:
        rows.append([esc(r["name"]), esc(r["category"] or "동물병원"),
                     f"{r['distance_m']:,}m"])
    if len(rivals) > limit:
        rows.append([f"외 {len(rivals)-limit}곳", "", ""])
    return rows


def _marketing_sections(data, ctx, is2, start_n):
    """경쟁사 분석 결과 — 어떻게 분석했나·우리 vs 경쟁사 차이·벤치마킹·강점 부각 + tier 전략."""
    from collections import Counter
    mk = ctx.get("comp_mk", {})
    clinic = data["clinic"]
    tier = mk.get("tier", 2)
    comp = data.get("competition", {})
    rms = comp.get("rival_marketing", [])
    mtx = mk.get("matrix", {})
    out = []
    n = start_n
    if not mk.get("has_data") and not mtx.get("rows"):
        out.append(C.section(str(n), "경쟁사 분석 결과",
            C.info("경쟁사 <b>홈페이지·인스타 URL</b>이나 <b>플레이스·블로그·리뷰 화면</b>을 입력하면(② 경쟁의 '경쟁사 마케팅 현황 → 🔎 실제 분석 자동화'), "
                   "채널 운영·리뷰·특화·강약점을 자동 분석해 우리와의 차이·벤치마킹·강점 부각 방법을 정리합니다.")))
        return out, n + 1

    # ── 우리 데이터 ──
    subj_row = next((r for r in mk.get("ranking", []) if r.get("is_subject")), None)
    our_active = set(subj_row["active"]) if subj_row else set()
    _our_place = scoring.subject_place_reviews(data.get("review", {}), data.get("marketing", {}))  # 리뷰수 = 네이버 플레이스
    our_reviews = _our_place["review_count"] if _our_place else None

    inner = ('<p class="lead">카카오 반경 수집 + 경쟁사 <b>홈피·인스타 URL 자동수집</b> + '
             '<b>플레이스·블로그·리뷰 화면 판독(AI 비전)</b>으로 경쟁사를 실제 분석한 결과입니다.</p>')

    # 상권 온라인 성숙도
    mat = mk.get("maturity", {})
    if mat.get("score") is not None:
        g = mat["grade"]
        interp = {"낮음": "경쟁사 상당수가 온라인을 안 합니다 — <b>선점 기회</b>가 큽니다.",
                  "보통": "경쟁사 절반 정도만 온라인을 합니다 — 지금이 <b>치고 나갈 타이밍</b>입니다.",
                  "높음": "경쟁사 온라인이 활발합니다 — <b>차별화</b>가 없으면 묻힙니다."}.get(g, "")
        inner += C.callout(f"<b>상권 온라인 성숙도 {mat['score']}점 · {esc(g)}</b> — {interp}", good=(g == "낮음"))

    # 자동 분석 내역(실제로 수집·판독된 것 — 확인용)
    analyzed = [r for r in rms if r.get("_analyzed")]
    if analyzed:
        al = ('<div class="info"><b>🔎 자동 분석 내역</b> — URL 자동수집·화면 판독으로 실제 실행된 것:'
              '<ul style="margin:6px 0 0;padding-left:18px;font-size:12.5px;line-height:1.7">')
        for r in analyzed:
            al += f'<li><b>{esc(r.get("name",""))}</b>: ' + " · ".join(esc(x) for x in r["_analyzed"]) + '</li>'
        al += '</ul></div>'
        inner += al

    # ── ① 우리 vs 경쟁사 — 무엇이 다른가 ──
    inner += '<h4 style="margin:18px 0 6px;font-size:15px;color:var(--navy)">① 우리 vs 경쟁사 — 무엇이 다른가</h4>'
    if mk.get("channels"):
        crows = []
        for ch in mk["channels"]:
            we = "🟢 운영" if ch["label"] in our_active else "⚪ 미운영"
            crows.append([f"<b>{esc(ch['label'])}</b>", we,
                          f"{ch['active']}곳" if ch['active'] else "–",
                          f"{ch['absent']}곳" if ch['absent'] else "–"])
        inner += ("<b>채널 운영 비교</b>"
                  + C.table(["채널", "우리", "경쟁사 운영", "경쟁사 없음(확인)"], crows))
    # 순위는 '운영강도'(외부 탐지 비대칭으로 왜곡) 대신 검증 가능한 플레이스 리뷰수 기준.
    rk = mk.get("ranking", [])
    if rk:
        for row in rk:                          # 본 병원 리뷰수 채우기(검증 가능한 값)
            if row.get("is_subject") and not row.get("place_review") and our_reviews:
                row["place_review"] = our_reviews
        rk_sorted = sorted(rk, key=lambda r: (r.get("place_review") or 0), reverse=True)
        if any(r.get("place_review") for r in rk_sorted):
            rrows = []
            for i, row in enumerate(rk_sorted):
                nm = esc(row["name"]) + (' <span class="win">본 병원</span>' if row["is_subject"] else "")
                ch = (esc("/".join(row["active"])) if row.get("active")
                      else '<span style="color:#8a94a3">확인된 채널 없음</span>')
                rv = row.get("place_review")
                rrows.append([f"{i+1}", nm, f"{rv:,}" if rv else "–", ch])
            inner += ('<h4 style="margin:14px 0 6px;font-size:14px;color:var(--navy)">'
                      '플레이스 리뷰 비교 · 확인된 운영 채널</h4>'
                      '<p class="hint" style="margin:0 0 6px">순위는 검증 가능한 네이버 플레이스 '
                      '리뷰수 기준입니다. 운영 채널은 실제로 접속해 병원명이 확인된 것만 표기합니다.</p>'
                      + C.table(["순위", "병원", "플레이스 리뷰", "확인된 운영 채널"], rrows, num_cols={0, 2}))
    # 특화 비교(포지셔닝 맵 — 빈자리 프레임 제거, '차이' 관점)
    if mtx.get("rows"):
        specs = mtx["specialties"]
        rows = []
        for r in mtx["rows"]:
            cells = [esc(r["name"] or "(무명)")]
            for s in specs:
                if s in r.get("confirmed", set()):
                    cells.append('<b style="color:var(--good)">✓</b>')
                elif s in r.get("estimated", set()):
                    cells.append('<span style="color:var(--warn)">~</span>')
                else:
                    cells.append('<span style="color:#c9d2de">·</span>')
            rows.append(cells)
        inner += ('<h4 style="margin:14px 0 6px;font-size:14px;color:var(--navy)">경쟁사 특화(진료과목) 비교</h4>'
                  '<p class="hint" style="margin:0 0 6px">✓ 확인(직접 입력·홈피/화면 판독) · ~ 추정(명칭) · · 없음</p>'
                  '<div style="overflow-x:auto">' + C.table(["경쟁사"] + specs, rows) + '</div>')

    # 경쟁사 인스타 현황(URL OG 메타 또는 캡처 판독)
    insta_rows = [r for r in rms if r.get("insta_followers") or r.get("insta_posts")]
    if insta_rows:
        irows = [[esc(r.get("name", "")),
                  f"{r['insta_followers']:,}" if r.get("insta_followers") else "–",
                  f"{r['insta_posts']:,}" if r.get("insta_posts") else "–"] for r in insta_rows]
        inner += ('<h4 style="margin:14px 0 6px;font-size:14px;color:var(--navy)">경쟁사 인스타 현황</h4>'
                  + C.table(["경쟁사", "팔로워", "게시물"], irows, num_cols={1, 2}))

    # ── ② 벤치마킹하면 좋은 점 (경쟁사에게 배울 것) ──
    bench = []
    for ch in mk.get("channels", []):
        if ch["active"] >= 1 and ch["label"] not in our_active:
            bench.append((f"경쟁사가 하는 {ch['label']} — 우리는 아직",
                          f"경쟁사 {ch['active']}곳이 {ch['label']}을(를) 운영합니다. 이미 검증된 채널이니 우리도 도입해 격차를 좁히는 것이 좋습니다."))
    all_praise = [w for r in rms for w in (r.get("praise") or [])]
    if all_praise:
        top_praise = [w for w, _ in Counter(all_praise).most_common(5)]
        bench.append(("경쟁사 칭찬 = 시장이 원하는 경험",
                      f"경쟁사 리뷰에서 반복되는 칭찬: <b>{esc(', '.join(top_praise[:4]))}</b>. "
                      "이건 지역 보호자가 중요하게 보는 지점 — 우리도 이 경험을 강화하고 콘텐츠·리뷰로 드러내면 좋습니다."))
    max_rv_rival = max(((r.get("place_review") or 0) for r in rms), default=0)
    if max_rv_rival and our_reviews and max_rv_rival > our_reviews * 1.5:
        bench.append(("경쟁사 리뷰 볼륨 벤치마킹 (네이버 플레이스 기준)",
                      f"네이버 플레이스 리뷰가 가장 많은 경쟁사는 {max_rv_rival:,}개로 우리({our_reviews:,}개)보다 훨씬 많습니다. "
                      "리뷰 요청 자동화·후기 이벤트로 리뷰 수를 끌어올리는 것이 검색·신뢰에 직결됩니다."))
    elif max_rv_rival and our_reviews is None:
        bench.append(("네이버 플레이스 리뷰수를 넣으면 정확 비교",
                      f"경쟁사는 네이버 플레이스 리뷰 최다 {max_rv_rival:,}개입니다. 우리 <b>네이버 플레이스 리뷰수</b>를 입력하면 "
                      "같은 기준으로 정확히 비교됩니다(구글 등 다른 채널은 감성·키워드 분석에만 사용)."))
    if bench:
        inner += ('<h4 style="margin:20px 0 6px;font-size:15px;color:var(--navy)">② 벤치마킹하면 좋은 점 — 경쟁사에게 배울 것</h4>'
                  + "".join(C.finding(t, b, "w", src="경쟁") for t, b in bench))

    # ── ③ 우리 강점 부각 방법 ──
    boost = []
    comp_complaints = [w for r in rms for w in (r.get("complaint") or [])]
    if comp_complaints:
        common = [w for w, c in Counter(comp_complaints).most_common(4)]
        boost.append(("경쟁사 불만을 뒤집는 역공략 메시지",
                      f"경쟁사 리뷰의 불만: <b>{esc(', '.join(common[:4]))}</b>. "
                      "우리는 이 반대편(예: ‘과잉진료 없는 꼭 필요한 진료’·‘투명한 비용 안내’·‘친절한 응대’)을 "
                      "플레이스 소개·광고 문구·리뷰 답글에 전면화해 차별화할 수 있습니다."))
    only_us = [ch["label"] for ch in mk.get("channels", []) if ch["label"] in our_active and ch["active"] == 0]
    if only_us:
        boost.append(("경쟁사가 약한 채널에서 앞서가기",
                      f"우리는 운영하는데 경쟁사 대부분이 안 하는 채널: <b>{esc(', '.join(only_us))}</b>. "
                      "이 채널을 더 키우면 온라인 노출에서 확실한 우위를 굳힐 수 있습니다."))
    conf_specs = mtx.get("confirmed", []) + mtx.get("estimated", [])
    open_specs = mtx.get("open", [])
    my_specs = clinic.get("specialties_short") or []
    my_open = [s for s in my_specs if s in open_specs] if my_specs else []
    if my_open:
        boost.append(("경쟁사가 비운 특화를 선점",
                      f"우리 특화 중 경쟁사가 안 내세우는 진료: <b>{esc(', '.join(my_open))}</b>. "
                      "‘○○ 특화’로 포지셔닝하면 무경쟁 영역을 선점할 수 있습니다."))
    elif open_specs:
        boost.append(("비어 있는 특화 = 선점 후보",
                      f"경쟁사 3곳이 내세우지 않는 진료: <b>{esc(', '.join(open_specs[:4]))}</b>. "
                      "우리가 실제 강한 진료가 여기 있으면 전면에 세워 차별화하세요."))
    if boost:
        inner += ('<h4 style="margin:20px 0 6px;font-size:15px;color:var(--navy)">③ 우리 강점 부각 방법</h4>'
                  + "".join(C.finding(t, b, "g", src="경쟁") for t, b in boost))

    # ── 근거: 경쟁사 리뷰 키워드(캡처 판독) ──
    rms_kw = [r for r in rms if r.get("praise") or r.get("complaint")]
    if rms_kw:
        kh = ('<h4 style="margin:20px 0 6px;font-size:14px;color:var(--navy)">근거 — 경쟁사 리뷰 키워드 '
              '<span class="hint">(화면 판독)</span></h4>')
        for r in rms_kw:
            kh += f'<div class="card" style="margin:8px 0"><b>{esc(r.get("name",""))}</b>'
            if r.get("praise"):
                kh += '<div style="margin-top:5px;font-size:12px;color:var(--muted)">칭찬</div>' + C.keywords(r["praise"])
            if r.get("complaint"):
                kh += '<div style="margin-top:5px;font-size:12px;color:var(--muted)">불만</div>' + C.keywords(r["complaint"], neg=True)
            kh += '</div>'
        inner += kh

    out.append(C.section(str(n), "경쟁사 분석 결과", inner))
    n += 1

    # ── tier별 전략 제언 ──
    strat = mk.get("strategy", {})
    if strat:
        badge = "1차 · 저비용 선점 관점" if tier == 1 else "2차 · 전문성 차별화 관점"
        si = C.callout(f"<b>[{esc(badge)}]</b> {strat['headline']}",
                       good=(strat.get("maturity_grade") == "낮음"))
        acts = [{"title": a, "effort": 2, "impact": 3, "cost": 1} for a in strat.get("actions", [])]
        if acts:
            si += C.actions_to_roadmap(acts)
        out.append(C.section(str(n), "경쟁사 대비 마케팅 전략", si))
        n += 1

    return out, n


def build(data, ctx):
    clinic = data["clinic"]
    k = ctx["comp"]
    is2 = (k["subject_tier"] == 2)
    body = []

    # ── 공용 데이터(참조 워딩 자동생성용) ──
    nm_ = clinic["name"]
    _last = nm_[-1] if nm_ else ""
    nj = "은" if ("가" <= _last <= "힣" and (ord(_last) - 0xAC00) % 28) else "는"  # 받침→은/는
    radius_km = round(k["radius_m"] / 1000)
    rc, rf = k["rival_count"], k["referral_count"]
    total = rc + rf
    near, far = k["band"]["near"], k["band"]["far"]
    nearest = k["nearest_m"]
    cod, base, bonus = k["co_density"], k["base"], k["bonus"]
    rel = k.get("rel", {}); rel_score = rel.get("score")
    # 우리 네이버 플레이스 리뷰수 vs 경쟁사 최다(상대 포지션 서술용)
    _op = scoring.subject_place_reviews(data.get("review", {}), data.get("marketing", {}))
    our_reviews = _op["review_count"] if _op else None
    max_rv_rival = max((r.get("place_review", 0) or 0 for r in data.get("competition", {}).get("rival_marketing", [])),
                       default=0)
    prof = k.get("profile", {}); h24 = prof.get("h24", 0)
    gap = k.get("gap", {})
    rivals, refs = k["rivals"], k["referrals"]
    loose = cod >= 80
    ref_names = "·".join(r["name"] for r in refs[:3]) if refs else ""
    riv0 = rivals[0]["name"] if rivals else "가장 가까운 경쟁"
    spec_hint = ", ".join((clinic.get("specialties_short") or [])[:2]) or "영상진단(CT·MRI)·중환자 집중치료 등 전문 진료"

    # 카카오 자동수집 안내(있을 때)
    cl = data.get("competition", {}).get("_collect")
    if cl:
        cap = " · 반경 내 병원이 많아 가까운 45곳까지만 수집됨" if cl.get("capped") else ""
        body.append(C.info(
            f"🗺️ <b>카카오 자동수집</b> — 반경 {cl.get('radius_m'):,}m 내 동물병원 "
            f"<b>{cl.get('total')}곳</b>을 자동 수집·분류했습니다{cap}."))

    # ① 경쟁 스냅샷
    snap_lead = (f'<p class="lead">반경 {radius_km}km 내 동물병원 {total}곳을 <b>동급 경쟁</b>과 '
                 f'<b>의뢰처</b>로 나눠 파악한 경쟁 지형입니다. (자기 병원은 제외)</p>' if is2 else
                 f'<p class="lead">반경 {radius_km}km 내 동급 동물병원 {rc}곳을 파악한 경쟁 지형입니다. (자기 병원은 제외)</p>')
    snap = C.snap([
        (f"{rc}곳", "동급 경쟁(2차)" if is2 else "동급 경쟁(1차)"),
        (f"{rf}곳", "의뢰처(1차)" if is2 else "인근 2차"),
        (f"{nearest:,}m" if nearest else "–", "최근접 동급"),
        (f"{cod}점", "경쟁 포지션"),
    ])
    if is2:
        core = (f'핵심 한 줄: {esc(nm_)}{nj} <b>2차 병원</b>이라, 주변 1차 병원은 경쟁이 아니라 '
                f'환자를 보내주는 <b>의뢰처(유입원)</b>입니다. 동급 2차 경쟁은 {rc}곳뿐이고 '
                f'코앞(≤300m)엔 {near}곳 — 경쟁은 {"느슨" if far >= rc * 0.6 else "존재"}하고 '
                f'의뢰처는 {rf}곳으로 풍부한, <b>{"매우 유리한" if loose else "양호한"} 포지션</b>입니다.')
    else:
        core = (f'핵심 한 줄: {esc(nm_)}{nj} <b>1차(동네 병원)</b>이라 주변 동급 1차가 직접 경쟁입니다. '
                f'반경 {radius_km}km 내 동급 {rc}곳, 최근접 {nearest or "–"}m — '
                f'{"근거리 경쟁이 여유로운" if loose else "국지 경쟁이 있는"} 포지션입니다.')
    body.append(C.section("1", "경쟁 스냅샷", snap_lead + snap + C.callout(core, good=loose)))

    # ② (2차) 개념 + 흐름도
    if is2:
        concept = C.info(
            "<b>1차·2차 구조</b> — 동네 병원(1차)이 고난도 케이스(CT·MRI·중환자·전문수술)를 "
            "2차 전문센터로 <b>의뢰(refer)</b>하고 치료 후 회송합니다. "
            "대상이 <b>2차</b>이면 주변 <b>2차 = 직접 경쟁</b>, 주변 <b>1차 = 의뢰처(유입원)</b>로 "
            "많을수록 기회(가점)입니다.")
        concept += C.table(["역할", "대상 병원 관점", "본 병원 반경 내"],
                           [["동급 2차", "직접 경쟁", f"{rc}곳"],
                            ["1차 병원", "의뢰처(환자 유입)", f"{rf}곳 (가점 +{bonus})"]])
        concept += C.info(
            f"경쟁 포지션 점수(<b>{cod}점</b>) = 근거리 경쟁 여유({base}) + 의뢰처 유입 보너스(+{bonus}). "
            "가까운 경쟁일수록 크게, 먼 경쟁은 작게 반영합니다.")
        body.append(C.section("2", "먼저 이해하기 — 1차·2차와 '경쟁 vs 의뢰처'", concept))

    # ③ 한눈에 보는 종합 진단
    n = "3" if is2 else "2"
    axis_txt = (f"경쟁 종합 <b>{k['axis_score']} / 20</b> · 충실도 {k['coverage']}%"
                if k["axis_score"] is not None else "측정 데이터 부족")
    diag = f'<p class="lead">경쟁 축(20점 만점)을 항목별로 평가했습니다. {axis_txt}.</p>'
    # 점수 막대(벤치 대비 리치 노트)
    pressure_txt = "경쟁 압력 낮음" if far >= max(1, rc * 0.6) else "경쟁 압력 존재"
    disp = []
    for m in k["metrics"]:
        key, note = m["key"], m.get("note", "")
        if key == "co_density":
            note = f"동급 {'2차 ' if is2 else ''}{rc}곳 · 최근접 {nearest or '–'}m · 300m 이내 {near}곳 ({pressure_txt})"
        elif key == "co_rel_position" and rel_score is not None:
            tier = "상위권" if rel_score >= 80 else ("중위권" if rel_score >= 45 else "하위권")
            note = f"네이버 플레이스 리뷰 수 기준 경쟁사 대비 {tier}"
            if our_reviews and max_rv_rival:
                note += f" — 우리 {our_reviews:,}개 vs 최다 경쟁사 {max_rv_rival:,}개"
            elif our_reviews:
                note += f" — 우리 {our_reviews:,}개"
        elif key == "co_gap_specialty":
            if gap.get("open"):
                note = f"빈자리(기회): {', '.join(gap['open'][:4])} 등 — 동급이 안 내세우는 특화"
            elif gap.get("covered"):
                note = f"동급 다수가 {', '.join(gap['covered'][:3])} 계열 — 차별 특화 필요"
        elif key == "co_profile":
            note = f"강한 경쟁 {prof.get('strong',0)}/{rc}곳 · 24시·응급 {h24}곳"
        disp.append({**m, "note": note})
    diag += C.scoregrid(disp)
    if is2:
        diag += C.callout(
            f"<b>경쟁 포지션 종합 {cod}점</b> = 근거리 경쟁 여유 {base} + 의뢰처 유입 보너스 {bonus}.",
            good=loose)
    diag += C.info(
        f"<b>거리별 경쟁</b> — 300m 이내 <b>{near}</b>곳 · 300~600m <b>{k['band']['mid']}</b>곳 · "
        f"600m 밖 <b>{far}</b>곳. 가까운 경쟁일수록 위협이 크게, 먼 경쟁은 작게 반영합니다.")
    body.append(C.section(n, "한눈에 보는 종합 진단", diag))

    # ④ 어떻게 분석했나 — 방법 (참조 순서: 주변 지형보다 앞)
    cl = data.get("competition", {}).get("_collect")
    scan = (f"카카오 로컬로 반경 {cl['radius_m']:,}m 내 동물병원 {cl['total']}곳을 자동 수집했습니다."
            if cl else f"반경 {k['radius_m']:,}m 내 동물병원 목록을 수집했습니다.")
    n = "4" if is2 else "3"
    body.append(C.section(n, "어떻게 분석했나 — 방법",
        '<p class="lead">카카오 로컬 검색으로 반경 내 병원을 모아, 자동 분류·거리 가중·리뷰 비교로 판단했습니다.</p>'
        + C.method_cards([
            ("① 반경 스캔 (tier별 자동)",
             (f"2차 병원은 리퍼 기반이라 진료권이 넓어 반경 3km로 스캔(1차는 1km). 동물병원 {total}곳을 집계했습니다."
              if is2 else f"1차는 반경 1km로 스캔. 반경 내 동물병원 {total}곳을 집계했습니다.")),
            ("② 1·2차 자동 분류",
             "병원명 신호(24시·응급·메디컬센터·의료원·종합·대학)로 2차를 판정. "
             + ("동급(2차)=경쟁, 타 tier(1차)=의뢰처로 갈랐습니다." if is2 else "동급(1차)=경쟁, 2차=인근 전문센터로 갈랐습니다.")),
            ("③ 거리로 경쟁 강도 반영",
             f"가까운 경쟁일수록 위협을 크게, 먼 경쟁은 작게 반영합니다. "
             + (f"{rc}곳 중 {far}곳이 600m 밖이라 경쟁 압력이 낮습니다." if far else "먼 경쟁은 작게 반영합니다.")),
            ("④ 자기 제외 + 리뷰 비교",
             "주소·상호가 겹치는 자기 병원은 제외. 추천 경쟁사 리뷰를 우리와 비교해 상대포지션을 산출했습니다."),
        ])))

    # 기준 표
    def _res(sc):
        if sc is None:
            return ("결측", "t-warn")
        return ("우수", "t-good") if sc >= 70 else (("양호", "t-warn") if sc >= 45 else ("개선", "t-bad"))
    by = {m["key"]: m for m in k["metrics"]}
    crit = [
        ("동급 경쟁 밀도", f"동급이 얼마나·얼마나 가까이 있나? ({k['rival_count']}곳, 최근접 {k['nearest_m'] or '–'}m)",
         _res(by.get("co_density", {}).get("score"))),
    ]
    if is2:
        crit.append(("의뢰처 네트워크", f"주변 1차(유입원)가 충분한가? ({k['referral_count']}곳)",
                     ("우수", "t-good") if k["referral_count"] >= 5 else ("보통", "t-warn")))
    crit.append(("리뷰 상대포지션", "경쟁사 대비 리뷰가 앞서나?", _res(by.get("co_rel_position", {}).get("score"))))
    crit.append(("특화 빈자리", "동급이 안 하는 특화가 있나?", _res(by.get("co_gap_specialty", {}).get("score"))))
    crit.append(("경쟁 포지션 종합", f"여유+유입을 합친 위치는? (경쟁 포지션 {cod}점)", _res(k["co_density"])))
    n = "5" if is2 else "4"
    body.append(C.section(n, "어떤 기준으로 봤나 — 평가 항목", C.criteria_table(crit)))

    # ⑥ 주변 병원 지형 (참조 순서: 평가 항목 뒤)
    n = "6" if is2 else "5"
    geo = "<b>동급 경쟁 병원</b>"
    geo += C.table(["병원명", "구분", "거리"], _rival_rows(k["rivals"]) or [["(반경 내 동급 경쟁 없음)", "", ""]],
                   num_cols={2})
    if k["referrals"]:
        lab = "의뢰처(1차) 병원" if is2 else "인근 2차 병원"
        geo += f"<b>{lab}</b>"
        geo += C.table(["병원명", "구분", "거리"], _rival_rows(k["referrals"]), num_cols={2})
    if k["top3"]:
        geo += "<b>리뷰 정밀비교 추천 Top3</b><p class=\"lead\" style=\"font-size:13px;color:#5b6675\">가장 가까운 상위 경쟁 — 리뷰수·평점을 직접 비교할 대상입니다.</p>"
        rows = []
        for i, r in enumerate(k["top3"]):
            rvp = []
            if r.get("review_count"):
                rvp.append(f"리뷰 {r['review_count']:,}")
            if r.get("rating"):
                rvp.append(f"★{r['rating']}")
            rv = " · ".join(rvp) or "리뷰 미입력"
            rows.append([f"{i+1}", esc(r["name"]), f"{r['distance_m']:,}m", rv])
        geo += C.table(["순위", "병원명", "거리", "리뷰·평점"], rows, num_cols={2})
    body.append(C.section(n, "주변 병원 지형", geo))

    # ⑦ 유리한 점 (경쟁 강점)
    n = "7" if is2 else "6"
    _rel = by.get("co_rel_position", {})
    fnd = []
    if near == 0 and nearest:
        fnd.append(C.finding(
            "코앞 동급 경쟁이 없다 (사실상 근거리 독점)",
            f"동급 {rc}곳 중 <b>300m 이내는 {near}곳</b>, 가장 가까운 {esc(riv0)}도 {nearest:,}m입니다. "
            f"{far}곳은 600m 밖이라, 즉시 상권이 겹치는 직접 경쟁이 거의 없습니다.", "g", src="경쟁"))
    elif nearest and nearest >= 700:
        fnd.append(C.finding(
            f"근거리 경쟁 여유 — 최근접 {nearest:,}m",
            f"가장 가까운 동급 {esc(riv0)}도 {nearest:,}m로 떨어져 있어, 상권 내 우선 선택지가 될 여지가 큽니다.", "g", src="경쟁"))
    if is2 and rf:
        near_ref = "·".join(f"{esc(r['name'])}({r['distance_m']:,}m)" for r in refs[:2])
        fnd.append(C.finding(
            f"의뢰처 1차가 {rf}곳으로 풍부하다",
            f"바로 옆 {near_ref}를 비롯해 주변 1차 {rf}곳이 모두 <b>잠재 유입원</b>입니다. "
            f"이 관계를 활용하면 광고 없이도 환자가 흘러옵니다(경쟁 포지션 +{bonus} 가점의 근거).", "g", src="경쟁"))
    if _rel.get("score") is not None and _rel["score"] >= 60:
        fnd.append(C.finding(
            "리뷰가 경쟁사보다 앞선다",
            f"추천 경쟁사와 비교한 상대포지션 <b>{_rel['score']}(경쟁 우세)</b>. "
            "리뷰 지표가 경쟁사 평균을 웃돌아, 리뷰 자체가 강력한 마케팅 자산입니다.", "g", src="경쟁"))
    if not fnd:
        fnd.append(C.finding("경쟁 목록 입력 시 강점 도출", "반경 내 병원 목록을 입력하면 경쟁 여유가 자동 도출됩니다.", "w", src="경쟁"))
    body.append(C.section(n, "유리한 점", "".join(fnd), subtitle="경쟁 강점"))

    # ⑧ 유의할 점 · 기회 (경쟁 리스크)
    n = "8" if is2 else "7"
    warn = []
    # 리뷰 볼륨 열위 — 경쟁사 리뷰가 우리보다 훨씬 많으면 정직하게 경고
    _rated = [r for r in k.get("top3", []) if r.get("review_count")]
    _max_rc = max((r["review_count"] for r in _rated), default=0)
    if _rel.get("score") is not None and _rel["score"] <= 50 and _max_rc:
        top_rival = max(_rated, key=lambda r: r["review_count"])
        warn.append(C.finding(
            "경쟁사 리뷰 볼륨이 우리보다 많다",
            f"상대포지션 {_rel['score']}(하위권). {esc(top_rival['name'])}는 리뷰 {top_rival['review_count']:,}개로 "
            "우리보다 훨씬 많습니다. 리뷰 수는 사회적 증거·검색 노출과 직결되니, "
            "<b>리뷰 요청 자동화·후기 확보</b>를 우선 과제로 두세요.", "b", src="경쟁"))
    if is2 and far:
        warn.append(C.finding(
            f"광역({radius_km}km) 진료권엔 2차 경쟁군이 존재",
            f"보호자가 차로 이동하는 2차 특성상 진료권이 넓습니다. 인근에 24시·의료센터 계열 {rc}곳이 포진해 있어, "
            "근거리 여유에 안주하지 말고 <b>광역 인지도(검색·평판)</b>를 확보해야 합니다.", "w", src="경쟁"))
    elif not is2 and nearest and nearest < 500:
        warn.append(C.finding(
            f"최근접 경쟁 {nearest:,}m — 근접 압력",
            "가장 가까운 동급이 도보권입니다. 검색·지도 노출과 첫인상(플레이스·리뷰)에서 밀리지 않도록 국지 방어가 필요합니다.", "w", src="경쟁"))
    if h24:
        warn.append(C.finding(
            "동급 다수가 '24시·응급' — 차별 특화 필요",
            f"경쟁 {'2차' if is2 else '동급'} 상당수({h24}곳)가 24시·응급을 내세웁니다. "
            f"{esc(spec_hint)}를 전면에 세워 \"그냥 24시\"와 구별되는 포지션을 만들어야 합니다.", "w", src="경쟁"))
    if is2 and rf:
        warn.append(C.finding(
            "의뢰처 관계는 '관리'해야 유지된다",
            f"1차 {rf}곳은 자동으로 보내주지 않습니다. 리퍼 절차·회송 리포트·감사 피드백 등 "
            "<b>관계 관리</b>가 없으면 다른 2차로 환자가 갈 수 있습니다.", "w", src="경쟁"))
    if not warn:
        warn.append(C.finding("경쟁 리스크 낮음",
                              "현재 데이터 기준 두드러진 경쟁 리스크는 확인되지 않았습니다. 리뷰·특화 데이터를 채우면 정밀도가 올라갑니다.", "g", src="경쟁"))
    body.append(C.section(n, "유의할 점 · 기회", "".join(warn), subtitle="경쟁 리스크"))

    # ⑨ 경쟁 우위 전략 로드맵 (3불릿)
    n = "9" if is2 else "8"
    if is2:
        intro = f'"근거리 여유 + 의뢰처 {rf}곳 + 리뷰 우위"라는 강점을 마케팅으로 전환하는 순서입니다.'
        now_t, now_b = "1차 리퍼럴 관계 강화 (즉시)", [
            f"근거리 1차({esc(ref_names)} 등)에 리퍼 안내·회송 리포트 체계 제안",
            '"CT·MRI·중환자 24시" 의뢰 가능 항목을 1페이지 리퍼 카드로 제작·배포',
            "의뢰 케이스 회송 시 감사 피드백 → 재의뢰 신뢰 구축"]
        mid_t, mid_b = "리뷰 우위 + 특화 차별화 (1~2개월)", [
            f"상대포지션 {_rel.get('score','–')}의 리뷰 우위를 플레이스·블로그·광고 문구로 자산화",
            f"{spec_hint}를 전면 포지셔닝 — \"그냥 24시\"와 구별",
            "경쟁사 공통 약점(대기·불친절 등)을 우리 강점 메시지로 역공략"]
        long_t, long_b = "광역 진료권 인지 확대 (지속)", [
            "인근 동남권으로 검색 노출·평판 관리 확대",
            "1차 병원 네트워크를 정기 세미나·심포지엄으로 확대",
            "분기별 경쟁·리퍼 재진단으로 경쟁군 변화 모니터링"]
    else:
        intro = "근거리 경쟁 여유를 검색·평판 우위로 굳히는 순서입니다."
        now_t, now_b = "지역 검색·평판 선점 (즉시)", [
            "'지역+진료과목' 키워드에서 상위 노출 확보",
            "네이버 플레이스·리뷰로 첫인상(별점·응대) 관리",
            "근거리 경쟁 대비 차별 메시지를 첫 화면에 고정"]
        mid_t, mid_b = "특화 차별화 (1~2개월)", [
            f"{spec_hint} 등 특화를 전면 포지셔닝",
            "경쟁사 공통 약점을 우리 강점 메시지로 역공략",
            "리뷰·후기 자산화로 신뢰 근거 축적"]
        long_t, long_b = "인지 확대·재진단 (지속)", [
            "인접 상권으로 검색·SNS 도달 확대",
            "2차 병원과 의뢰 관계 구축(고난도 케이스 회송)",
            "분기별 경쟁 재진단으로 경쟁군 변화 모니터링"]
    body.append(C.section(n, "경쟁 우위 전략 로드맵",
                          f'<p class="lead">{intro}</p>' + C.roadmap([
                              ("now", now_t, now_b, ""),
                              ("mid", mid_t, mid_b, ""),
                              ("long", long_t, long_b, ""),
                          ])))

    # 정리 (자동)
    if is2:
        summary = (f"<b>정리</b> — {esc(nm_)}{nj} 2차 병원으로서 코앞 동급 경쟁이 거의 없고(300m 내 {near}곳), "
                   f"주변 1차 {rf}곳이 모두 의뢰처인 <b>{'매우 유리한' if loose else '양호한'} 경쟁 포지션({cod})</b>입니다. "
                   "관건은 상권처럼 자동으로 굴러가는 게 아니라, <b>1차 리퍼럴 관계를 관리</b>하고, "
                   "<b>리뷰 우위·특화를 광역으로 알리는</b> 실행입니다. '바로' 항목(리퍼럴 관계 강화)부터 손대는 것을 권합니다.")
    else:
        summary = (f"<b>정리</b> — {esc(nm_)}{nj} 반경 {radius_km}km 내 동급 {rc}곳의 "
                   f"<b>경쟁 포지션 {cod}점</b>입니다. 검색·평판 선점과 특화 차별화로 근거리 우위를 굳히세요. "
                   "'바로' 항목부터 손대는 것을 권합니다.")
    body.append(C.callout(summary, good=loose))

    # ── 여기부터는 참조에 없는 '심화 분석'(우리 부가) ──
    body.append(C.divider("심화 분석 — 경쟁사 마케팅",
                          "아래는 참조 리포트에 없는 추가 분석입니다: 특화 포지셔닝 맵·경쟁사 온라인 채널 진단·전략 제언."))
    mk_sections, _ = _marketing_sections(data, ctx, is2, int(n) + 1)
    body.extend(mk_sections)

    return page(
        title=f"{clinic['name']} 경쟁분석",
        kicker="COMPETITION & REFERRAL",
        h1=f"{clinic['name']} 경쟁·의뢰처 분석",
        sub=f"반경 {k['radius_m']:,}m · {'2차 전문센터' if is2 else '1차 병원'} 관점",
        meta=[policy.TOOL_LABEL, clinic.get("date", ""), f"tier {k['subject_tier']}차"],
        body_html="".join(body),
        footnotes=[policy.FOOTNOTE_METHOD, policy.FOOTNOTE_NO_CRAWL, policy.DISCLAIMER_GENERIC],
        hero=HERO_NAVY, current_no=REPORT_NO, filenames=ctx["filenames"],
    )
