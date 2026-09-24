# -*- coding: utf-8 -*-
"""03 마케팅 — 온라인 채널 종합 진단 (PRD §6~11).
참조(인천 스카이) 구조: 채널 이동 목차 → 종합 진단(핵심 한 줄·공통 강점·공통 과제) →
채널별(핵심 한 줄·종합 점수 카드·평가 항목표·강점/약점) → 실행 우선순위 매트릭스."""
from .. import components as C
from .. import policy
from ..design import page, esc, HERO_NAVY

REPORT_NO = "03"
REPORT_LABEL = "마케팅"

CHANNEL_LABELS = {
    "homepage": "홈페이지", "blog": "네이버 블로그", "instagram": "인스타그램",
    "naverplace": "네이버 플레이스", "kakao": "카카오톡 채널", "map": "카카오맵",
    "tmap": "T맵", "aeo_geo": "AEO·GEO",
}
ORDER = ["homepage", "blog", "instagram", "naverplace", "kakao", "map", "tmap", "aeo_geo"]


def _lab(t):
    return "AEO·GEO (AI 검색 노출)" if t == "aeo_geo" else CHANNEL_LABELS.get(t, t)


# ── 공통 과제 중복 병합 ─────────────────────────────────────────
# 채널별 약점을 종합하면 같은 문제(전환 동선 vs 전화번호 클릭 등)가 반복된다.
# 주제 버킷별로 대표(가장 심각·본문 긴 것) 1개만 남겨 중복을 제거한다.
_BUCKETS = [
    ("전환 동선", ["전화", "예약", "전환", "cta", "dm ", "상담", "문의", "톡톡", "동선", "클릭"]),
    ("정보 일치(NAP)", ["주소", "nap", "일치", "정확", "번지", "정보 정확"]),
    ("채널 연결", ["연결", "링크", "끊", "상호", "회유", "유입"]),
    ("검색 노출·SEO", ["seo", "검색", "키워드", "meta", "구조화", "노출", "h1", "제목", "스키마", "발견"]),
    ("평판·도달 증폭", ["팔로워", "반응", "공감", "댓글", "평판", "후기", "리뷰", "성장", "정체", "도달", "참여"]),
]


def _bucket_of(title, body):
    t = (title + " " + body).lower()
    for name, kws in _BUCKETS:
        if any(k in t for k in kws):
            return name
    return None


def _sev_rank(w):
    return 0 if w.get("severity") == "high" else 1


def _sev_tag(w):
    """제목 뒤에 붙일 심각도 배지(안전 HTML)."""
    return (' <span class="tag t-bad">심각도 높음</span>' if w.get("severity") == "high"
            else ' <span class="tag t-warn">심각도 중간</span>')


def _dedup_weaks(weaks):
    """weaks: [(channel_label, weak_dict), ...] → 주제 버킷별 대표 1개 + 미분류는 그대로."""
    best = {}          # bucket → (label, w)
    passthrough = []   # 버킷 미매칭
    for lab, w in weaks:
        b = _bucket_of(w.get("title", ""), w.get("body", ""))
        if b is None:
            passthrough.append((lab, w))
            continue
        cur = best.get(b)
        if cur is None:
            best[b] = (lab, w)
        else:
            # 더 심각하거나(같으면) 본문이 더 자세한 쪽을 대표로
            cl, cw = cur
            if (_sev_rank(w), -len(w.get("body", ""))) < (_sev_rank(cw), -len(cw.get("body", ""))):
                best[b] = (lab, w)
    # 버킷 대표를 우선하되, 최종은 심각도 높은 순으로 정렬(같은 심각도면 대표 먼저)
    out = [(0, r) for r in best.values()] + [(1, p) for p in passthrough]
    out.sort(key=lambda x: (_sev_rank(x[1][1]), x[0]))
    return [r for _, r in out]


