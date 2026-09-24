# -*- coding: utf-8 -*-
"""06 12개월 마케팅 계획 — 작업명세 §4. 달력 고정(9월 시작)·계절성·예산·측정."""
from .. import components as C
from .. import policy
from .. import insights
from ..design import page, esc, HERO_NAVY

REPORT_NO = "06"
REPORT_LABEL = "12개월마케팅계획"

# 분기 테마 + 계절성 (작업명세 §4.4, 9월 시작 고정)
QUARTERS = [
    {"q": "q1", "name": "Q1 · 9–11월", "theme": "새는 곳부터 막는다",
     "desc": "가장 먼저 ‘새는 곳’부터 막습니다. 방문이 문의·예약으로 이어지는 전환 동선과 "
             "채널 정보(NAP) 정합성을 정비해, 이후 늘어날 유입을 놓치지 않을 그릇을 만드는 분기입니다.",
     "months": [
         ("9월", "가을 건강검진", ["홈페이지 tel·예약 버튼 정비", "네이버 예약 연동", "NAP(주소·전화) 통일"]),
         ("10월", "예방접종", ["카카오 상담 창구 개설", "플레이스 정보·소식 갱신", "리뷰 답글 루틴 시작"]),
         ("11월", "환절기 호흡기", ["FAQ·구조화 데이터 삽입", "블로그 예방접종 시리즈", "전환 지표 대시보드"]),
     ],
     "focus": [("전환 동선 완성", "홈페이지 전화·예약 버튼, 네이버 예약 연동, 카카오 상담 창구를 열어 방문→문의 누수를 막습니다."),
               ("채널 정합성(NAP) 통일", "주소·전화·병원명을 모든 채널에서 일치시켜 검색·지도 신뢰도와 노출 순위를 높입니다.")]},
    {"q": "q2", "name": "Q2 · 12–2월", "theme": "있는 평판을 무기로",
     "desc": "겨울 비수기는 ‘자산 축적기’입니다. 그동안 쌓인 리뷰·미담을 콘텐츠로 자산화하고, "
             "부정 리뷰 응대 체계를 갖춰 평판을 방어하면서 사회적 증거를 키웁니다.",
     "months": [
         ("12월", "연말 종합검진", ["대표 미담 콘텐츠화", "구글 부정 리뷰 응대 체계", "연말 검진 캠페인"]),
         ("1월", "겨울 관절·심장", ["카카오맵 후기 ON", "수술 미담 케이스 스토리", "재방문 알림톡"]),
         ("2월", "슬개골 수술", ["리뷰 요청 자동화", "인스타 전문성 릴스", "만족도 설문"]),
     ],
     "focus": [("리뷰·미담 자산화", "대표 미담·수술 케이스를 스토리 콘텐츠로 만들고 리뷰 요청을 자동화해 검증된 평판을 노출로 바꿉니다."),
               ("부정 응대 프로세스", "구글·네이버 부정 리뷰에 24~48시간 내 정중히 응대하는 표준 절차를 만들어 평판을 방어합니다.")]},
    {"q": "q3", "name": "Q3 · 3–5월", "theme": "새로운 유입원을 연다",
     "desc": "봄은 심장사상충·알레르기로 병원 수요가 폭증하는 최대 성수기입니다. 광고·콘텐츠 도달을 "
             "최대로 끌어올리고 의뢰처 리퍼럴을 가동해 신규 유입을 최대한 흡수합니다.",
     "months": [
         ("3월", "봄 알레르기", ["성수기 광고 세팅", "블로그·인스타 도달 확대", "신규층 타겟 캠페인"]),
         ("4월", "심장사상충 예방", ["예방 캠페인 집중 집행", "예약 전환 최적화", "리퍼럴 안내 강화"]),
         ("5월", "봄 성수기", ["의뢰처 1차 리퍼럴 프로그램", "실사진·후기 대량 확보", "검색 노출 점검"]),
     ],
     "focus": [("성수기 도달 극대화", "예방 캠페인 광고를 집중 집행하고 블로그·인스타 발행을 늘려 검색·SNS 도달을 확대합니다."),
               ("의뢰처 리퍼럴 가동", "인근 1차 병원 대상 협진·회송 프로그램을 가동해 안정적 초진 유입 파이프라인을 엽니다.")]},
    {"q": "q4", "name": "Q4 · 6–8월", "theme": "광역으로 넓히고 시스템화",
     "desc": "여름 응급(열사병·피부) 수요를 흡수하고, 한 해 성과를 결산해 차년도 계획으로 정착시키는 마무리 분기입니다.",
     "months": [
         ("6월", "여름 피부·진드기", ["여름 응급 안내", "24시 진료 노출 강화", "재진단 준비"]),
         ("7월", "열사병·응급", ["응급 키워드 상위 노출", "CRM 재방문 캠페인", "채널 성과 결산"]),
         ("8월", "연간 재진단", ["연간 성과 리뷰", "차년도 계획 수립", "전체 채널 재진단"]),
     ],
     "focus": [("여름 응급 수요 흡수", "24시·응급 진료를 응급 키워드 상위에 노출하고 여름철 건강 안내 콘텐츠를 배포합니다."),
               ("연간 재진단·정착", "채널 성과를 결산하고 6개 리포트를 재생성해 차년도 목표를 갱신합니다.")]},
]

