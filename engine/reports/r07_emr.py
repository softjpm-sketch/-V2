# -*- coding: utf-8 -*-
"""07 진료(EMR) 데이터 분석 — 내부 데이터축(재진·휴면·객단가·질환) + 12개월 로드맵.

방법론 §8: 01~06(외부 시장·온라인) 대비 병원 **내부 데이터** 관점.
입력은 data['emr'] = emr.run()의 반환(analysis·roadmap·mask_report·column_mapping).
개인정보는 업로드 시점에 이미 익명화되어, 여기서는 집계 지표만 다룬다.
"""
from .. import components as C
from .. import policy
from .. import emr as _emr
from ..design import page, esc, HERO_PURPLE

# 상시 채널의 성격: 콘텐츠 발행형 vs 운영·관리형 (리포트 설명용)
_CHANNEL_KIND = {
    "네이버": ("발행·관리", "t-good"),
    "카카오": ("운영·관리", "t-blue"),
    "소셜미디어·타겟": ("콘텐츠 발행", "t-good"),
    "지도·내비": ("정보 점검", "t-blue"),
    "AI 검색 노출": ("세팅 유지", "t-blue"),
}

REPORT_NO = "07"
REPORT_LABEL = "진료데이터분석"

_HERO_TEAL = "linear-gradient(135deg,#0f5c52,#128577)"


def _won(v):
    try:
        return f"{int(round(float(v))):,}원"
    except (TypeError, ValueError):
        return "–"


def _pct(v):
    return f"{v*100:.0f}%" if isinstance(v, (int, float)) else "–"


