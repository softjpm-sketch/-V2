# -*- coding: utf-8 -*-
"""04 리뷰분석 — 리뷰 평판 (PRD §16). 히어로만 퍼플(작업명세 §2.1)."""
from .. import components as C
from .. import policy
from ..design import page, esc, HERO_PURPLE

REPORT_NO = "04"
REPORT_LABEL = "리뷰분석"

SENTI_LABEL = {"pos": "긍정", "neu": "중립", "neg": "부정"}


def build(data, ctx):
    clinic = data["clinic"]
    rv = data.get("review", {})
    channels = rv.get("channels", [])
    body = []

    if not channels:
        body.append(C.note(
            "리뷰 평판 입력(<code>review.channels</code>)이 없어 이 리포트를 비웠습니다. "
            "네이버 플레이스·구글 리뷰 텍스트(붙여넣기/화면)를 넣으면 감성 분포·키워드가 자동 생성됩니다."))

    total_reviews = sum(c.get("review_count", 0) for c in channels)
    # 가중 평균 별점
    rated = [(c.get("rating"), c.get("review_count", 0)) for c in channels if c.get("rating")]
    wr = sum(r * n for r, n in rated); wn = sum(n for _, n in rated)
    avg_rating = round(wr / wn, 2) if wn else None
    # 전체 긍정률
    pos_sum = sum(c.get("sentiment", {}).get("pos", 0) * c.get("review_count", 0) for c in channels)
    pos_rate = round(pos_sum / total_reviews) if total_reviews else None

    syn = rv.get("synthesis") or {}
    quotes = rv.get("quotes", [])

    def _quote(q):
        src = f"{q.get('channel','')} · {q.get('author','익명')}"
        return C.quote(q.get("text", ""), src)

    def _quotes_by(sent, limit):
        picked = [q for q in quotes if q.get("sentiment") == sent][:limit]
        return "".join(_quote(q) for q in picked)

    # ① 핵심 요약 — 서술 한 줄(종합 패스). KPI 카드는 넣지 않음(참조 양식).
    if syn.get("summary"):
        summ = esc(syn["summary"])
    else:                                # 종합 없으면 수치로 한 줄 자동 구성
        bits = [f"총 {total_reviews:,}개 리뷰"]
        if pos_rate is not None:
            bits.append(f"긍정 {pos_rate}%")
        if avg_rating:
            bits.append(f"평균 ★{avg_rating}")
        bits.append(f"{len(channels)}개 채널 분석")
        summ = " · ".join(bits) + "입니다."
    body.append(C.section("1", "핵심 요약", C.callout("<b>한 줄:</b> " + summ)))

    n = 2

    # ② 채널별 스냅샷 & 감성 분포 — 나란히 비교 박스
    def _brand(name):
        nm = name or ""
        return "naver" if "네이버" in nm else ("google" if "구글" in nm.lower() or "google" in nm.lower() else "etc")
    boxes = []
    for c in channels:
        s = c.get("sentiment", {})
        pos, neu, neg = s.get("pos", 0), s.get("neu", 0), s.get("neg", 0)
        rc = c.get("review_count") or 0
        kpis = [("리뷰 수", f"{rc:,}개" if rc else "확인 필요"),
                ("별점", f"★{c.get('rating','–')}"),
                ("최신성", c.get("recency", "확인 필요"))]
        boxes.append(C.review_channel_box(c.get("name", ""), _brand(c.get("name", "")), kpis, (pos, neu, neg)))
    if channels:
        grid = f'<div class="cols">{"".join(boxes)}</div>' if len(boxes) >= 2 else "".join(boxes)
        lead = "채널마다 표본·시점이 달라 평판 인상이 갈릴 수 있습니다. 감성 비율은 제공된 표본 기준 추정입니다."
        if syn.get("channel_note"):     # 왜 채널 인상이 갈리는지 자동 서술
            lead = "※ 감성 비율은 제공된 표본 기준 추정입니다. " + esc(syn["channel_note"])
        body.append(C.section(str(n), "채널별 스냅샷 & 감성 분포",
                              f'<p class="lead">{lead}</p>' + grid))
        n += 1

    # ③ 공통 칭찬 키워드 — 칩 + 강점 테마 + 예시 리뷰
    pk = [k.get("keyword") if isinstance(k, dict) else k for k in rv.get("praise_keywords", [])]
    ck = [k.get("keyword") if isinstance(k, dict) else k for k in rv.get("complaint_keywords", [])]
    strengths = syn.get("strengths", [])
    if pk or strengths:
        sub = "(양 채널 1위)" if len(channels) >= 2 and pk else None
        inner = '<p class="lead">채널을 가로질러 반복되는 칭찬 — 이 병원의 검증된 강점입니다.</p>'
        if pk:
            inner += C.keywords(pk)
        inner += '<div class="card" style="margin-top:14px">'
        for s in strengths:                 # 먼저 '무엇이 강점인지' 서술
            inner += C.finding(s.get("title", "강점"), esc(s.get("body", "")), "g")
        inner += _quotes_by("pos", 3)       # 그 다음 예시 리뷰(긍정)
        inner += "</div>"
        body.append(C.section(str(n), "공통 칭찬 키워드", inner, subtitle=sub))
        n += 1

    # ④ 리스크·불만 키워드 — 칩 + 불만 테마 + 예시 리뷰
    challenges = syn.get("challenges", [])
    if ck or challenges:
        inner = '<p class="lead">반복되는 불만은 이탈·저평점의 원인 — 개선 우선순위의 근거가 됩니다.</p>'
        if ck:
            inner += C.keywords(ck, neg=True)
        inner += '<div class="card" style="margin-top:14px">'
        for w in challenges:
            kind = "b" if w.get("severity") == "high" else "w"
            tag = (' <span class="tag t-bad">심각도 높음</span>' if w.get("severity") == "high"
                   else ' <span class="tag t-warn">심각도 중간</span>')
            inner += C.finding(w.get("title", "개선점"), esc(w.get("body", "")), kind, tag=tag)
        inner += _quotes_by("neg", 3)       # 예시 리뷰(부정) — 근거로 붙임
        inner += "</div>"
        body.append(C.section(str(n), "리스크·불만 키워드", inner))
        n += 1

    # ⑤ 운영 관점 발견 — 채널 관리 관점 핵심만(종합 패스 ops_findings 우선)
    ops = syn.get("ops_findings") or rv.get("findings", [])
    if ops:
        fh = ""
        for f in ops:
            fh += C.finding(f.get("title", ""), esc(f.get("body", "")),
                            {"high": "b", "mid": "w"}.get(f.get("severity"), "g"))
        # 미담(긍정) 대표 후기 1~2개를 근거로
        fh += _quotes_by("pos", 2) if syn.get("ops_findings") else ""
        body.append(C.section(str(n), "운영 관점 발견", fh))
        n += 1

    # ⑥ 개선 우선순위 — 로드맵 + 정리 + 회색 근거 문구
    if rv.get("actions"):
        inner = C.actions_to_roadmap([{**a, "title": a.get("title", "개선")} for a in rv["actions"]])
        if syn.get("conclusion"):
            inner += C.callout("<b>정리:</b> " + esc(syn["conclusion"]))
        srcs = " · ".join(c.get("name", "") for c in channels)
        inner += ('<p style="font-size:12px;color:var(--muted);margin-top:10px">'
                  f'본 분석은 제공해 주신 리뷰 텍스트·화면({esc(srcs)}, 총 {total_reviews:,}개)를 근거로 한 표본 분석입니다. '
                  '감성 비율은 표본 기준 추정이며 전수 결과와 다를 수 있고, 개별 부정 리뷰의 사실관계는 병원 내부 확인이 필요합니다.</p>')
        body.append(C.section(str(n), "개선 우선순위", inner))
        n += 1

    return page(
        title=f"{clinic['name']} 리뷰분석",
        kicker="REVIEW REPUTATION",
        h1=f"{clinic['name']} 리뷰 평판 분석",
        sub="네이버·구글 감성 분포 · 칭찬/불만 키워드 · 채널 평판 격차",
        meta=[policy.TOOL_LABEL, clinic.get("date", ""),
              f"총 {total_reviews:,}개 리뷰" if total_reviews else "리뷰 미입력"],
        body_html="".join(body),
        footnotes=[
            "리뷰는 작성자 고유 콘텐츠 — 인용·활용 시 동의를 권장하고 개인정보·진료정보를 최소화합니다.",
            policy.FOOTNOTE_NO_CRAWL, policy.DISCLAIMER_GENERIC],
        hero=HERO_PURPLE, current_no=REPORT_NO, filenames=ctx["filenames"],
    )
