# -*- coding: utf-8 -*-
"""
05 강점 · 06 계획이 공유하는 파생 로직 — 01~04 결과에서 강점 축과 KPI를 도출.
  근거: 병원마케팅_리포트_생성_작업명세.md §3.2(강점 축), §4.3(KPI), §4.2(전략축).
'강점은 이미 상위권' 전제로 연결·증폭·확장 프레임(§0 핵심 철학)을 따른다.
"""

# 강점 축 5종 (작업명세 §3.2)
AXIS_CLINICAL = "진료 역량·전문성"
AXIS_REPUTATION = "평판·리뷰"
AXIS_COMPETITION = "경쟁 포지션"
AXIS_TRADE = "입지·상권"
AXIS_ONLINE = "온라인·브랜드 자산"


def derive_strengths(data, ctx):
    """반환: [{axis, one_liner, findings:[{title,body,src}]}] — 데이터 있는 축만."""
    t = ctx["trade"]; k = ctx["comp"]
    mk = data.get("marketing", {}); rv = data.get("review", {})
    clinic = data["clinic"]
    axes = []

    # 1) 진료 역량·전문성 (config.clinic.specialties 로 표현)
    specs = clinic.get("specialties", [])
    if specs:
        f = [{"title": s.get("title", ""), "body": s.get("body", ""), "src": "마케팅"} for s in specs]
        names = [s.get("title", "") for s in specs if s.get("title")]
        lead = " · ".join(names[:3])
        one = (f"{lead} 등 전문 진료로 2차 의뢰를 받는 임상 역량" if lead
               else "장비·전문의·전문 진료로 2차 의뢰를 받는 임상 역량")
        axes.append({"axis": AXIS_CLINICAL,
                     "one_liner": one,
                     "metric": lead or f"전문 진료 {len(specs)}종",
                     "findings": f})

    # 2) 평판·리뷰 (04 결과)
    chs = rv.get("channels", [])
    total_rv = sum(c.get("review_count", 0) for c in chs)
    if total_rv:
        pos_sum = sum(c.get("sentiment", {}).get("pos", 0) * c.get("review_count", 0) for c in chs)
        pos_rate = round(pos_sum / total_rv) if total_rv else 0
        f = [{"title": f"리뷰 {total_rv:,}개 · 긍정 {pos_rate}%",
              "body": f"복수 채널에서 축적된 리뷰 {total_rv:,}개는 신규 환자 결정의 강력한 사회적 증거입니다. "
                      "리뷰 규모가 클수록 검색·지도 노출 순위와 첫 방문 신뢰도에서 유리합니다.",
              "src": "리뷰"}]
        rated_chs = [c for c in chs if c.get("review_count")]
        if len(rated_chs) >= 2:
            ch_desc = " · ".join(f"{c.get('name','')} {c.get('review_count',0):,}개" for c in rated_chs)
            f.append({"title": "여러 채널에 분산된 평판",
                      "body": f"{ch_desc}로 리뷰가 채널별로 쌓여, 한 채널에 의존하지 않는 안정적 평판 구조입니다.",
                      "src": "리뷰"})
        pk = [x.get("keyword") if isinstance(x, dict) else x for x in rv.get("praise_keywords", [])][:5]
        if pk:
            f.append({"title": "일관된 칭찬 테마",
                      "body": "‘" + " · ".join(pk) + "’ 키워드가 반복됩니다 — 채널을 가로지르는 공통 강점이라, "
                              "이 키워드를 콘텐츠·광고 문구로 그대로 쓰면 검증된 메시지가 됩니다.",
                      "src": "리뷰"})
        axes.append({"axis": AXIS_REPUTATION,
                     "one_liner": f"리뷰 {total_rv:,}개·긍정 {pos_rate}%의 검증된 평판 자산",
                     "metric": f"리뷰 {total_rv:,}개 · 긍정 {pos_rate}%",
                     "findings": f})

    # 3) 경쟁 포지션 (02 결과)
    if k["co_density"] >= 70 or (k["subject_tier"] == 2 and k["referral_count"] >= 5):
        f = [{"title": f"경쟁 포지션 종합 {k['co_density']}점",
              "body": f"반경 {k['radius_m']:,}m 동급 경쟁 {k['rival_count']}곳, 최근접 "
                      f"{k['nearest_m']:,}m로 근거리 압력이 낮습니다." if k["nearest_m"] else
                      f"반경 {k['radius_m']:,}m 동급 경쟁 {k['rival_count']}곳으로 경쟁 압력이 낮습니다.",
              "src": "경쟁"}]
        _near = (k.get("band") or {}).get("near", 0)
        if k.get("nearest_m") and _near == 0:
            f.append({"title": "코앞(300m 이내) 동급 경쟁 없음",
                      "body": f"가장 가까운 동급 경쟁이 {k['nearest_m']:,}m 밖에 있어, 즉시 경쟁 없이 "
                              "인근 초진 수요를 먼저 흡수할 수 있는 위치입니다.",
                      "src": "경쟁"})
        _h24 = (k.get("profile") or {}).get("h24")
        if _h24 is not None and k["subject_tier"] == 2:
            f.append({"title": f"24시·응급 경쟁 {_h24}곳",
                      "body": ("24시간 진료를 전면에 내세우면 야간·응급 수요를 차별적으로 흡수할 수 있습니다."
                               if _h24 <= 3 else
                               "24시 경쟁이 있어, 응급 대응 속도·전문 분과로 차별화가 필요합니다."),
                      "src": "경쟁"})
        if k["subject_tier"] == 2 and k["referral_count"]:
            f.append({"title": f"의뢰처 {k['referral_count']}곳의 유입 파이프라인",
                      "body": f"주변 1차 병원 {k['referral_count']}곳이 잠재 의뢰처입니다 — 리퍼럴 관계(회송 리포트·리퍼 카드)를 "
                              "자산화하면 광고 없이도 안정적인 2차 초진 유입이 만들어집니다.",
                      "src": "경쟁"})
        _cm = f"경쟁 {k['co_density']}점"
        if k.get("nearest_m"):
            _cm += f" · 최근접 {k['nearest_m']:,}m"
        if k["subject_tier"] == 2 and k["referral_count"]:
            _cm += f" · 의뢰처 {k['referral_count']}곳"
        axes.append({"axis": AXIS_COMPETITION,
                     "one_liner": f"경쟁 여유 {k['co_density']}점 + 의뢰처 {k['referral_count']}곳의 우위",
                     "metric": _cm,
                     "findings": f})

    # 4) 입지·상권 (01 결과)
    ta = data.get("trade_area", {})
    if t["grade"] in ("A", "B") or t["is_station_area"]:
        f = []
        if t["grade"] in ("A", "B"):
            f.append({"title": f"시장 포화도 {t['saturation']:,} · {t['grade']}등급",
                      "body": f"반려가구 대비 병원 수가 여유로운 시장(전국 벤치 대비 {t['grade']}등급) — "
                              "병원 한 곳이 나눠 갖는 잠재 고객이 많은 블루오션 구간입니다.",
                      "src": "상권"})
        _sales, _foot = ta.get("monthly_sales_manwon"), ta.get("daily_footfall")
        if _sales or _foot:
            _b = []
            if _sales:
                _b.append(f"업종 월평균 추정매출 {_sales:,}만원")
            if _foot:
                _b.append(f"일일 유동인구 {_foot:,}명")
            f.append({"title": "소비력·상권 활력이 뒷받침",
                      "body": " · ".join(_b) + " — 소득·유동이 받쳐주는 상권이라 마케팅 투자 대비 반응이 큽니다.",
                      "src": "상권"})
        _ph, _reg = t.get("pet_households"), t.get("registered_pets")
        if _ph or _reg:
            _b = []
            if _ph:
                _b.append(f"반려가구 약 {_ph:,}")
            if _reg:
                _b.append(f"등록 반려동물 {_reg:,}")
            f.append({"title": "두터운 반려 수요 기반",
                      "body": " · ".join(_b) + " 규모로 정주 고객 풀이 넓어, 재방문·정기검진 기반이 탄탄합니다.",
                      "src": "상권"})
        if t["is_station_area"]:
            f.append({"title": f"{t['nearest_station'] or '역'} 도보 {t['walk_min']}분 역세권",
                      "body": "대중교통 접근성이 좋아 인근 동을 넘어선 광역 유입에 유리합니다.", "src": "상권"})
        _tm = []
        if t.get("saturation"):
            _tm.append(f"포화도 {t['saturation']:,} {t['grade']}등급")
        if t["is_station_area"]:
            _tm.append(f"{t.get('nearest_station') or '역'} 도보 {t.get('walk_min','?')}분")
        axes.append({"axis": AXIS_TRADE,
                     "one_liner": f"{t['grade'] or ''}등급 상권 여유와 접근성",
                     "metric": " · ".join(_tm) or "입지·상권",
                     "findings": f})

    # 5) 온라인·브랜드 자산 (03 결과 — 고득점 채널)
    good_ch = [c for c in mk.get("channels", []) if (c.get("score") or 0) >= 70]
    if good_ch:
        from .reports.r03_marketing import CHANNEL_LABELS
        names = ", ".join(CHANNEL_LABELS.get(c.get("type"), c.get("type", "")) for c in good_ch[:3])
        _avg_g = round(sum(c["score"] for c in good_ch) / len(good_ch))
        f = [{"title": f"강한 채널: {names}",
              "body": f"평균 {_avg_g}점의 상위권 채널을 허브로 삼아, 약한 채널의 방문자를 예약·상담으로 "
                      "연결·증폭할 수 있습니다. 이미 트래픽이 있으니 '새로 만들기'보다 '잇기'가 빠릅니다.",
              "src": "온라인"}]
        _detail = " · ".join(f"{CHANNEL_LABELS.get(c.get('type'),'')} {c.get('score')}점" for c in good_ch[:4])
        if _detail:
            f.append({"title": "채널별 성숙도",
                      "body": f"{_detail} 등 채널이 이미 상위권 — 각 채널의 강점을 서로 연결하면 브랜드 인지가 배가됩니다.",
                      "src": "온라인"})
        _spec_hi = [s.get("name", "") for s in mk.get("specialty_analysis", {}).get("specialties", [])
                    if s.get("emphasis") == "강함"][:3]
        if _spec_hi:
            f.append({"title": "진료 특화가 채널에 노출됨",
                      "body": f"{' · '.join(_spec_hi)} 등 특화가 홈페이지·콘텐츠로 드러나, '전문성 있는 병원' 인지에 유리합니다.",
                      "src": "온라인"})
        axes.append({"axis": AXIS_ONLINE,
                     "one_liner": "상위권 온라인 채널을 허브로 한 브랜드 자산",
                     "metric": f"강한 채널 {len(good_ch)}개 · 평균 {_avg_g}점",
                     "findings": f})

    return axes[:5]