STRATEGY_AXES = [
    ("축 1 · 새지 않게 연결", "있는 방문을 문의·예약으로",
     "홈페이지 전화 바로걸기·예약, 카카오 상담 창구, 네이버 예약 연동으로 방문→문의 누수를 막습니다."),
    ("축 2 · 있는 자산을 퍼뜨림", "검증된 평판을 노출로",
     "리뷰·미담 자산화, 구글·네이버 부정 응대, 카카오맵 후기 켜기, 자주 묻는 질문 정비로 평판을 노출로 바꿉니다."),
    ("축 3 · 더 넓게 알림", "의뢰처·신규층으로 도달",
     "인스타·블로그 도달 확대, 인근 1차 리퍼럴, 미등록 신규 반려가구로 도달 범위를 넓힙니다."),
]

CHANNELS_MATRIX = ["홈페이지", "네이버 플레이스", "블로그", "인스타", "카카오톡", "리퍼럴/의뢰처"]
# 채널×분기 강도 (hi/mid/lo)
MATRIX = {
    "홈페이지":       ["hi", "mid", "mid", "mid"],
    "네이버 플레이스": ["hi", "hi", "hi", "mid"],
    "블로그":         ["mid", "mid", "hi", "mid"],
    "인스타":         ["lo", "mid", "hi", "mid"],
    "카카오톡":       ["hi", "mid", "mid", "mid"],
    "리퍼럴/의뢰처":   ["lo", "lo", "hi", "mid"],
}


def _budget(data, ctx):
    """예산 기본 35/30/20/15, 의뢰처 풍부 & 도달 약하면 리퍼럴 상향(작업명세 §4.5)."""
    b = {"콘텐츠·평판": 35, "광고": 30, "리퍼럴": 20, "고객 관리(재방문)": 15}
    k = ctx["comp"]
    if k["subject_tier"] == 2 and k["referral_count"] >= 20:
        b["리퍼럴"] = 22; b["광고"] = 28
    return b