def build(data, ctx):
    clinic = data["clinic"]
    emr = data.get("emr", {})
    an = emr.get("analysis", {})
    rm = emr.get("roadmap", {})
    mask = emr.get("mask_report", {})
    body = []

    if an.get("error"):
        body.append(C.callout(f"⚠️ 분석 불가 — {esc(an['error'])}"))
        return _wrap(clinic, ctx, body)

    rev = an.get("revisit", {})
    arpu = an.get("arpu", {})
    dorm = an.get("dormant", {})
    mix = an.get("diagnosis_mix", [])
    hv = an.get("high_value_candidates", [])
    period = an.get("period", {})

    # ① 스냅샷
    body.append(C.section("1", "진료 데이터 스냅샷", C.snap([
        (f"{an.get('total_visits',0):,}", "총 방문 건수"),
        (f"{an.get('unique_patients') or '–':,}" if an.get("unique_patients") else "–", "고유 환자수(가명)"),
        (_won(arpu.get("total_revenue")) if arpu else "–", "기간 총매출"),
        (f"{esc(period.get('start','–'))}~{esc(period.get('end','–'))}", "분석 기간"),
    ])))

    # ② 개인정보 보호 처리 — 핵심 안전장치
    dropped = mask.get("dropped_fields", [])
    masked = mask.get("masked_fields", [])
    priv = (
        "<b>🔒 개인정보 보호 처리 완료</b> — 이 리포트에는 실제 보호자 정보가 전혀 담겨 있지 않습니다."
        "<ul style='margin:8px 0 0;padding-left:18px;font-size:13.5px;line-height:1.7'>"
        "<li><b>가명 처리</b>: 환자 구분은 세션 랜덤 솔트 + SHA-256 해시(<code>P…</code>)로만. "
        "'같은 환자인지'만 판별되고 <b>원본 재식별은 불가</b>합니다.</li>"
        f"<li><b>원본 삭제</b>: {('· '.join(esc(c) for c in dropped)) if dropped else '해당 없음'} "
        f"컬럼(보호자명·전화·주소 등)은 분석 전에 <b>즉시 폐기</b>했습니다.</li>"
        "<li><b>솔트 폐기</b>: 세션 종료와 함께 솔트를 버려 재연결 경로를 남기지 않습니다.</li>"
        "</ul>")
    body.append(C.section("2", "개인정보 보호 처리", C.info(priv) + C.note(
        "※ 기술적 안전장치입니다. 실제 위탁 처리 시 개인정보 처리위탁 계약·정보주체 동의 등 법적 절차가 선행돼야 합니다.")))

    # ③ 핵심 지표 진단
    metrics = []
    if rev:
        rr = rev.get("revisit_rate")
        # 재진율 60%를 만점 기준으로 환산(참고 점수)
        sc = round(min(100, (rr or 0) / 0.6 * 100)) if rr is not None else None
        metrics.append({"name": "재진율(리텐션)", "score": sc,
                        "note": f"{_pct(rr)} · 재방문 환자 {rev.get('revisit_patients',0)}명 / 평균 {rev.get('avg_visits_per_patient','–')}회"})
    if dorm:
        dr = dorm.get("dormant_rate")
        sc = round(max(0, 100 - (dr or 0) * 100 * 2)) if dr is not None else None  # 휴면율 50%면 0점
        metrics.append({"name": "활성도(휴면 반비례)", "score": sc,
                        "note": f"휴면 {dorm.get('dormant_patients',0)}명({_pct(dr)}) · 최근 {dorm.get('months_threshold',6)}개월 미방문"})
    if arpu:
        metrics.append({"name": "객단가", "score": None,
                        "note": f"방문당 평균 {_won(arpu.get('avg_per_visit'))} · 중앙값 {_won(arpu.get('median_per_visit'))}"
                                + (f" · 환자당 {_won(arpu.get('avg_per_patient'))}" if arpu.get("avg_per_patient") else "")})
    diag = C.scoregrid(metrics)
    # 해석 callout
    if rev.get("revisit_rate") is not None:
        rr = rev["revisit_rate"]
        good = rr >= 0.4
        diag += C.callout(
            f"<b>재진율 {_pct(rr)}</b> — " + (
                "단골화가 안정적입니다. 재진 리마인드로 더 끌어올릴 여지가 있습니다." if rr >= 0.6 else
                "보통 수준. 알림톡 재진 리마인드·정기검진 리콜로 리텐션을 강화하면 매출 안정성이 커집니다." if rr >= 0.4 else
                "낮은 편 — <b>신규 유입보다 재방문 전환</b>이 급선무입니다. 리텐션 자동화를 최우선 과제로 권합니다."),
            good=good)
    body.append(C.section("3", "핵심 지표 진단", diag))

    # ④ 고관여(고객단가) 진료 후보
    if hv:
        rows = [(esc(h["diagnosis"]), _won(h["avg_amount"])) for h in hv]
        thr = an.get("high_value_threshold")
        body.append(C.section("4", "고관여 진료 후보 — 객단가 상향 대상",
            '<p class="lead">진단명별 평균 객단가 상위입니다. 콘텐츠·패키지·전문성 마케팅의 <b>수익 레버</b>가 되는 진료입니다.</p>'
            + C.table(["진단명", "평균 객단가"], rows, num_cols={1})
            + (C.note(f"고관여 임계(상위 20% 분위) = {_won(thr)} 이상") if thr else "")))

    # ⑤ 질환 유입 믹스 — 주력 강점
    if mix:
        rows = []
        for m in mix:
            share = m["share"]
            barw = round(share * 100)
            bar = (f'<div style="display:flex;align-items:center;gap:8px">'
                   f'<div style="flex:1;height:8px;background:#e8f0f9;border-radius:5px;overflow:hidden">'
                   f'<div style="width:{barw}%;height:100%;background:var(--blue)"></div></div>'
                   f'<span style="font-weight:700;color:var(--navy);min-width:38px;text-align:right">{_pct(share)}</span></div>')
            rows.append((esc(m["diagnosis"]), f"{m['visits']:,}", bar))
        body.append(C.section("5", "질환 유입 믹스 — 주력 진료",
            '<p class="lead">가장 많이 유입되는 진료 = 이 병원의 <b>대외 강점</b>. 특화 콘텐츠·광고의 1순위 소재입니다.</p>'
            + C.table(["진단명", "방문수", "유입 비율"], rows, num_cols={1})))

    # ⑥ AI 검색 추천 전략 (AEO·GEO) — EMR 강점 → 엔티티
    aeo = rm.get("aeo", {})
    targets = aeo.get("targets", [])
    if targets:
        trows = [(esc(t["keyword"]),
                  f'<span class="tag {"t-good" if t.get("kind")=="주력" else "t-warn"}">{esc(t.get("kind",""))}</span>',
                  esc(t.get("basis", ""))) for t in targets]
        body.append(C.section("6", "AI 검색 추천 전략 (AEO·GEO)",
            '<p class="lead">미래 고객은 네이버·구글 검색창보다 <b>AI(챗봇·생성형 검색)에게 '
            '"우리 동네 OO 잘하는 동물병원 추천해줘"</b>라고 묻습니다. AI가 이 병원을 추천하려면 '
            '<b>진료데이터가 증명한 실제 강점</b>을 기계가 읽는 <b>엔티티 신호</b>로 노출해야 합니다.</p>'
            + C.table(["AI가 인식해야 할 강점 진료", "유형", "근거(EMR 실측)"], trows)
            + C.info(
                "<b>엔티티(entity)</b> = AI·검색엔진이 이 병원을 '글자'가 아니라 <b>하나의 실체</b>로 이해하는 것. "
                "<ul style='margin:8px 0 0;padding-left:18px;font-size:13.5px;line-height:1.7'>"
                "<li><b>① 구조화 데이터</b> — schema.org <code>VeterinaryCare·medicalSpecialty</code>로 강점 진료를 코드로 선언</li>"
                "<li><b>② NAP 일관성</b> — 상호·주소·전화가 홈페이지·플레이스·지도에서 동일 → AI가 '같은 실체'로 확신</li>"
                "<li><b>③ 전문 콘텐츠</b> — 강점 진료 사례·정보를 축적 → AI가 인용할 근거</li></ul>"
                "이 셋이 갖춰질수록 '" + esc(targets[0]["keyword"]) + " 잘하는 병원' 같은 질문에서 AI 추천에 오릅니다.")
            + C.note("※ 위 타겟은 추정 키워드가 아니라 07 진료데이터가 실측한 <b>주력·고관여 진료</b>입니다 — "
                     "'실제로 많이·비싸게 보는 진료'라 AI 노출 전략의 설득력이 큽니다.")))

    # ⑦ 어떻게 분석했나 — 방법
    body.append(C.section("7", "어떻게 분석했나 — 방법", C.method_cards([
        ("① 익명화(가명 처리)", "보호자명·전화·주소를 삭제하고 환자는 솔티드 SHA-256 가명 ID로만 구분(재식별 불가)."),
        ("② 재진율·활성도", "환자별 방문 횟수로 재방문(2회+) 비율과 최근 6개월 미방문(휴면) 규모를 계산."),
        ("③ 객단가", "방문당 평균·중앙값, 환자당 합계 평균으로 매출 구조를 파악."),
        ("④ 고관여·질환믹스", "진단명별 평균 객단가 상위 5(임계=80분위)와 유입 비율 Top 8로 수익 레버·강점을 도출."),
        ("⑤ 규칙 기반 로드맵", "지표 약점→우선 과제를 가중치로 매칭해 12개월에 라운드로빈 배분(키·네트워크 불필요)."),
    ])))

    # ⑧ 우선순위 과제
    pris = rm.get("priorities", [])
    if pris:
        rows = []
        for p in pris:
            tier = ("바로", "t-good") if p.get("weight", 0) >= 3 else ("중기", "t-warn")
            item = f"[{esc(p['focus'])}] {esc(p['issue'])} → " + " · ".join(esc(a) for a in p["actions"])
            rows.append((tier, item, "", ""))
        body.append(C.section("8", "우선순위 개선 과제",
            '<p class="lead">지표 약점에서 자동 도출된 실행 과제입니다(가중치순).</p>' + C.checklist(rows)))

    # ⑨ 12개월 로드맵
    months = rm.get("months", [])
    if months:
        qcls = {1: "q1", 2: "q2", 3: "q3", 4: "q4"}
        blocks = []
        for q in (1, 2, 3, 4):
            qmonths = [m for m in months if m["quarter"] == q]
            if not qmonths:
                continue
            theme = qmonths[0]["theme"]
            mlabels = "".join(
                f'<span class="f">{m["month"]}월</span>' for m in qmonths)
            months_html = f'<div class="focusrow" style="margin-bottom:8px">{mlabels}</div>'
            # 이 분기에 배정된 집중 액션(중복 제거)
            seen, acts = set(), []
            for m in qmonths:
                for a in m.get("focus_actions", []):
                    if a not in seen:
                        seen.add(a); acts.append(a)
            focus_rows = [("집중", esc(a)) for a in acts[:4]] or [("상시", "채널 상시 운영(네이버·카카오·소셜미디어·지도·AI 검색)")]
            blocks.append(C.gquarter(qcls[q], f"{q}Q", theme, months_html, focus_rows))

        # 상시 vs 집중 2층 구조 설명
        layer_box = (
            '<div class="two" style="margin:2px 0 16px"><ul style="list-style:none;padding-left:0">'
            '<li><span class="tag t-blue">🔁 상시</span> <b>매월 반복하는 기본기.</b> '
            '검색·지도·소셜미디어가 "살아있고 관리되는 병원"으로 인식하게 하는 최소 운영입니다. '
            '손을 놓으면 노출·순위가 서서히 식습니다.</li></ul>'
            '<ul style="list-style:none;padding-left:0">'
            '<li><span class="tag t-good">🎯 집중</span> <b>이번 분기의 승부수.</b> '
            '진료데이터 약점(재진율·휴면 등)을 겨냥한 캠페인으로, 아래 분기 블록의 '
            '<span class="tag t-good" style="font-size:11px">집중</span> 항목이 그것입니다.</li></ul></div>')

        # 상시 채널 상세 표: 채널 | 매월 활동 | 유형(발행/관리)
        baseline_map = _emr.BASELINE
        brows = []
        for ch in rm.get("channels", []):
            act = baseline_map.get(ch, "")
            kind, cls = _CHANNEL_KIND.get(ch, ("운영", "t-blue"))
            brows.append((f"<b>{esc(ch)}</b>", esc(act),
                          f'<span class="tag {cls}">{esc(kind)}</span>'))
        base_tbl = ""
        if brows:
            base_tbl = (
                '<h4 style="margin:18px 0 6px;font-size:14px;color:var(--navy)">🔁 상시 채널 — 매월 유지할 기본기</h4>'
                + C.table(["채널", "매월 상시 활동", "유형"], brows)
                + C.note("‘발행’은 블로그·인스타에 <b>글/콘텐츠가 매월 올라가야</b> 하는 것, "
                         "‘관리’는 알림톡 발송·지도 정보 점검·구조화 데이터 유지처럼 <b>글이 아닌 운영</b> 작업입니다."))

        body.append(C.section("9", "12개월 마케팅 로드맵 (진료데이터 기반)",
            '<p class="lead">이 로드맵은 <b>두 층</b>입니다 — 매월 유지하는 <b>상시(기본기)</b> 위에, '
            '진료데이터 약점을 겨냥한 <b>집중(분기 승부수)</b>을 얹습니다.</p>'
            + layer_box + "".join(blocks) + base_tbl))

    # 정리
    lead_diag = mix[0]["diagnosis"] if mix else None
    summary = "<b>정리</b> — 내부 진료 데이터가 가리키는 방향: "
    bits = []
    if rev.get("revisit_rate") is not None:
        bits.append(("재진율 안정 → 신규 유입 확대" if rev["revisit_rate"] >= 0.5 else "재진율 강화(리텐션 자동화)"))
    if dorm.get("recall_target"):
        bits.append(f"휴면 {dorm['recall_target']}명 리콜")
    if lead_diag:
        bits.append(f"주력 '{lead_diag}' 특화 마케팅")
    aeo_t = rm.get("aeo", {}).get("targets", [])
    if aeo_t:
        bits.append(f"강점 진료를 엔티티로 노출해 AI 검색 추천 선점(AEO·GEO)")
    summary += ", ".join(esc(b) for b in bits) if bits else "데이터가 더 쌓이면 정밀도가 올라갑니다"
    summary += ". 외부 5축(01~06)과 함께 보면 '내부에서 무엇을 잘하나 + 외부에서 어디서 이기나'가 맞물립니다."
    body.append(C.callout(summary, good=True))

    return _wrap(clinic, ctx, body)


def _wrap(clinic, ctx, body):
    region = ctx.get("emr_meta", {}).get("region") or clinic.get("address", "")
    return page(
        title=f"{clinic['name']} 진료데이터분석",
        kicker="MEDICAL DATA ANALYSIS · 내부 데이터축",
        h1=f"{clinic['name']} 진료데이터분석",
        sub="재진율·휴면·객단가·주력질환 기반 내부 진단 + 12개월 로드맵",
        meta=[policy.TOOL_LABEL, clinic.get("date", ""), "개인정보 보호 처리 완료"],
        body_html="".join(body),
        footnotes=[
            "진료 데이터는 업로드 즉시 익명화(가명 처리)되며 원본 개인정보(이름·전화·주소)는 저장하지 않습니다.",
            policy.FOOTNOTE_METHOD, policy.DISCLAIMER_GENERIC],
        hero=_HERO_TEAL, current_no=REPORT_NO, filenames=ctx["filenames"],
    )
