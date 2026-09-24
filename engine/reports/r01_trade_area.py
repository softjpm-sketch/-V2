# -*- coding: utf-8 -*-
"""01 상권분석 — 방법론 §1 / 프롬프트 B안 상권 규칙.

참조 리포트(인천 스카이) 수준의 서술을 '데이터로 자동 생성'한다.
스냅샷 출처 콜아웃·핵심 한 줄·종합진단 설명·방법 카드·유리한점(다블록)·
유의점(다블록)·활용 로드맵(3불릿)·정리를 모두 입력 데이터에서 템플릿으로 만든다.
값이 없는 항목은 자연스럽게 생략(결측 내성).
"""
from .. import components as C
from .. import policy
from ..design import page, esc, HERO_NAVY

REPORT_NO = "01"
REPORT_LABEL = "상권분석"


def _sigungu(region, address):
    """region_label 또는 주소에서 시군구명 추출('남동구')."""
    if region:
        parts = region.split()
        if len(parts) >= 2:
            return parts[1]
    for tok in (address or "").split():
        if tok.endswith("구") or tok.endswith("군") or (
                tok.endswith("시") and "광역시" not in tok and "특별시" not in tok and "자치시" not in tok):
            return tok
    return ""


def _dong(region):
    parts = (region or "").split()
    return parts[2] if len(parts) >= 3 else None