_KPI_CH_LAB = {"homepage": "홈페이지", "blog": "블로그", "instagram": "인스타",
               "naverplace": "네이버 플레이스", "kakao": "카카오톡", "map": "카카오맵",
               "tmap": "T맵", "aeo_geo": "AI 검색"}


def _kpi_num_in(channels, ctype, patterns):
    """채널 서술 텍스트(한줄·하위축·강점)에서 숫자 추출(팔로워·친구 수 등). 없으면 None."""
    import re as _re
    for c in channels:
        if c.get("type") != ctype:
            continue
        text = " ".join([c.get("one_liner", "")]
                        + [s.get("note", "") for s in c.get("subscores", [])]
                        + [s.get("body", "") for s in c.get("strengths", [])]
                        + [s.get("body", "") for s in c.get("weaknesses", [])])
        for pat in patterns:
            m = _re.search(pat, text)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except ValueError:
                    pass
    return None


def derive_kpis(data, ctx):
    """연간 KPI 표 행: [지표, 현재, 12개월 목표, 연결 전략축]. 채널별로 구체화."""
    k = ctx["comp"]
    mk = data.get("marketing", {}); rv = data.get("review", {})
    mch = mk.get("channels", [])
    rows = []

    # 1) 리뷰 채널별 별점·리뷰수(또는 긍정률) 현재→목표
    chs = rv.get("channels", [])
    for c in chs:
        nm = c.get("name", "리뷰")
        cnt = c.get("review_count") or 0
        rating = c.get("rating")
        cur, tgt = [], []
        if rating:
            cur.append(f"★{rating}")
            if rating >= 4.7:                    # 이미 최상위 — 목표는 '유지'
                tgt.append(f"★{rating} 유지")
            else:
                tgt.append(f"★{min(4.9, round(rating + 0.4, 1))}")
        if cnt:
            cur.append(f"{cnt:,}개")
            tgt.append(f"{round(cnt * 1.5):,}개+")
        else:
            pos = c.get("sentiment", {}).get("pos")
            if pos is not None:
                cur.append(f"긍정 {pos}%"); tgt.append(f"{min(95, pos + 5)}%")
        if cur:
            rows.append([f"{nm} 평판", " · ".join(cur), " · ".join(tgt), "축2 평판"])
    if len(chs) >= 2:   # 총량도 한 줄
        total_rv = sum(c.get("review_count", 0) for c in chs)
        if total_rv:
            rows.append(["총 리뷰 수", f"{total_rv:,}개", f"{round(total_rv * 1.4):,}개", "축2 평판"])

    # 2) 인스타 팔로워 / 카카오 친구 — 채널 서술에서 숫자 추출되면 목표 제시
    insta = _kpi_num_in(mch, "instagram", [r"팔로워\s*([\d,]+)"])
    if insta:
        tgt = 2000 if insta < 2000 else round(insta * 1.5)
        rows.append(["인스타 팔로워", f"{insta:,}명", f"{tgt:,}명+", "축3 도달"])
    kfr = _kpi_num_in(mch, "kakao", [r"친구\s*([\d,]+)"])
    if kfr:
        tgt = 5000 if kfr < 5000 else round(kfr * 1.5)
        rows.append(["카카오톡 친구", f"{kfr:,}명", f"{tgt:,}명+", "축1·3"])

    # 3) 가장 약한 채널 점수 → 구체 목표(어느 채널을 얼마로)
    scored = [c for c in mch if c.get("score") is not None]
    if scored:
        worst = min(scored, key=lambda c: c["score"])
        lab = _KPI_CH_LAB.get(worst.get("type"), worst.get("type", "채널"))
        rows.append([f"{lab} 채널 점수(보완 1순위)", f"{worst['score']}점",
                     f"{min(85, worst['score'] + 15)}점", "축1 전환"])

    # 4) 의뢰처 리퍼럴
    if k["subject_tier"] == 2 and k.get("referral_count"):
        rows.append(["의뢰처 리퍼럴 관계", f"잠재 {k['referral_count']}곳", "핵심 8곳↑ 정기 리퍼", "축3 도달"])

    # 5) 진료 특화 키워드 리뷰(특화가 있으면)
    specs = [s.get("title", "") for s in data.get("clinic", {}).get("specialties", []) if s.get("title")]
    if specs:
        rows.append(["전문 진료 키워드 리뷰", "친절·24시 편중",
                     f"{' · '.join(specs[:2])} 리뷰 축적", "축2·3"])

    rows.append(["월 초진(선행→후행)", "진단값 기준", "+20% 상향", "축1·3"])
    return rows
