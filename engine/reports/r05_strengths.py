# -*- coding: utf-8 -*-
"""05 강점 종합 — 01~04의 강점(green)만 통합 (작업명세 §3). 약점·리스크 제외."""
from .. import components as C
from .. import policy
from .. import insights
from ..design import page, esc, HERO_NAVY

REPORT_NO = "05"
REPORT_LABEL = "강점"


def build(data, ctx):
    clinic = data["clinic"]
    t = ctx["trade"]; k = ctx["comp"]; rv = data.get("review", {})
    axes = insights.derive_strengths(data, ctx)
    body = []

    # ① 데이터 범위 안내
    used = []
    if t.get("saturation") is not None:
        used.append("상권")
    if k.get("rival_count") is not None:
        used.append("경쟁")
    if data.get("marketing", {}).get("channels"):
        used.append("온라인 채널")
    if rv.get("channels"):
        used.append("리뷰 평판")
    missing = [x for x in ["상권", "경쟁", "온라인 채널", "리뷰 평판"] if x not in used]
    note = f"사용한 진단: <b>{', '.join(used) or '없음'}</b>."
    if missing:
        note += f" 미포함: {', '.join(missing)} — 추가되면 해당 강점 축이 자동 삽입됩니다."
    body.append(C.note(note))

    # ① 한 줄 요약 (+스냅샷) — 축을 엮은 데이터 서술(참조 양식)
    total_rv = sum(c.get("review_count", 0) for c in rv.get("channels", []))
    pos_sum = sum(c.get("sentiment", {}).get("pos", 0) * c.get("review_count", 0)
                  for c in rv.get("channels", []))
    pos_rate = round(pos_sum / total_rv) if total_rv else None
    n_ax = len(axes)
    axis_bits = [a["one_liner"] for a in axes]
    if axis_bits:
        narr = (f"<b>{esc(clinic['name'])}은 실력·평판·입지·경쟁 포지션이 고루 갖춰진 강한 병원입니다.</b> "
                "핵심 강점은 " + esc(" / ".join(axis_bits)) + "입니다. "
                f"{n_ax}개 분석이 모두 ‘기본기는 이미 상위권’이라는 같은 결론을 가리킵니다.")
    else:
        narr = f"<b>{esc(clinic['name'])}의 강점 축을 도출할 데이터가 부족합니다.</b> 진단을 추가하면 자동 채워집니다."
    summary = C.callout(narr, good=True)
    summary += C.snap([
        (f"{k['co_density']}점", "경쟁 포지션 종합"),
        (f"{total_rv:,}개" if total_rv else "–", "리뷰 자산"),
        (f"{k['referral_count']}곳" if k.get("referral_count") else "–", "주변 의뢰처(1차)"),
        (f"{pos_rate}%" if pos_rate is not None else f"{n_ax}개", "리뷰 긍정 비율" if pos_rate is not None else "강점 축"),
    ])
    body.append(C.section("1", "한 줄 요약", summary))

    # ② 강점 축 카드 (네 개의 강점 축)
    _title2 = "네 개의 강점 축" if n_ax == 4 else f"{n_ax}개의 강점 축"
    if axes:
        body.append(C.section("2", _title2, C.pillars(
            [(f"강점 {i+1}", a["axis"], a["one_liner"]) for i, a in enumerate(axes)])))

    # 진료 특화 상세(마케팅 분석에서 자동 추출) — 진료 역량 축에 붙임(03에서 이동)
    _spec = data.get("marketing", {}).get("specialty_analysis") or {}
    _emb = {"강함": "t-good", "보통": "t-warn", "약함": "t-bad"}

    # ③~ 강점별 상세 (축마다 개별 섹션)
    _circ = ["①", "②", "③", "④", "⑤"]
    for i, a in enumerate(axes):
        is_clinical = a["axis"] == insights.AXIS_CLINICAL
        _groups = (_spec.get("groups") or []) if is_clinical else []
        # 진료 역량 축에 계열 그룹이 있으면 개별 특화 findings 대신 '계열별'로 대체(산만함 방지)
        if is_clinical and _groups:
            blocks = ('<p class="lead">진료 특화를 계열별로 묶어 정리했습니다.</p><div class="card">')
            for g in _groups:
                emb = g.get("emphasis", "보통")
                items = " · ".join(g.get("items", []))
                tag = (f' <span class="tag {_emb.get(emb, "t-warn")}">마케팅 강조 {esc(emb)}</span>'
                       if emb else "")
                title = g.get("category", "진료 계열") + (f" ({items})" if items else "")
                blocks += C.finding(title, esc(g.get("summary", "")), "g", tag=tag)
            blocks += "</div>"
        else:
            _fs = "".join(C.finding(f["title"], f["body"], "g", src=f.get("src"))
                          for f in a["findings"])
            blocks = f'<div class="card">{_fs}</div>' if _fs else ""
        # 진료 역량 축: (그룹 없을 때) 마케팅 강조 정도 + 제안
        if is_clinical and _spec:
            if not _groups and _spec.get("specialties"):   # 그룹 없을 때만 개별(폴백)
                blocks += ('<h4 style="margin:16px 0 6px;font-size:14px;color:var(--navy)">'
                           '마케팅에서 내세우는 정도</h4><div class="card">')
                for s in _spec["specialties"]:
                    emb = s.get("emphasis", "보통")
                    tag = f' <span class="tag {_emb.get(emb, "t-warn")}">마케팅 강조 {esc(emb)}</span>'
                    blocks += C.finding(s.get("name", "특화"), esc(s.get("evidence", "")), "g", tag=tag)
                blocks += "</div>"
            if _spec.get("suggestions"):
                blocks += ('<h4 style="margin:16px 0 6px;font-size:14px;color:var(--navy)">'
                           '제안 — 더 내세우면 좋을 특화 <span class="tag t-warn">기회</span></h4><div class="card">')
                for s in _spec["suggestions"]:
                    blocks += C.finding(s.get("name", "제안"), esc(s.get("note", "")), "w")
                blocks += "</div>"
        body.append(C.section(str(i + 3), f"강점 {_circ[i]} {a['axis']}", blocks,
                              subtitle=a.get("metric")))

    # 강점 한눈에 보기 표 (근거 = 정량 지표)
    if axes:
        rows = [[a["axis"], a["one_liner"],
                 a.get("metric") or " · ".join(dict.fromkeys(f.get("src", "") for f in a["findings"]))]
                for a in axes]
        body.append(C.section(str(n_ax + 3), "강점 한눈에 보기",
                              C.table(["영역", "핵심 강점", "근거 지표"], rows)))

    # (멀티지점) 형제 지점 대비 — 심화
    sib = clinic.get("sibling")
    if sib:
        rows = []
        if sib.get("co_density") is not None:
            win = ' <span class="win">우위</span>' if k["co_density"] >= sib["co_density"] else ""
            rows.append(["경쟁 포지션", f"{k['co_density']}점", f"{sib['co_density']}점", win or "–"])
        if sib.get("saturation") is not None and t.get("saturation"):
            win = ' <span class="win">우위</span>' if t["saturation"] >= sib["saturation"] else ""
            rows.append(["시장 포화도", f"{t['saturation']:,}", f"{sib['saturation']:,}", win or "–"])
        if rows:
            body.append(C.divider("심화 — 형제 지점 대비 차별 강점", f"vs {esc(sib.get('name',''))}"))
            body.append(C.section("＋", "형제 지점 대비 차별 강점",
                                  C.table(["항목", clinic["name"], sib.get("name", "형제"), "판정"], rows)))

    # 마지막 섹션: 강점을 어떻게 살릴까 — 활용 방향(바로/중기/장기 로드맵, 데이터 자동)
    addr = clinic.get("address", "")
    sigungu = ""
    for tok in addr.replace("특별시", "").replace("광역시", "").split():
        if tok.endswith(("구", "시", "군")):
            sigungu = tok
            break
    axis_set = {a["axis"] for a in axes}
    has_clinical = insights.AXIS_CLINICAL in axis_set
    mk_types = {c.get("type") for c in data.get("marketing", {}).get("channels", [])}

    now = []
    if total_rv:
        now.append(f"{total_rv:,}개 리뷰·미담 자산을 플레이스·블로그·광고 문구로 적극 노출(동의 하에)")
    now.append("전 채널 문의 동선을 ‘전화(탭)+예약+카카오 상담’으로 통일 — 있는 방문을 상담으로")
    if {"map", "naverplace"} & mk_types:
        now.append("카카오맵 후기 켜기·구글 프로필 정비로 방치된 평판 노출 회복")

    mid = []
    if has_clinical:
        mid.append("2차 전문 진료·영상진단 역량을 전면 포지셔닝 — ‘그냥 24시’와 구별")
    if k.get("referral_count"):
        mid.append(f"주변 1차 {k['referral_count']}곳과 리퍼럴 관계 강화(리퍼 카드·회송 리포트)로 유입 실현")
    mid.append("미등록 신규 반려가구 대상 ‘동물등록+건강검진’ 패키지로 정주 리텐션 시작")

    lng = ["전문 진료 경험 키워드 리뷰를 쌓아 검색 강점 확대",
           (f"{sigungu} 넘어 광역까지 검색 노출·평판 관리" if sigungu else "인근을 넘어 광역까지 검색 노출·평판 관리"),
           "분기별 경쟁·상권·평판 재진단으로 강점 변화 모니터링"]

    steps = [("now", "있는 강점을 새는 곳 없이 ‘전환’으로 연결", now, ""),
             ("mid", "진료·입지 강점을 ‘광역 인지’로 확장", mid, ""),
             ("long", "강점을 지속 자산으로 관리", lng, "")]
    lead = C.info("강점은 이미 강합니다. 관건은 강점이 자동으로 굴러가지 않는다는 것 — "
                  "관계·노출·전환으로 <b>연결</b>하는 실행입니다.")
    body.append(C.section(str(n_ax + 4), "강점을 어떻게 살릴까 — 활용 방향", lead + C.roadmap(steps)))

    strong = axis_bits[0] if axis_bits else "핵심 역량"
    body.append(C.callout(
        f"<b>정리</b> — {esc(clinic['name'])}은 {esc(' · '.join(a['axis'] for a in axes))}를 두루 갖춘 균형 잡힌 병원입니다. "
        "공통 메시지는 하나 — ‘강점은 충분하니, 새지 않게 <b>연결</b>하고 더 넓게 <b>알리는</b> 실행’입니다. "
        "리뷰·미담 노출과 전환 동선 통일 같은 ‘바로’ 항목부터 손대길 권합니다. "
        "위 강점들은 06 <b>12개월 마케팅 계획</b>에서 분기별 실행으로 전개됩니다.", good=True))

    return page(
        title=f"{clinic['name']} 강점 종합 리포트",
        kicker="STRENGTHS SYNTHESIS",
        h1=f"{clinic['name']} 강점 종합 리포트",
        sub="4종 진단에서 강점만 추출·통합 — 연결·증폭·확장 프레임",
        meta=[policy.TOOL_LABEL, clinic.get("date", ""), f"강점 축 {len(axes)}개"],
        body_html="".join(body),
        footnotes=[policy.FOOTNOTE_METHOD, policy.DISCLAIMER_GENERIC],
        hero=HERO_NAVY, current_no=REPORT_NO, filenames=ctx["filenames"],
    )