def build(data, ctx):
    clinic = data["clinic"]
    t = ctx["trade"]
    ta_in = data.get("trade_area", {})
    k = ctx.get("comp", {})

    # ── 데이터 준비 ──
    region = ta_in.get("region_label")
    gu = _sigungu(region, clinic.get("address"))
    dong = _dong(region)
    date = clinic.get("date", "")
    sales = ta_in.get("monthly_sales_manwon")
    foot = ta_in.get("daily_footfall")
    region_clinics = ta_in.get("region_clinics")     # 상권영역(동) 내 업소수
    population = ta_in.get("population")
    hh = ta_in.get("households")
    station = t.get("nearest_station")
    walk = t.get("walk_min")
    station_m = ta_in.get("nearest_station_m")
    pet_hh = t.get("pet_households")
    reg = t.get("registered_pets")
    clinics = t.get("clinics_in_region")
    sat = t.get("saturation")
    grade = t.get("grade")
    glabel = t.get("grade_label")
    reg_sat = t.get("reg_saturation")
    area_type = ta_in.get("area_type")
    by = {m["key"]: m for m in t["metrics"]}
    area_score = by.get("ta_area_type", {}).get("score")
    acc_score = by.get("ta_accessibility", {}).get("score")

    resid = bool(area_type in ("주거 밀집형", "주거·상업 혼합") or ta_in.get("apartment_dense"))
    loose = grade in ("A", "B")
    under_reg = bool(pet_hh and reg and pet_hh > reg)
    gu_label = f"{gu} 동물병원" if gu else "지역 동물병원"
    body = []

    # ═══ 1. 상권 스냅샷 ═══
    snap_lead = (f'<p class="lead">통계청·검역본부·카카오·소상공인 상권정보를 결합해 파악한 '
                 f'{esc(gu) + " " if gu else ""}상권 현황입니다.</p>')
    snap = C.snap([
        (f"{pet_hh:,}" if pet_hh else "–", "반려가구(추정)"),
        (f"{reg:,}" if reg else "–", "등록 반려동물"),
        (f"{clinics:,}곳" if clinics else "–", gu_label),
        (f"{grade}등급" if grade else "–", "시장 포화도"),
    ])
    src_bits = []
    if sales:
        src_bits.append(f"동물병원 업종 월평균 추정매출 <b>{sales:,}만원</b>")
    if foot:
        src_bits.append(f"일일 유동인구 <b>{foot:,}명</b>")
    if region_clinics:
        src_bits.append(f"동물병원 업소 <b>{region_clinics}개</b> 밀집")
    src_html = ""
    if src_bits:
        rtxt = f" · {esc(dong or gu)} 상권영역" if (dong or gu) else ""
        dtxt = f" ({esc(date)} 기준)" if date else ""
        src_html = C.info(f"<b>소상공인 상권정보{rtxt}{dtxt}</b>: " + " · ".join(src_bits))
    # 핵심 한 줄 (자동 생성)
    core = '핵심 한 줄: "'
    core += "정주 반려가구가 두텁고(주거 밀집형), " if resid else ""
    core += (f"병원당 시장이 <b>전국 평균보다 여유 있는</b>(포화도 {grade}·{glabel}) 우호적 상권"
             if loose else f"병원당 경쟁이 있는(포화도 {grade or '–'}·{glabel or '–'}) 도전적 상권")
    core += '"입니다. '
    core += "유동보다 <b>동네 반려가구 리텐션</b>이 핵심이고, " if resid else ""
    core += ("등록 반려동물이 추정치보다 적어 <b>미등록 신규층 발굴</b> 여지가 큽니다."
             if under_reg else "안정적 수요 기반을 갖췄습니다.")
    core_html = C.callout(core, good=loose)
    body.append(C.section("1", "상권 스냅샷", snap_lead + snap + src_html + core_html))

    # ═══ 2. 한눈에 보는 종합 진단 ═══
    axis_txt = (f"상권 종합 <b>{t['axis_score']} / 20</b> · 충실도 {t['coverage']}%"
                if t["axis_score"] is not None else "측정 데이터 부족")
    lead2 = (f'<p class="lead">상권 축(20점 만점)을 구성하는 {len(t["metrics"])}개 지표를 항목별로 평가했습니다. '
             f'{axis_txt}.</p>')
    # 점수 막대(작은 설명 = 벤치마크 대비 서술)
    disp = []
    for m in t["metrics"]:
        key, note = m["key"], m.get("note", "")
        if key == "ta_pet_households" and sat:
            cmp = "위" if sat >= 1100 else "아래"
            note = f"포화도 {sat:,} 반려가구/병원 (전국평균 ≈1,100 {cmp})"
            if loose and clinics:
                note += f" — 여유 있으나 {clinics}곳 경쟁 존재"
        elif key == "ta_footfall" and foot:
            note = f"일일 유동인구 약 {round(foot, -3):,}명 — 기준(10만) {'상회' if foot >= 100000 else '미달'}"
        elif key == "ta_income" and sales:
            note = f"동물병원 업종 월평균 추정매출 {sales:,}만원 (전국 평균 4,500만 {'상회' if sales >= 4500 else '미달'})"
        elif key == "ta_accessibility" and acc_score is not None and note != "미입력":
            bits = []
            if ta_in.get("parking"):
                bits.append("주차")
            if ta_in.get("apartment_dense"):
                bits.append("아파트 밀집")
            if station:
                bits.append(f"역세권({station} 도보 {walk}분" + (f"·{station_m}m" if station_m else "") + ")")
            if bits:
                note = " · ".join(bits) + (" 3박자" if len(bits) >= 3 else "")
        elif key == "ta_area_type" and area_type:
            note = area_type
        disp.append({**m, "note": note})
    diag = lead2 + C.scoregrid(disp)
    if area_type and area_score is not None:
        best = "가장 유리한" if area_score >= 80 else "유리한"
        diag += C.callout(
            f"상권 유형은 <b>{esc(area_type)}({area_score}점)</b> — 반려동물은 정주 주거인구가 핵심이라 "
            f"동물병원에 {best} 유형입니다.", good=(area_score >= 70))
    # 포화도 개념 박스
    sat_line = (f"{gu or '지역'}은 {pet_hh:,} ÷ {clinics} = <b>{sat:,}</b>"
                if (pet_hh and clinics and sat) else "반려가구 ÷ 동물병원 수")
    diag += (
        '<div class="card" style="margin-top:12px;border-left:4px solid var(--blue)">'
        '<h4 style="margin:0 0 6px;font-size:15px;color:var(--navy)">📖 "시장 포화도"란?</h4>'
        '<p style="font-size:14px;margin:0 0 8px">동물병원 <b>한 곳이 나눠 갖는 반려가구</b>가 몇이냐를 재는 지표입니다. '
        '식당에 비유하면 동네 손님(반려가구)을 식당(동물병원) 수로 나눈 <b>"식당 하나당 손님 수"</b>예요.</p>'
        f'<p style="font-size:14px;margin:0 0 8px"><b>포화도 = 반려가구 ÷ 동물병원 수</b> → {sat_line}</p>'
        '<div class="two"><ul>'
        '<li><b>클수록</b> 손님 많고 병원 적음 → 여유(블루오션)</li>'
        '<li><b>작을수록</b> 손님 적고 병원 많음 → 포화(레드오션)</li></ul><ul>'
        '<li>전국평균 ≈ 1,100</li>'
        '<li>등급: A≥1,500 · B≥1,100 · C≥800 · D&lt;800</li></ul></div>'
        + (f'<p style="font-size:13px;margin:8px 0 0;color:#5b6675">다만 실제 등록 반려동물 기준'
           f'(등록기반 {reg_sat})으로 보면 더 빡빡 — <b>미등록 신규층 발굴</b> 여지가 큽니다.</p>'
           if (under_reg and reg_sat) else "")
        + '</div>')
    if t.get("hh_basis") == "등록수 기반 추정":
        diag += C.info(
            f"<b>산정 근거</b> — 가구수 자료가 없어 <b>등록 반려동물수 기반</b>으로 반려가구를 추정했습니다"
            f"(등록기반 포화도 {t.get('reg_saturation', '–')}).")
    body.append(C.section("2", "한눈에 보는 종합 진단", diag))

    # ═══ 3. 어떻게 분석했나 — 방법 ═══
    cards = []
    if hh:
        pop_txt = f"{gu or '시군구'} 인구 {population:,}명·가구 {hh:,}세대를 조회하고" if population else \
                  f"시군구 가구수 {hh:,}세대를 자동 조회하고"
        cards.append(("① 인구·가구 (통계청 SGIS)",
                      f"주소 → {pop_txt}, 반려동물 양육률(28%)로 반려가구 {pet_hh:,}를 추정했습니다."))
        cards.append(("② 등록 반려동물 (검역본부)",
                      f"농림축산검역본부 반려동물 등록수" + (f" {reg:,}마리" if reg else "") +
                      "(실측)를 병행 확인해, 추정과 실측을 함께 봅니다."))
    else:
        cards.append(("① 반려동물 등록수 (검역본부)",
                      f"행정구역별 등록 반려동물수" + (f" {reg:,}마리" if reg else "") +
                      "를 시장 규모 근거로 사용합니다(개 위주 하한, SGIS 키 연결 시 가구수 기반 정석 계산)."))
    m3 = f"지역 동물병원 {clinics}곳을 집계해 포화도를 계산하고" if clinics else "지역 동물병원 수를 집계해 포화도를 계산하고"
    m3 += (f", 최근접 지하철역({station})까지 도보시간을 자동 산출했습니다." if station else ".")
    cards.append(("③ 병원수·입지 (카카오맵)", m3))
    if sales or foot:
        rtxt = f"({esc(dong or gu)} 상권영역)" if (dong or gu) else ""
        m4 = f"소상공인 상권정보 간단분석 리포트{rtxt}에서 동물병원 업종 " + " · ".join(filter(None, [
            f"추정매출 {sales:,}만원" if sales else None,
            f"유동인구 {foot:,}명" if foot else None,
            f"업소수 {region_clinics}개" if region_clinics else None,
        ])) + "·상권유형을 추출해 소비력과 활력을 평가했습니다."
        cards.append(("④ 매출·유동인구 (상권정보)", m4))
    else:
        cards.append(("④ 매출·유동인구 (상권정보)",
                      "간단분석 PDF를 넣으면 동물병원 업종 추정매출·유동인구·상권유형을 자동 추출합니다."))
    body.append(C.section("3", "어떻게 분석했나 — 방법",
        '<p class="lead">"느낌"이 아니라 공공데이터와 실측으로 판단하기 위해, 여러 출처를 결합했습니다.</p>'
        + C.method_cards(cards)))

    # ═══ 4. 어떤 기준으로 봤나 — 평가 항목 ═══
    def _res(score):
        if score is None:
            return ("미측정", "t-warn")
        return ("우수", "t-good") if score >= 70 else (("양호", "t-warn") if score >= 45 else ("개선", "t-bad"))
    crit = []
    if pet_hh:
        crit.append(("시장 규모", f"반경 상권에 반려가구가 충분한가? (추정 {pet_hh:,}가구)",
                     _res(by.get("ta_pet_households", {}).get("score"))))
    crit.append(("시장 포화도",
                 f"병원당 반려가구가 여유 있는가? ({sat:,} vs 전국평균 ≈1,100)" if sat else "병원당 수요가 여유 있는가?",
                 _res(by.get("ta_pet_households", {}).get("score"))))
    if by.get("ta_income", {}).get("score") is not None:
        crit.append(("소득·소비력", f"업종 추정매출이 높은가? ({sales:,}만 vs 전국 평균 4,500만)" if sales else "업종 추정매출이 높은가?",
                     _res(by["ta_income"]["score"])))
    if by.get("ta_footfall", {}).get("score") is not None:
        crit.append(("유동인구", f"상권 활력이 있는가? (일 {round(foot,-3):,}명)" if foot else "상권 활력이 있는가?",
                     _res(by["ta_footfall"]["score"])))
    if acc_score is not None:
        crit.append(("입지·접근성", "주차·역세권·주거밀집이 갖춰졌는가?", _res(acc_score)))
    if area_score is not None:
        crit.append(("상권 유형", f"정주 반려가구 중심인가? ({area_type})" if area_type else "정주 반려가구 중심인가?",
                     _res(area_score)))
    if reg:
        crit.append(("등록 실측", f"등록 반려동물 규모는? ({reg:,}마리, 개 위주 하한)", ("참고", "t-blue")))
    body.append(C.section("4", "어떤 기준으로 봤나 — 평가 항목",
                          '<p class="lead">판단에 쓴 실제 지표와 비교 기준입니다 — "왜 이런 결론인지"의 근거.</p>'
                          + C.criteria_table(crit)))

    # ═══ 5. 유리한 점 (상권 강점) ═══
    fnd = []
    if loose and sat:
        fnd.append(C.finding(
            f"시장이 전국 평균보다 여유 있다 (포화도 {grade}·{glabel})",
            f"병원당 반려가구 <b>{sat:,}</b>으로 전국 평균(≈1,100)을 웃돕니다. "
            + (f"{clinics}개 병원이 있어도 " if clinics else "") +
            "수요 기반이 이를 받쳐주는, 레드오션은 아닌 상권입니다.", "g", src="상권"))
    if resid:
        at_txt = f"{esc(area_type)}({area_score}점)" if area_score is not None else "주거 밀집형"
        fnd.append(C.finding(
            "주거 밀집형 — 동물병원 최적 유형",
            f"반려동물 진료는 정주 주거인구가 핵심 수요입니다. {esc(gu) + ' 상권은 ' if gu else '이 상권은 '}"
            f"{at_txt}이라, 뜨내기 유동보다 <b>단골로 전환되는 정주 고객</b>이 두텁습니다.", "g", src="상권"))
    acc_bits = []
    if ta_in.get("parking"):
        acc_bits.append("주차 가능")
    if ta_in.get("apartment_dense"):
        acc_bits.append("아파트 밀집")
    if station:
        acc_bits.append(f"{station} 도보 {walk}분" + (f"({station_m}m)" if station_m else ""))
    if len(acc_bits) >= 2:
        title_acc = f"접근성 {len(acc_bits)}박자 — " + "·".join(x.split()[0] for x in acc_bits)
        fnd.append(C.finding(
            title_acc,
            " + ".join(acc_bits) + "으로, 처음 오는 보호자도 응급 상황에 찾아오기 쉽습니다."
            + (f" 입지 점수 {acc_score}점." if acc_score is not None else ""), "g", src="상권"))
    if sales and foot:
        fnd.append(C.finding(
            "소비력·상권 활력 상위",
            f"업종 월평균 추정매출 {sales:,}만원, 일일 유동인구 약 {round(foot,-3):,}명으로 "
            "소비 여력과 상권 활력이 모두 전국 기준을 상회합니다.", "g", src="상권"))
    if not fnd:
        fnd.append(C.finding("추가 입력 시 강점 도출", "월매출·유동인구·상권유형을 입력하면 유리한 점이 자동 도출됩니다.", "w", src="상권"))
    body.append(C.section("5", "유리한 점", "".join(fnd), subtitle="상권 강점"))

    # ═══ 6. 유의할 점 · 기회 (상권 리스크) ═══
    warn = []
    if loose:
        loc = f"{esc(gu)} 전체 {clinics}개 병원" if (gu and clinics) else (f"반경 내 {clinics}개 병원" if clinics else "인근 병원")
        if region_clinics and dong:
            loc += f", 특히 {esc(dong)} 상권영역에만 동물병원 업소 <b>{region_clinics}개</b>가 밀집"
        warn.append(C.finding(
            "블루오션(A)까지는 아니다 — 국지 경쟁 밀집",
            f"포화도 {grade}({glabel})는 여유가 있다는 뜻이지 무경쟁은 아닙니다. {loc}해 있어, "
            "상권 우위만 믿기보다 <b>차별화(강점·평판)</b>가 함께 가야 합니다.", "w", src="상권"))
    else:
        warn.append(C.finding("포화 구간 — 차별화 필요",
                              f"포화도 {sat:,}로 낮은 편이라 전문성·평판 차별화로 점유율을 확보해야 합니다." if sat else
                              "포화도 산출을 위한 데이터가 부족합니다.", "w", src="상권"))
    if under_reg:
        warn.append(C.finding(
            "등록 반려동물이 추정보다 적다 → 미등록 신규층 기회",
            f"추정 반려가구 {pet_hh:,} 대비 실제 등록은 {reg:,}마리로, 등록기반 포화도는 "
            f"{reg_sat}(전국평균 아래)입니다. 이는 <b>미등록·잠재 반려가구가 상당수</b>임을 시사 — "
            "등록 캠페인·신규 발굴 여지가 큽니다.", "g", src="상권"))
    if resid:
        warn.append(C.finding(
            "유동보다 '정주 리텐션'이 승부처",
            "주거 밀집형 상권은 신규 유입 광고보다, 한 번 온 보호자를 단골로 붙잡는 "
            "<b>CRM(재방문·정기검진·알림)</b>이 매출을 좌우합니다.", "w", src="상권"))
    if not warn:
        warn.append(C.finding("데이터 충실도 보완", f"현재 상권축 충실도 {t['coverage']}%. 지표를 더 넣으면 정밀도가 올라갑니다.", "w", src="상권"))
    body.append(C.section("6", "유의할 점 · 기회", "".join(warn), subtitle="상권 리스크"))

    # ═══ 7. 상권 활용 전략 로드맵 ═══
    accessibility_hook = (f'"{station} 도보 {walk}분 · 주차 완비" 접근성을 플레이스·광고 문구로 고정'
                          if station else '"주차 완비·접근성" 강점을 플레이스·광고 문구로 고정')
    now_bul = ["반경 1km 아파트 단지 타깃 — 입주민 채널·단지 게시판·지역맘카페",
               accessibility_hook, "24시·응급 키워드로 야간 상권 수요 흡수"]
    if under_reg:
        mid_first = (f"등록 반려동물 {round(reg/10000,1)}만 vs 추정 {round(pet_hh/10000,1)}만 — "
                     "미등록층 대상 '동물등록+건강검진' 패키지")
    else:
        mid_first = "신규·미등록 보호자 대상 '동물등록+건강검진' 패키지"
    mid_bul = [mid_first, "신규 입주·전입 가구 타깃 웰컴 프로모션(정주 리텐션 시작점)",
               "재방문·정기검진 알림(카카오 알림톡)으로 단골 전환"]
    long_bul = [f"포화도 {grade}(여유)를 활용해 2차 진료권(3km) 리퍼럴 네트워크 확대" if loose else
                "전문성·평판을 앞세워 인접 상권으로 도달 확대",
                "주변 1차 병원과 의뢰 관계 구축(영상진단·중환자 특화 강점 연계)",
                "분기별 상권·경쟁 재진단으로 포화도 변화 모니터링"]
    strong = "상권의 강점(" + "·".join(filter(None, [
        "주거밀집" if resid else None,
        "접근성" if (acc_score is not None and acc_score >= 70) else None,
        "시장 여유" if loose else None])) + ")을 마케팅으로 전환하는 순서입니다."
    body.append(C.section("7", "상권 활용 전략 로드맵",
                          f'<p class="lead">{strong}</p>' + C.roadmap([
                              ("now", "정주 반려가구 공략 (즉시)", now_bul, ""),
                              ("mid", "미등록 신규층 발굴 (1~2개월)", mid_bul, ""),
                              ("long", "시장 여유를 광역으로 확장 (지속)", long_bul, ""),
                          ])))

    # ═══ 정리 (자동) ═══
    strong_pts = " + ".join(filter(None, [
        "주거 밀집" if resid else None,
        "접근성" if (acc_score is not None and acc_score >= 70) else None,
        "시장 여유" if loose else None])) or "우호적 여건"
    body.append(C.callout(
        f"<b>정리</b> — {esc(gu) + ' 상권은 ' if gu else '이 상권은 '}<b>{strong_pts}</b>라는, "
        "동물병원에 유리한 3박자를 갖췄습니다. 관건은 상권 자체가 아니라 "
        "<b>정주 반려가구를 단골로 전환(리텐션)</b>하고, <b>미등록 신규층을 발굴</b>하는 실행입니다. "
        "'바로' 항목부터 손대는 것을 권합니다.", good=loose))

    return page(
        title=f"{clinic['name']} 상권분석",
        kicker="TRADE AREA ANALYSIS",
        h1=f"{clinic['name']} 상권분석",
        sub="지역 시장 규모·포화도·입지 기반 상권 진단",
        meta=[policy.TOOL_LABEL, clinic.get("date", ""), region or clinic.get("address", "")],
        body_html="".join(body),
        footnotes=[policy.FOOTNOTE_METHOD, policy.FOOTNOTE_NO_CRAWL, policy.DISCLAIMER_GENERIC],
        hero=HERO_NAVY, current_no=REPORT_NO, filenames=ctx["filenames"],
    )