def build(data, ctx):
    clinic = data["clinic"]
    body = []

    # ── 진단 데이터 요약(전략 개요 서술·전략축에 녹임) ──
    name = clinic["name"]
    k = ctx["comp"]
    rv = data.get("review", {})
    r_chs = rv.get("channels", [])
    total_rv = sum(c.get("review_count", 0) for c in r_chs)
    referral = k.get("referral_count") or 0
    g = next((c for c in r_chs if "구글" in (c.get("name") or "")
              or "google" in (c.get("name", "").lower())), None)
    g_rating = g.get("rating") if g else None
    axes = insights.derive_strengths(data, ctx)
    top_axes = " · ".join(a["axis"] for a in axes[:4]) or "진료·평판·입지"

    # ① 전략 개요 — 핵심 방향(진단 기반 서술) + 세 전략 축
    direction = (
        f"<b>핵심 방향:</b> 진단 결과, <b>{esc(name)}은 강점({esc(top_axes)})은 이미 상위권</b>입니다. "
        "부족한 것은 콘텐츠나 실력이 아니라, ①있는 방문을 문의·예약으로 잇는 <b>전환 동선</b>, "
        + (f"②리뷰 {total_rv:,}개 등 있는 평판을 새는 곳 없이 <b>노출</b>" if total_rv
           else "②있는 평판을 새는 곳 없이 <b>노출</b>")
        + (f"(특히 구글 {g_rating} 회복)" if g_rating else "")
        + ", ③"
        + (f"의뢰처(1차 {referral}곳)·" if referral else "")
        + "신규층으로 <b>도달을 넓히는 것</b>입니다. "
        "그래서 이 계획은 새로 만들기보다 <b>있는 강점을 연결·증폭·확장해 환자 유입·매출로 잇는 데</b> 집중합니다.")

    pillars_data = [
        ("축 1 · 전환", "새지 않게 연결",
         "전 채널 문의 동선을 ‘전화(탭)+예약+카카오 상담’으로 통일하고, 상호·주소·전화 표기 일치·"
         "구글 프로필·카카오맵 후기를 정비해 방문이 문의·예약으로 흐르게 합니다."),
        ("축 2 · 평판 증폭", "있는 자산을 퍼뜨림",
         (f"네이버 리뷰 {total_rv:,}개·" if total_rv else "")
         + "미담·실사진·전문 콘텐츠를 답글·재가공·광고로 자산화하고, "
         + (f"구글 {g_rating}·저평가된 채널 평판을 끌어올립니다." if g_rating else "채널 평판을 노출로 바꿉니다.")),
        ("축 3 · 도달 확장", "더 넓게 알림",
         (f"의뢰처(1차 {referral}곳) 리퍼럴 네트워크, " if referral else "")
         + "지역 타깃 인스타·릴스, 미등록 신규 반려가구까지 새로운 유입원을 여는 성장 트랙입니다."),
    ]
    overview = (C.callout(direction, good=True)
                + '<p class="lead">이를 세 개의 전략 축으로 정리하면 다음과 같습니다.</p>'
                + C.pillars([(lab, C.plainify(title), C.plainify(desc)) for lab, title, desc in pillars_data], cols=3))
    body.append(C.section("1", "전략 개요", overview))

    # ② 연간 KPI 표
    kpi_rows = insights.derive_kpis(data, ctx)
    body.append(C.section("2", "연간 목표 (KPI)", C.table(
        ["지표", "현재(진단값)", "12개월 목표", "연결 전략축"], kpi_rows, num_cols=set()) +
        C.info("<b>선행지표</b>(마케팅이 직접 움직임: 노출·문의·리뷰수) vs "
               "<b>후행지표</b>(초진·재방문·2차 의뢰)를 구분해 측정합니다.")))

    # ③ 연간 타임라인
    tl = '<div class="timeline">' + "".join(
        f'<div class="tl {q["q"]}"><div class="qn">{esc(q["name"])}</div>'
        f'<h4>{esc(q["theme"].split("(")[0].strip())}</h4>'
        f'<p>{esc(q["months"][0][1])} · {esc(q["months"][1][1])} · {esc(q["months"][2][1])}</p></div>'
        for q in QUARTERS) + "</div>"
    body.append(C.section("3", "연간 로드맵 한눈에", tl))

    # ④ 분기별 상세 — 진단(03·04) 개선안을 tier별로 분기에 배치(참조식)
    from .. import scoring as _sc
    from .r03_marketing import CHANNEL_LABELS as _CL
    _diag = {"now": [], "mid": [], "long": []}
    for ch in data.get("marketing", {}).get("channels", []):
        lab = _CL.get(ch.get("type"), ch.get("type", "채널"))
        for a in ch.get("actions", []):
            r = _sc.score_action(a.get("effort"), a.get("impact"), a.get("cost"))
            _diag[r["tier"]].append(f"[{lab}] " + C.plainify(a.get("title", "개선")))
    for a in data.get("review", {}).get("actions", []):
        r = _sc.score_action(a.get("effort"), a.get("impact"), a.get("cost"))
        _diag[r["tier"]].append("[리뷰] " + C.plainify(a.get("title", "개선")))
    _mid = _diag["mid"]; _h = len(_mid) // 2 + len(_mid) % 2
    _q_acts = {"q1": _diag["now"][:6], "q2": _mid[:_h][:6], "q3": _mid[_h:][:6], "q4": _diag["long"][:6]}

    detail = []
    for q in QUARTERS:
        da = _q_acts.get(q["q"], [])
        # 계절 초점(월별 시즌을 분기 상단에 명시 — 타임라인·참조와 일치)
        seasons = " · ".join(m[1] for m in q["months"])
        season_line = f'<p class="lead" style="margin:0 0 6px"><b>🗓 계절 초점:</b> {esc(seasons)} 시즌</p>'
        intro = (f'<p style="margin:0 0 10px;color:var(--muted);font-size:14px">{esc(C.plainify(q["desc"]))}</p>'
                 if q.get("desc") else "")
        diag_block = ""
        if da:
            diag_block = ('<div class="callout" style="margin:0 0 12px"><b>🔧 이 병원 우선 실행 (진단 기반)</b>'
                          '<ul class="rdul" style="margin:6px 0 0">'
                          + "".join(f"<li>{esc(x)}</li>" for x in da) + "</ul></div>")
        mh = (season_line + intro + diag_block + '<div class="months">' + "".join(
            f'<div class="mbox"><div class="mh">{esc(m[0])}<span class="season">{esc(m[1])}</span></div>'
            f'<ul>{"".join(f"<li>{esc(C.plainify(x))}</li>" for x in m[2])}</ul></div>'
            for m in q["months"]) + "</div>")
        focus_rows = [(C.plainify(lab), esc(C.plainify(desc))) for lab, desc in q["focus"]]
        detail.append(C.gquarter(q["q"], q["theme"], q["name"], mh, focus_rows))
    body.append(C.section("4", "분기별 실행 계획", "".join(detail)))

    # ⑤ 매월 상시 운영 루틴
    body.append(C.section("5", "매월 반복하는 상시 운영", C.two_col_lists(
        ["블로그·인스타 정기 발행", "리뷰 답글 100% 응대", "릴스/숏폼 제작", "플레이스 소식 갱신"],
        ["재방문 알림톡 발송", "예약·문의 전환 점검", "월간 대시보드 리뷰", "부정 리뷰 모니터링"])))

    # ⑥ 채널별 12개월 초점 매트릭스
    mrows = []
    for ch in CHANNELS_MATRIX:
        cells = MATRIX.get(ch, ["mid"] * 4)
        row = [ch] + [f'<span class="d d-{c}"></span>' for c in cells]
        mrows.append(row)
    body.append(C.section("6", "채널별 12개월 초점",
                          '<p class="lead">채널마다 분기별로 <b>얼마나 힘을 쏟을지</b>(운영 강도)를 색으로 나타냈습니다. '
                          '‘집중’ 분기의 채널부터 손대면 됩니다.</p>'
                          + '<div class="dmatrix">' + C.table(["채널", "Q1", "Q2", "Q3", "Q4"], mrows) + "</div>" +
                          C.info('<b>색상 의미</b> — '
                                 '<span class="d d-hi"></span> <b>집중</b>(그 분기 최우선 채널) · '
                                 '<span class="d d-mid"></span> <b>유지</b>(평소대로 꾸준히) · '
                                 '<span class="d d-lo"></span> <b>최소</b>(여력 될 때만)')))

    # ⑦ 예산 배분
    b = _budget(data, ctx)
    bud = '<div class="budget">' + "".join(
        f'<div class="bcard"><div class="blab">{esc(name)}</div>'
        f'<div class="btrack"><div class="bbar" style="width:{pct}%"></div></div>'
        f'<div class="bval">{pct}%</div></div>'
        for name, pct in b.items()) + "</div>"
    body.append(C.section("7", "예산 배분 가이드", bud +
                          C.info("성수기(3~5월)에는 광고·콘텐츠 가중을 권장합니다. "
                                 "의뢰처가 풍부하고 도달이 약하면 리퍼럴 비중을 상향합니다.")))

    # ⑧ 측정 체계
    body.append(C.section("8", "측정·리뷰 체계", C.table(
        ["주기", "무엇을", "지표"],
        [["월", "선행지표", "노출·문의·리뷰수·전환율"],
         ["분기", "후행지표 + 전략 점검", "초진·재방문·2차 의뢰"],
         ["연간", "전체 재진단", "6개 리포트 재생성·목표 갱신"]])))

    # ⑨ 실행 체크리스트 (진단에서 나온 개선안 → 담당·기한 관리)
    from .. import scoring
    from .r03_marketing import CHANNEL_LABELS
    tier_tag = {"now": ("바로", "t-bad"), "mid": ("중기", "t-warn"), "long": ("장기", "t-blue")}
    order = {"now": 0, "mid": 1, "long": 2}
    acts = []
    for ch in data.get("marketing", {}).get("channels", []):
        lab = CHANNEL_LABELS.get(ch.get("type"), ch.get("type", "채널"))
        for a in ch.get("actions", []):
            acts.append((a, f"[{lab}] " + a.get("title", "개선")))
    for a in data.get("review", {}).get("actions", []):
        acts.append((a, "[리뷰] " + a.get("title", "개선")))
    if acts:
        scored = []
        for a, title in acts:
            r = scoring.score_action(a.get("effort"), a.get("impact"), a.get("cost"))
            scored.append((order[r["tier"]], tier_tag[r["tier"]], title))
        scored.sort(key=lambda x: x[0])
        rows = [(tag, C.plainify(title), "", "") for _, tag, title in scored]
        body.append(C.divider("심화 — 실행 체크리스트",
                              "참조 리포트에 없는 추가 도구: 진단 개선안을 우선순위로 정렬해 담당·기한을 관리합니다."))
        body.append(C.section("9", "실행 체크리스트",
                              '<p class="lead">진단에서 도출된 개선안을 우선순위(바로/중기/장기)로 정렬했습니다. 담당·기한을 채워 실행 관리하세요.</p>'
                              + C.checklist(rows)))

    body.append(C.callout(
        "<b>정리</b> — 강점은 이미 충분합니다. 관건은 <b>새지 않게 연결하고, 있는 자산을 퍼뜨리고, 더 넓게 알리는</b> 실행입니다. "
        "Q1(9월)의 전환 동선·정보 정합성 정비 같은 ‘바로’ 항목부터 시작해, "
        "새는 곳 막기 → 평판 무기화 → 새 유입원 → 광역 시스템화의 순환으로 강점을 매출로 전환합니다.", good=True))

    return page(
        title=f"{clinic['name']} 12개월 마케팅 계획",
        kicker="12-MONTH MARKETING PLAN",
        h1=f"{clinic['name']} 12개월 마케팅 계획",
        sub="강점 기반 실행 로드맵 · 9월 시작 · 계절성 반영",
        meta=[policy.TOOL_LABEL, clinic.get("date", ""), "Q1 9월 시작"],
        body_html="".join(body),
        footnotes=[policy.FOOTNOTE_PLAN, policy.DISCLAIMER_GENERIC],
        hero=HERO_NAVY, current_no=REPORT_NO, filenames=ctx["filenames"],
    )