def build(data, ctx):
    clinic = data["clinic"]
    mk = data.get("marketing", {})
    channels = mk.get("channels", [])
    by_type = {c.get("type"): c for c in channels}
    body = []

    if not channels:
        body.append(C.note(
            "온라인 채널 진단 입력(<code>marketing.channels</code>)이 없어 이 리포트의 채널 축을 비웠습니다. "
            "링크 4종(홈피·인스타·카카오맵·T맵) + 화면 3종(네이버 블로그·플레이스·카카오톡)을 넣으면 자동 채워집니다."))

    scored = [c for c in channels if c.get("score") is not None]
    avg = round(sum(c["score"] for c in scored) / len(scored)) if scored else None
    best = max(scored, key=lambda c: c["score"]) if scored else None
    worst = min(scored, key=lambda c: c["score"]) if scored else None
    ordered = [by_type[t] for t in ORDER if t in by_type] + \
              [c for c in channels if c.get("type") not in ORDER]

    # ── 리드 + 채널 이동 목차(클릭 카드) ──
    body.append(
        '<p class="lead">아래는 각 채널을 같은 기준(관점 → 평가 → 점수 → 강점/약점 → 실행가능성)으로 '
        "진단한 결과입니다. 맨 아래 ‘실행 우선순위 매트릭스’는 모든 개선안을 효과·노력·비용으로 계산해 "
        "자동 정렬한 것입니다.</p>")
    # 진료 특화 상세는 05 강점 리포트로 이동. 여기선 홈페이지 채널에 가볍게만 반영.
    spec = mk.get("specialty_analysis") or {}
    toc_items = [("combined", "🔗 종합 진단", "공통 강점·과제")]
    for i, c in enumerate(ordered, 1):
        toc_items.append((f"ch{i}", _lab(c.get("type")), f"채널 진단 {i}"))
    toc_items.append(("matrix", "✅ 실행 우선순위", "전체 개선안"))
    body.append(C.toc(toc_items))

    # ── 1. 종합 진단(공통 강점·공통 과제) ──
    seg = ['<section id="combined">']
    seg.append(C.chan_head("종합", "온라인 채널 종합 진단",
                           subtitle=", ".join(_lab(c.get("type")) for c in ordered)))
    if avg is not None and best and worst:
        good = avg >= 65
        seg.append(C.callout(
            f"<b>핵심 한 줄</b> — 온라인 채널 평균 <b>{avg}점</b>으로 "
            + ("전반적으로 상위권입니다. " if good else "기본기를 다질 여지가 있습니다. ")
            + f"<b>{CHANNEL_LABELS.get(best['type'], best['type'])}</b>가 가장 강하고 "
            f"<b>{CHANNEL_LABELS.get(worst['type'], worst['type'])}</b>가 보완 1순위입니다. "
            "공통 과제는 채널마다 제각각인 <b>전환 동선 통일</b>, 상호·주소·전화 표기 일치, 도달 확대입니다.",
            good=good))
    syn = mk.get("synthesis") or {}
    # ── 공통 강점 ──
    if syn.get("strengths"):
        # 종합 패스 결과(채널 교차 테마) — 참조 톤
        seg.append('<h3 class="sub-h">공통 강점</h3><div class="card">')
        for s in syn["strengths"]:
            seg.append(C.finding(s.get("title", "강점"), esc(s.get("body", "")), "g"))
        seg.append("</div>")
    else:
        # 폴백: 종합 결과가 없으면 채널별 강점 상위 3(채널 태그 표시)
        strengths = [(CHANNEL_LABELS.get(c.get("type"), c.get("type", "")), s)
                     for c in ordered for s in c.get("strengths", [])]
        if strengths:
            seg.append('<h3 class="sub-h">공통 강점</h3><div class="card">')
            for lab, s in strengths[:3]:
                seg.append(C.finding(s.get("title", "강점"), esc(s.get("body", "")), "g", src=lab))
            seg.append("</div>")
    # ── 공통 과제 ──
    if syn.get("challenges"):
        seg.append('<h3 class="sub-h">공통 과제(채널을 가로지르는 우선 개선점)</h3><div class="card">')
        for w in syn["challenges"]:
            kind = "b" if w.get("severity") == "high" else "w"
            seg.append(C.finding(w.get("title", "개선점"), esc(w.get("body", "")), kind, tag=_sev_tag(w)))
        seg.append("</div>")
    else:
        weaks = [(CHANNEL_LABELS.get(c.get("type"), c.get("type", "")), w)
                 for c in ordered for w in c.get("weaknesses", [])]
        weaks = _dedup_weaks(weaks)
        if weaks:
            seg.append('<h3 class="sub-h">공통 과제(채널을 가로지르는 우선 개선점)</h3><div class="card">')
            for lab, w in weaks[:5]:
                kind = "b" if w.get("severity") == "high" else "w"
                seg.append(C.finding(w.get("title", "개선점"), esc(w.get("body", "")), kind,
                                     src=lab, tag=_sev_tag(w)))
            seg.append("</div>")
    seg.append("</section>")
    body.append("".join(seg))

    # (진료 특화 상세는 05 강점으로 이동. 03은 홈페이지 채널에 가볍게 반영 — 아래 채널 루프)

    # ── 채널별 개별 섹션 ──
    _spec_names = [s.get("name", "") for s in spec.get("specialties", [])
                   if s.get("emphasis") in ("강함", "보통")][:3]
    _res = {"우수": "t-good", "매우 우수": "t-good", "양호": "t-good", "보통": "t-warn",
            "확인 필요": "t-warn", "확인 권장": "t-warn", "미확인": "t-warn", "정체": "t-bad",
            "낮음": "t-bad", "미흡": "t-bad", "개선 필요": "t-bad"}
    for i, c in enumerate(ordered, 1):
        lab = CHANNEL_LABELS.get(c.get("type"), c.get("type", "채널"))
        seg = [f'<a id="ch{i}"></a><section class="channel">']
        seg.append(C.chan_head(str(i), _lab(c.get("type")), url=c.get("url")))
        if c.get("one_liner"):
            seg.append(C.callout("<b>핵심 한 줄</b> — " + esc(C.plainify(c["one_liner"]))))
        # 홈페이지에는 '내세우는 진료 특화'를 가볍게만 반영(상세는 05 강점)
        if c.get("type") == "homepage" and _spec_names:
            seg.append(C.info(
                f"<b>내세우는 진료 특화</b> — {esc(' · '.join(_spec_names))} "
                "(콘텐츠에서 반복 노출). 특화 강점의 상세 진단·제안은 <b>05 강점 리포트</b>에서 다룹니다."))
        # 종합 점수 = 세부 진단 카드(진행바형)
        if c.get("subscores"):
            cards = [(s.get("label", ""), s.get("level", "보통"), s.get("note", ""))
                     for s in c["subscores"]]
            seg.append('<h3 class="sub-h">종합 점수</h3>')
            seg.append(C.metric_cards(cards))
        elif c.get("score") is not None:
            seg.append('<h3 class="sub-h">종합 점수</h3>')
            seg.append(C.scoregrid([{"name": "종합 점수", "score": c.get("score"), "note": c.get("note", "")}]))
        # 평가 항목(기준) 표
        if c.get("criteria"):
            crows = [(esc(x.get("perspective", "")), esc(x.get("question", "")),
                      (x.get("result", ""), _res.get(x.get("result", ""), "t-warn"))) for x in c["criteria"]]
            seg.append('<h3 class="sub-h">평가 항목(기준)</h3>')
            seg.append(C.criteria_table(crows))
        # 잘하고 있는 점 / 부족한 점
        if c.get("strengths"):
            seg.append('<h3 class="sub-h">잘하고 있는 점 <span class="tag t-good">강점</span></h3><div class="card">')
            for s in c["strengths"]:
                seg.append(C.finding(s.get("title", "강점"), esc(s.get("body", "")), "g"))
            seg.append("</div>")
        if c.get("weaknesses"):
            seg.append('<h3 class="sub-h">부족한 점 · 개선 포인트 <span class="tag t-bad">약점</span></h3><div class="card">')
            for w in c["weaknesses"]:
                kind = "b" if w.get("severity") == "high" else "w"
                seg.append(C.finding(w.get("title", "개선점"), esc(w.get("body", "")), kind, tag=_sev_tag(w)))
            seg.append("</div>")
        # AEO·GEO 채널: 진단은 보여주되, 실제 구조화 코드(schema.org)는 구독 산출물로 게이트
        if c.get("type") == "aeo_geo":
            seg.append(C.callout(
                "🔒 <b>AI 검색 최적화 구조화 데이터(schema.org) 코드</b>는 이 진단 리포트에 포함되지 않습니다. "
                "병원 상호·주소·전화·<b>강점 진료</b>·공식 채널을 AI가 읽는 <b>엔티티 코드</b>로 만들어 "
                "홈페이지에 심고, 심은 뒤 <b>AI 추천에 실제로 오르는지 재검증</b>하는 것은 "
                "<b>구독(엔티티 구축)</b>에서 제공됩니다. 위 진단은 ‘무엇이 비어 있는지’까지입니다."))
        seg.append("</section>")
        body.append("".join(seg))

    # ── 마지막. 실행 우선순위 매트릭스 ──
    all_actions = []
    for c in channels:
        lab = CHANNEL_LABELS.get(c.get("type"), c.get("type", "채널"))
        for a in c.get("actions", []):
            all_actions.append({**a, "desc": a.get("desc", ""),
                                "title": f"[{lab}] " + a.get("title", "개선")})
    if all_actions:
        matrix = ('<a id="matrix"></a>' + C.info(
            "우선순위 점수 = <b>효과×3 − 노력 − 비용</b>. "
            "바로(≥5 또는 노력1·효과2↑) / 중기(2~5) / 장기(&lt;2).") + C.actions_to_roadmap(all_actions))
        body.append(f'<section>{C.sechead(str(len(ordered) + 2), "실행 우선순위 매트릭스")}{matrix}</section>')

    return page(
        title=f"{clinic['name']} 마케팅(온라인 채널 진단)",
        kicker="ONLINE CHANNEL AUDIT",
        h1=f"{clinic['name']} 마케팅 채널 종합 진단",
        sub="홈페이지·블로그·인스타·플레이스·카카오·지도·AEO/GEO 8축 진단",
        meta=[policy.TOOL_LABEL, clinic.get("date", ""), f"평균 {avg}점" if avg is not None else "채널 미입력"],
        body_html="".join(body),
        footnotes=[policy.FOOTNOTE_NO_CRAWL, policy.DISCLAIMER_GENERIC],
        hero=HERO_NAVY, current_no=REPORT_NO, filenames=ctx["filenames"],
    )
