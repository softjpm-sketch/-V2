# -*- coding: utf-8 -*-
"""
공용 계산 엔진 — 상권/경쟁 점수식 + 실행 우선순위(score_action).

  근거: 상권경쟁_분석방법론.md §1-2 (= 상권경쟁_리포트_프롬프트.md B안 공식과 1:1 일치)
        PRD_marketing_audit.md §11 (score_action)

방법론 문서와 프롬프트 문서에 '중복 서술'되던 공식을 이 파일 한 곳으로 통합했다.
"""
import math
from . import policy


# ══════════════════════════════════════════════════════════════
# 실행 우선순위 (효과×3 − 노력 − 비용) — PRD §11
# ══════════════════════════════════════════════════════════════
def score_action(effort, impact, cost):
    """
    effort/impact/cost 는 각 1~3.
    반환: dict(priority, tier['now'|'mid'|'long'], feasibility['easy'|'normal'|'hard'])
    """
    e = int(effort or 1); i = int(impact or 1); c = int(cost or 1)
    priority = i * 3 - e - c
    if priority >= 5 or (e == 1 and i >= 2):
        tier = "now"
    elif priority >= 2:
        tier = "mid"
    else:
        tier = "long"
    if e <= 1 and c <= 1:
        feas = "easy"
    elif e <= 2 and c <= 2:
        feas = "normal"
    else:
        feas = "hard"
    return {"priority": priority, "tier": tier, "feasibility": feas}


TIER_LABEL = {"now": "바로", "mid": "중기", "long": "장기"}
TIER_BADGE = {"now": "b-now", "mid": "b-mid", "long": "b-long"}
FEAS_LABEL = {"easy": "쉬움", "normal": "보통", "hard": "어려움"}


def _band(value, table, default):
    """table=[(threshold, score), ...] 내림차순. value 이상 첫 구간 점수."""
    if value is None:
        return None
    for thr, sc in table:
        if value >= thr:
            return sc
    return default


# ══════════════════════════════════════════════════════════════
# ① 상권 분석 — 방법론 §1
# ══════════════════════════════════════════════════════════════
def analyze_trade_area(ta):
    """
    입력(ta dict) 키(모두 선택, 있는 것만 사용):
      households, population, clinics_in_region, registered_pets,
      nearest_station, nearest_station_m,
      monthly_sales_manwon, daily_footfall, area_type, parking, apartment_dense
    """
    households = ta.get("households")
    clinics = ta.get("clinics_in_region")
    registered = ta.get("registered_pets")

    # 반려가구 추정: 가구수 있으면 ×0.28, 없으면 등록수 기반 역산(방법론 §1-2)
    if households:
        pet_households = round(households * policy.PET_OWNERSHIP_RATE)
        hh_basis = "가구수×양육률"
    elif registered:
        pet_households = round(registered * policy.PET_HH_FROM_REG)
        hh_basis = "등록수 기반 추정"
    else:
        pet_households = None
        hh_basis = None
    saturation = round(pet_households / clinics) if (pet_households and clinics) else None
    reg_saturation = round(registered / clinics) if (registered and clinics) else None
    grade, grade_label = policy.saturation_grade(saturation)

    st_m = ta.get("nearest_station_m")
    walk_min = round(st_m / policy.WALK_M_PER_MIN) if st_m else None
    is_station_area = (st_m is not None and st_m <= policy.STATION_NEAR_M)

    # ── 지표별 점수(0~100)와 가중치 — 방법론 §1-4
    metrics = []

    # 시장규모·포화도 (가중 30)
    if saturation is not None:
        sc = _band(saturation, [(2000, 90), (1500, 80), (1100, 66), (800, 52), (500, 42)], 33)
    elif pet_households is not None:  # 병원수 없을 때 규모로
        sc = _band(pet_households, [(50000, 88), (30000, 80), (15000, 68), (5000, 54)], 40)
    else:
        sc = None
    metrics.append(_m("ta_pet_households", "시장규모·포화도", 30, sc,
                      f"포화도 {saturation:,}" if saturation else
                      (f"반려가구 {pet_households:,}" if pet_households else "미입력")))

    # 유동인구·상권활력 (가중 20)
    foot = ta.get("daily_footfall")
    sc = _band(foot, [(250000, 90), (150000, 80), (80000, 68), (40000, 55), (20000, 45)], 38) if foot else None
    metrics.append(_m("ta_footfall", "유동인구·상권활력", 20, sc,
                      f"일유동 {foot:,}명" if foot else "미입력"))

    # 입지·주차·역세권 (가중 20) = 40 + 20×(주차+역세권+아파트밀집)
    acc_flags = [bool(ta.get("parking")), is_station_area, bool(ta.get("apartment_dense"))]
    has_acc = (st_m is not None) or ("parking" in ta) or ("apartment_dense" in ta)
    sc = (40 + 20 * sum(acc_flags)) if has_acc else None
    metrics.append(_m("ta_accessibility", "입지·주차·역세권", 20, sc,
                      f"역 도보 {walk_min}분" if walk_min is not None else "미입력"))

    # 소득·소비력 (가중 15)
    sales = ta.get("monthly_sales_manwon")
    sc = _band(sales, [(6000, 90), (5000, 80), (4500, 68), (3500, 55), (2500, 45)], 38) if sales else None
    metrics.append(_m("ta_income", "소득·소비력", 15, sc,
                      f"월매출 {sales:,}만원" if sales else "미입력"))

    # 상권유형 (가중 15)
    at = ta.get("area_type")
    at_map = {"주거 밀집형": 85, "주거·상업 혼합": 68, "상업 중심": 52}
    sc = at_map.get(at)
    metrics.append(_m("ta_area_type", "상권유형", 15, sc, at or "미입력"))

    axis = _axis_from_metrics(metrics)
    return {
        "pet_households": pet_households, "saturation": saturation, "hh_basis": hh_basis,
        "reg_saturation": reg_saturation, "grade": grade, "grade_label": grade_label,
        "clinics_in_region": clinics, "registered_pets": registered,
        "nearest_station": ta.get("nearest_station"), "walk_min": walk_min,
        "is_station_area": is_station_area,
        "metrics": metrics, "axis_score": axis["score"],
        "axis_score100": axis["score100"], "coverage": axis["coverage"],
    }


# ══════════════════════════════════════════════════════════════
# ② 경쟁 분석 — 방법론 §2
# ══════════════════════════════════════════════════════════════
def _is_tier2(name, category=""):
    text = f"{name} {category}".lower()
    return any(sig.lower() in text for sig in policy.TIER2_SIGNALS)


# 병원명에서 공통 접미/수식어를 제거해 '핵심 상호'만 남긴다(자기병원 매칭용).
_NAME_STRIP = ["동물메디컬센터", "동물의료센터", "동물의료원", "메디컬센터", "의료센터",
               "동물종합병원", "종합동물병원", "동물병원", "의료원", "메디컬", "클리닉",
               "24시간", "24시", "24", "연중무휴", "동물", "병원", "센터"]


def _norm_name(s):
    """상호 정규화 — 접미어·공백·기호 제거 후 소문자. '인천24시스카이동물메디컬센터'→'인천스카이'."""
    s = str(s or "")
    for t in _NAME_STRIP:
        s = s.replace(t, "")
    for ch in " ()[]·.,-_/":
        s = s.replace(ch, "")
    return s.strip().lower()


def _is_self(nm, d, self_name, self_core):
    """경쟁 목록의 한 병원이 '본원'인지 판정(자기 제외)."""
    if d is not None and d <= policy.SELF_MATCH_M:
        return True                                  # 같은 위치(≤30m)
    if self_name and nm and (self_name in nm or nm in self_name):
        return True                                  # 원문 상호 포함관계
    core = _norm_name(nm)
    if self_core and core and len(self_core) >= 2 and (self_core in core or core in self_core):
        # 핵심 상호가 겹치고 근거리면 같은 병원(상호 표기만 다른 경우)
        if d is None or d <= policy.SELF_NAME_M:
            return True
    return False


def subject_place_reviews(review, marketing=None):
    """경쟁 비교용 자병원 리뷰수 = 네이버 플레이스 기준(경쟁사도 플레이스 기준이라 통일).

    ① ④리뷰 섹션의 네이버 채널 → ② ③마케팅 분석의 네이버 플레이스 채널(캡처 판독) 순으로 찾는다.
    구글 등 다른 채널은 감성·키워드 '분석'에만 쓰고 리뷰수 비교에는 넣지 않는다. 없으면 None(비교 결측).
    """
    for c in (review or {}).get("channels", []):
        nm = c.get("name") or ""
        if ("네이버" in nm or "플레이스" in nm) and c.get("review_count"):
            return {"review_count": c["review_count"], "rating": c.get("rating"),
                    "basis": "네이버 플레이스"}
    # 마케팅 분석의 네이버 플레이스 채널에서 리뷰수를 뽑았으면 그것 사용
    for c in (marketing or {}).get("channels", []):
        if c.get("type") == "naverplace" and c.get("review_count"):
            return {"review_count": c["review_count"], "rating": c.get("rating"),
                    "basis": "네이버 플레이스(마케팅 분석)"}
    return None


def analyze_competition(comp, clinic, subject_reviews=None):
    """
    comp: {"clinics":[{name,category,distance_m, review_count?, rating?}, ...]}
    clinic: {"name","tier"(1|2)}
    subject_reviews: {"review_count":int, "rating":float}  # 상대 포지션 계산용(선택)
    """
    subject_tier = int(clinic.get("tier", 2))
    radius = policy.RADIUS_TIER1_M if subject_tier == 1 else policy.RADIUS_TIER2_M
    self_name = clinic.get("name", "")
    self_core = _norm_name(self_name)
    # 사용자가 지정한 별칭(카카오맵 상호 등)도 자기 병원으로 제외
    self_aliases = [a for a in (clinic.get("aka") or []) if a]

    rivals, referrals = [], []          # 동급(경쟁) / 타tier(의뢰처)
    for c in comp.get("clinics", []):
        d = c.get("distance_m")
        nm = c.get("name", "")
        if d is None:
            continue
        # 자기 병원 제외: 근거리·상호포함·핵심상호 일치(표기만 다른 같은 병원) 또는 별칭
        if _is_self(nm, d, self_name, self_core) or nm in self_aliases:
            continue
        if d > radius:
            continue
        tier2 = _is_tier2(nm, c.get("category", ""))
        neighbor_tier = 2 if tier2 else 1
        rec = {"name": nm, "category": c.get("category", ""), "distance_m": d,
               "tier": neighbor_tier, "w": math.exp(-d / policy.DIST_DECAY),
               "review_count": c.get("review_count"), "rating": c.get("rating")}
        if neighbor_tier == subject_tier:
            rivals.append(rec)
        else:
            referrals.append(rec)

    rivals.sort(key=lambda r: r["distance_m"])
    referrals.sort(key=lambda r: r["distance_m"])
    # 최근접은 '동급 경쟁' 기준(방법론 §2-6 스냅샷)
    nearest = rivals[0]["distance_m"] if rivals else None

    pressure = sum(r["w"] for r in rivals)          # 동급 경쟁 압력
    referral_pool = sum(r["w"] for r in referrals)  # 의뢰처 유입 풀

    base = 100 * math.exp(-pressure / 2.5)
    bonus = min(20, referral_pool * 4) if subject_tier == 2 else 0
    co_density = max(10, min(100, base + bonus))

    # 거리 밴드
    band = {"near": 0, "mid": 0, "far": 0}   # ~300 / 300~600 / 600~
    for r in rivals:
        d = r["distance_m"]
        if d <= 300:
            band["near"] += 1
        elif d <= 600:
            band["mid"] += 1
        else:
            band["far"] += 1

    # 리뷰 정밀비교 Top3 = 경쟁 중 거리가중 상위 3 (방법론 §2-4)
    top3 = sorted(rivals, key=lambda r: r["w"], reverse=True)[:3]

    # ── §2-5 지표 ②③④ ────────────────────────────────────
    rel = _co_rel_position(rivals, subject_reviews)      # 상대 포지션(리뷰수·평점)
    # 경쟁사 특화(직접입력 rm_spec·캡처판독)도 빈자리 계산에 사용 — 이름만이 아니라
    _rspec = " ".join(
        (" ".join(r["specialty"]) if isinstance(r.get("specialty"), list) else str(r.get("specialty") or ""))
        for r in (comp.get("rival_marketing") or []))
    gap = _co_gap_specialty(rivals, self_name, _rspec)   # 특화 빈자리
    prof = _co_profile(rivals)                           # 경쟁사 프로필(과목/24시)

    # 경쟁 축(20점) = 측정된 지표만 가중평균 ×0.2 + 충실도% (방법론 §2-5)
    metrics = [
        _m("co_density", "경쟁 포지션(밀도)", 30, round(co_density),
           f"거리가중 압력 {round(pressure,2)}"),
        _m("co_rel_position", "상대 포지션(리뷰·평점)", 30, rel["score"], rel["note"]),
        _m("co_gap_specialty", "빈자리(희소 특화)", 25, gap["score"], gap["note"]),
        _m("co_profile", "경쟁사 프로필(과목·24시)", 15, prof["score"], prof["note"]),
    ]
    axis = _axis_from_metrics(metrics)

    return {
        "subject_tier": subject_tier, "radius_m": radius,
        "rivals": rivals, "referrals": referrals,
        "rival_count": len(rivals), "referral_count": len(referrals),
        "nearest_m": nearest, "pressure": round(pressure, 2),
        "referral_pool": round(referral_pool, 2),
        "base": round(base), "bonus": round(bonus), "co_density": round(co_density),
        "band": band, "top3": top3,
        "metrics": metrics, "axis_score": axis["score"],
        "axis_score100": axis["score100"], "coverage": axis["coverage"],
        "rel": rel, "gap": gap, "profile": prof,
    }


def _has_signal(text):
    t = text.lower()
    for kws in policy.SPECIALTY_KEYWORDS.values():
        if any(kw.lower() in t for kw in kws):
            return True
    return False


def _co_rel_position(rivals, subject_reviews):
    """상대 포지션: 경쟁사 대비 리뷰·평점 위치.

    ⚠️ 경쟁사 별점이 없으면(미입력) 0점으로 취급하지 않는다 — 양쪽 다 있는 지표로만 비교.
    별점이 둘 다 있으면 별점 우선, 없으면 리뷰수로 비교(볼륨=사회적 증거·검색 노출).
    """
    rated = [r for r in rivals if r.get("review_count") or r.get("rating")]
    sr = subject_reviews or {}
    s_rc, s_rt = sr.get("review_count"), sr.get("rating")
    if s_rc is None and s_rt is None:
        return {"score": None, "note": "우리 네이버 플레이스 리뷰수 미입력 → 비교 결측"}
    if not rated:
        return {"score": None, "note": "경쟁사 리뷰 미입력 → 결측"}

    def wins(r):
        r_rc, r_rt = r.get("review_count"), r.get("rating")
        # 양쪽 다 별점 있으면 별점 우선(동점 시 리뷰수)
        if s_rt is not None and r_rt is not None:
            if s_rt != r_rt:
                return s_rt > r_rt
            return (s_rc or 0) >= (r_rc or 0)
        # 별점이 한쪽이라도 없으면 리뷰수(볼륨)로만 비교 — 없는 별점을 0으로 취급하지 않음
        return (s_rc or 0) >= (r_rc or 0)

    beat = sum(1 for r in rated if wins(r))
    pct = round(beat / len(rated) * 100)
    has_rt = sum(1 for r in rated if r.get("rating") is not None)
    basis = "별점·리뷰수" if has_rt else "리뷰수(별점 미확인)"
    return {"score": pct,
            "note": f"경쟁 {len(rated)}곳 중 {beat}곳보다 리뷰 많음 ({basis} 기준)"}


def _co_gap_specialty(rivals, self_name, rival_specs=""):
    """특화 빈자리: 동급 경쟁이 커버 못 한 희소 특화 = 기회.
       근거 = 경쟁사 명칭 + 입력/판독된 경쟁사 특화(rm_spec·캡처). 신호가 전무하면 결측(환각 방지)."""
    names = " ".join(r["name"] + " " + (r.get("category") or "") for r in rivals)
    combined = names + " " + (rival_specs or "")
    any_signal = _has_signal(combined) or _has_signal(self_name or "")
    if not rivals or not any_signal:
        return {"score": None, "note": "경쟁사 특화 신호 없음 → 결측(경쟁사 ‘특화’ 입력·캡처 시 채워짐)",
                "covered": [], "open": []}
    covered, open_ = [], []
    low = combined.lower()
    for spec, kws in policy.SPECIALTY_KEYWORDS.items():
        if any(kw.lower() in low for kw in kws):
            covered.append(spec)
        else:
            open_.append(spec)
    total = len(policy.SPECIALTY_KEYWORDS)
    score = round(40 + (len(open_) / total) * 60)   # 빈자리 많을수록 기회↑
    return {"score": score, "covered": covered, "open": open_,
            "note": f"빈자리 {len(open_)}/{total} · 커버 {len(covered)}"}


def _co_profile(rivals):
    """경쟁사 프로필: 동급 중 24시·전문 성격 비중. 강한 경쟁 많을수록 점수↓.
       (명칭 신호 없으면 결측)"""
    if not rivals:
        return {"score": None, "note": "동급 경쟁 없음 → 결측", "strong": 0, "h24": 0}
    strong = h24 = 0
    _strong_kws = [k.lower() for k in policy.TIER2_SIGNALS]   # 종합·메디컬센터·의료원·2차 등도 강한 경쟁
    for r in rivals:
        t = (r["name"] + " " + (r.get("category") or "")).lower()
        if any(k in t for k in [k2.lower() for k2 in policy.PROFILE_24H_KEYWORDS]):
            h24 += 1
        if _has_signal(t) or any(k in t for k in _strong_kws):   # 특화명 OR 종합/메디컬/의료원 성격
            strong += 1
    if strong == 0 and h24 == 0:
        return {"score": None, "note": "명칭 기반 프로필 신호 없음 → 결측",
                "strong": 0, "h24": 0}
    share = strong / len(rivals)
    score = max(40, min(100, round(100 - share * 60)))
    return {"score": score, "strong": strong, "h24": h24,
            "note": f"강한 경쟁 {strong}/{len(rivals)}곳 · 24시 {h24}곳"}


# ── 내부 헬퍼 ───────────────────────────────────────────────
def _m(key, name, weight, score, note):
    return {"key": key, "name": name, "weight": weight, "score": score, "note": note}


def _axis_from_metrics(metrics):
    """측정된 지표만 가중평균 → ×0.2 (20점 만점) + 충실도%."""
    total_w = sum(m["weight"] for m in metrics)
    got = [(m["score"], m["weight"]) for m in metrics if m["score"] is not None]
    meas_w = sum(w for _, w in got)
    if meas_w == 0:
        return {"score": None, "score100": None, "coverage": 0}
    wavg = sum(s * w for s, w in got) / meas_w
    return {"score": round(wavg * 0.2, 1), "score100": round(wavg),
            "coverage": round(meas_w / total_w * 100)}


def marketing_axis100(data):
    """마케팅 축(0~100) = 온라인 채널 평균 점수. 채널 없으면 None."""
    chs = [c for c in data.get("marketing", {}).get("channels", []) if c.get("score") is not None]
    if not chs:
        return None
    return round(sum(c["score"] for c in chs) / len(chs))


def review_axis100(data):
    """리뷰 축(0~100) = 리뷰수 가중 긍정률. 채널 없으면 None."""
    chs = data.get("review", {}).get("channels", [])
    tot = sum(c.get("review_count", 0) for c in chs)
    if not tot:
        return None
    pos = sum(c.get("sentiment", {}).get("pos", 0) * c.get("review_count", 0) for c in chs)
    return round(pos / tot)


def overall_grade(trade, comp, data):
    """
    측정된 진단축(상권·경쟁·마케팅·리뷰) 평균 → 0~100 종합 + 등급(A≥80…).
    각 축 동일 가중(방법론 §0). 강점(05)은 종합 제언이라 점수 제외.
    반환: {"score100", "grade", "coverage", "axes":[(라벨,점수)]}
    """
    axes = [
        ("상권", trade.get("axis_score100")),
        ("경쟁", comp.get("axis_score100")),
        ("마케팅", marketing_axis100(data)),
        ("리뷰", review_axis100(data)),
    ]
    got = [(lab, s) for lab, s in axes if s is not None]
    if not got:
        return {"score100": None, "grade": None, "coverage": 0, "axes": axes}
    score = round(sum(s for _, s in got) / len(got))
    return {"score100": score, "grade": policy.axis_grade(score),
            "coverage": round(len(got) / len(axes) * 100), "axes": axes}


def bar_class(score100):
    """점수 바 색: 우수≥70 / 양호≥45 / 개선."""
    if score100 is None:
        return "s-lo"
    if score100 >= 70:
        return "s-hi"
    if score100 >= 45:
        return "s-mid"
    return "s-lo"


# ══════════════════════════════════════════════════════════════
# 경쟁사 마케팅 분석 — 채널 3-state·상권 온라인 성숙도·tier별 기회
#   핵심 원칙: "마케팅 안 함(확인)"은 결측이 아니라 '기회 신호'.
#             "운영/없음(확인)/미확인"을 엄격히 구분한다.
# ══════════════════════════════════════════════════════════════

# 마케팅 채널(적극 마케팅 신호) + 가중치. 플레이스/리뷰는 baseline이라 별도 취급.
_MK_CHANNELS = [("homepage", "홈페이지", 2.0),
                ("blog", "네이버 블로그", 2.0),
                ("instagram", "인스타그램", 1.5)]
_MK_MAX = sum(w for _, _, w in _MK_CHANNELS)  # 5.5


def _state(v):
    """입력값을 3-state로 정규화: 운영 / 없음 / 미확인."""
    if v is None:
        return "미확인"
    s = str(v).strip().lower()
    if s in ("운영", "함", "있음", "y", "yes", "o", "1", "true", "active"):
        return "운영"
    if s in ("없음", "안함", "안 함", "무", "n", "no", "x", "0", "false", "none"):
        return "없음"
    return "미확인"


def _subject_marketing_states(subject_marketing):
    """자병원 marketing 블록(있으면)에서 홈피/블로그/인스타 운영 여부 추정."""
    if not subject_marketing:
        return None
    type_map = {"homepage": "homepage", "blog": "blog", "instagram": "instagram"}
    states = {}
    for c in subject_marketing.get("channels", []):
        t = type_map.get(c.get("type"))
        if t:
            states[t] = "운영" if (c.get("score") is not None or c.get("note")) else "미확인"
    return states or None


def _intensity(states):
    """채널 상태 dict → 운영 강도(0~100)와 운영 채널 라벨."""
    got = 0.0
    active = []
    for key, lab, w in _MK_CHANNELS:
        if states.get(key) == "운영":
            got += w
            active.append(lab)
    return round(got / _MK_MAX * 100), active


def analyze_competition_marketing(comp, clinic, k, subject_marketing=None):
    """경쟁사 마케팅 분석.

    입력: comp['rival_marketing'] = [{name, homepage, blog, instagram, place_review?, notes?}, ...]
          각 채널값은 운영/없음/미확인(별칭 허용). 없으면 미확인.
    반환: 채널 집계·상권 온라인 성숙도·운영 강도 랭킹·빈 채널·tier별 전략.
    """
    tier = int(clinic.get("tier", 2))
    # 자기 병원이 섞여 있으면 제외(상호 표기가 달라도 핵심상호로 매칭)
    self_name = clinic.get("name", "")
    self_core = _norm_name(self_name)
    rms = []
    for r in (comp.get("rival_marketing") or []):
        nm = r.get("name", "")
        core = _norm_name(nm)
        is_self = (self_name and nm and (self_name in nm or nm in self_name)) or \
                  (self_core and core and len(self_core) >= 2 and (self_core in core or core in self_core))
        if not is_self:
            rms.append(r)
    result = {"has_data": bool(rms), "tier": tier, "n_assessed": len(rms)}

    # ── 채널별 3-state 집계(경쟁사) ──
    chan_agg = []
    total_confirmed = total_active = 0
    open_channels = []
    for key, lab, _w in _MK_CHANNELS:
        active = absent = unknown = 0
        for r in rms:
            st = _state(r.get(key))
            if st == "운영":
                active += 1
            elif st == "없음":
                absent += 1
            else:
                unknown += 1
        confirmed = active + absent
        total_confirmed += confirmed
        total_active += active
        # 빈 채널(기회): 확인된 곳이 2+이고 대부분(≥2/3) 없음
        is_open = confirmed >= 2 and active <= confirmed / 3.0
        if is_open:
            open_channels.append(lab)
        chan_agg.append({"key": key, "label": lab, "active": active, "absent": absent,
                         "unknown": unknown, "confirmed": confirmed,
                         "active_ratio": round(active / confirmed, 2) if confirmed else None,
                         "open": is_open})
    result["channels"] = chan_agg
    result["open_channels"] = open_channels

    # ── 상권 온라인 성숙도(확인된 것만; 미확인 제외) ──
    if total_confirmed:
        ratio = total_active / total_confirmed
        score = round(ratio * 100)
        grade = "높음" if score >= 60 else ("보통" if score >= 30 else "낮음")
        result["maturity"] = {"score": score, "grade": grade,
                              "confirmed_cells": total_confirmed, "active_cells": total_active}
    else:
        result["maturity"] = {"score": None, "grade": None,
                              "confirmed_cells": 0, "active_cells": 0}

    # ── 운영 강도 랭킹(경쟁사 + 자병원) ──
    ranking = []
    for r in rms:
        states = {key: _state(r.get(key)) for key, _l, _w in _MK_CHANNELS}
        inten, active = _intensity(states)
        n_unknown = sum(1 for s in states.values() if s == "미확인")
        ranking.append({"name": r.get("name", "경쟁사"), "intensity": inten,
                        "active": active, "is_subject": False,
                        "all_unknown": n_unknown == len(_MK_CHANNELS),
                        "place_review": r.get("place_review")})
    subj_states = _subject_marketing_states(subject_marketing)
    if subj_states:
        inten, active = _intensity(subj_states)
        ranking.append({"name": clinic.get("name", "본 병원"), "intensity": inten,
                        "active": active, "is_subject": True, "all_unknown": False,
                        "place_review": None})
    ranking.sort(key=lambda x: x["intensity"], reverse=True)
    if subj_states:
        for i, row in enumerate(ranking):
            if row["is_subject"]:
                result["subject_rank"] = i + 1
                break
    result["ranking"] = ranking

    # ── 특화 포지셔닝 맵(거리 가중 상위 3곳만) ──
    result["matrix"] = competitor_specialty_matrix(k.get("rivals", []), rms, limit=3)

    # ── tier별 전략 제언 ──
    result["strategy"] = _marketing_strategy(tier, result, k)
    return result


def _match_specs(text):
    """자유 텍스트 → 표준 특화 8종 중 매칭되는 집합."""
    t = str(text or "").lower()
    hits = set()
    for spec, kws in policy.SPECIALTY_KEYWORDS.items():
        if any(kw.lower() in t for kw in kws):
            hits.add(spec)
    return hits


def top_rivals(comp, clinic, n=3):
    """리포트 §2-4 '추천 Top3'와 동일 기준(동급·반경 내·거리가중 상위)으로 상위 n곳 반환.
       각 항목에 '_ref'(원본 clinic dict)를 실어, 리뷰수·평점을 되써넣을 수 있게 한다."""
    subject_tier = int(clinic.get("tier", 2))
    radius = policy.RADIUS_TIER1_M if subject_tier == 1 else policy.RADIUS_TIER2_M
    self_name = clinic.get("name", "")
    self_core = _norm_name(self_name)
    self_aliases = [a for a in (clinic.get("aka") or []) if a]
    rivals = []
    for c in comp.get("clinics", []):
        d = c.get("distance_m")
        nm = c.get("name", "")
        if d is None or d > radius:
            continue
        if _is_self(nm, d, self_name, self_core) or nm in self_aliases:
            continue
        neighbor_tier = 2 if _is_tier2(nm, c.get("category", "")) else 1
        if neighbor_tier != subject_tier:
            continue
        rivals.append({"name": nm, "category": c.get("category", ""), "distance_m": d,
                       "w": math.exp(-d / policy.DIST_DECAY), "_ref": c})
    rivals.sort(key=lambda r: r["w"], reverse=True)
    return rivals[:n]


def competitor_specialty_matrix(rivals, rms=None, limit=8):
    """경쟁사 × 특화 매트릭스.

    두 근거를 구분:
      - 확인(confirmed): 사용자가 '특화' 칸에 직접 입력한 것(rms[i]['specialty']).
      - 추정(estimated): 경쟁사 명칭·카테고리에 특화 단어가 들어간 것.
    빈자리(open)는 확인·추정 어느 쪽도 없는 특화. 명칭만으론 과대평가되므로 근거를 분리한다.
    """
    specs = list(policy.SPECIALTY_KEYWORDS.keys())
    # 이름 정규화 → 수동 특화 매핑
    manual = {}
    for r in (rms or []):
        sp = r.get("specialty")
        if not sp:
            continue
        stext = " ".join(sp) if isinstance(sp, (list, tuple)) else str(sp)
        manual[_norm_name(r.get("name", ""))] = _match_specs(stext)

    top = sorted(rivals, key=lambda r: r.get("w", 0), reverse=True)[:limit]
    # 수동 태그가 달린 경쟁사가 top에 없으면 추가로 포함
    seen_cores = {_norm_name(r.get("name", "")) for r in top}
    extra = []
    for r in (rms or []):
        core = _norm_name(r.get("name", ""))
        if core in manual and core not in seen_cores:
            extra.append({"name": r.get("name", ""), "w": 0, "distance_m": None})
            seen_cores.add(core)

    rows = []
    confirmed, estimated = set(), set()
    for r in top + extra:
        core = _norm_name(r.get("name", ""))
        est = _match_specs((r.get("name", "") + " " + (r.get("category") or "")))
        conf = manual.get(core, set())
        estimated |= est
        confirmed |= conf
        rows.append({"name": r.get("name", ""), "distance_m": r.get("distance_m"),
                     "confirmed": conf, "estimated": est - conf, "hits": conf | est})
    covered = confirmed | estimated
    open_ = [s for s in specs if s not in covered]
    return {"specialties": specs, "rows": rows,
            "confirmed": sorted(confirmed), "estimated": sorted(estimated),
            "covered": sorted(covered), "open": open_,
            "has_manual": bool(manual), "n_rivals": len(rows)}


def _marketing_strategy(tier, res, k):
    """1차=선점 / 2차=차별화 관점의 tier별 전략 제언."""
    maturity = res.get("maturity", {})
    grade = maturity.get("grade")
    open_ch = res.get("open_channels", [])
    spec_open = res.get("matrix", {}).get("open", [])
    actions = []

    if tier == 1:
        # 1차: 저비용 선점 관점
        if grade == "낮음":
            headline = ("이 상권 온라인은 사실상 <b>무주공산</b> — 경쟁사 상당수가 마케팅을 안 합니다. "
                        "기본기만 갖춰도 <b>지역 검색을 선점</b>할 수 있습니다.")
        elif grade == "보통":
            headline = "경쟁사 절반 정도만 온라인을 합니다 — <b>지금이 선점 타이밍</b>입니다."
        elif grade == "높음":
            headline = "1차치고 경쟁사 온라인이 활발합니다 — 남들과 다른 <b>차별화 포인트</b>가 필요합니다."
        else:
            headline = "경쟁사 마케팅 현황을 입력하면 선점 여지를 정량화합니다."
        if open_ch:
            actions.append(f"빈 채널 선점 — {', '.join(open_ch)}에 콘텐츠를 먼저 쌓아 검색 노출 독점")
        actions.append("네이버 스마트플레이스 정보·사진·소식 최적화(가장 저비용·고효율)")
        actions.append("블로그 주 1회 지역·진료 콘텐츠 — 꾸준함만으로 상위 노출")
        if spec_open:
            actions.append(f"명칭에 특화 신호 추가 검토 — 빈 특화: {', '.join(spec_open[:3])}")
    else:
        # 2차: 전문성·품질 차별화 관점
        if grade == "높음":
            headline = ("경쟁사 온라인이 활발합니다 — 양이 아니라 <b>전문성·케이스 깊이</b>로 갈라야 합니다.")
        elif grade == "보통":
            headline = "경쟁이 중간 수준 — <b>전문 콘텐츠의 깊이</b>로 상위를 선점할 여지가 있습니다."
        elif grade == "낮음":
            headline = ("2차 상권인데 경쟁사 온라인이 약합니다 — <b>전문성 콘텐츠 선점</b>의 드문 기회입니다.")
        else:
            headline = "경쟁사 마케팅 현황을 입력하면 차별화 지점을 정량화합니다."
        actions.append("주력 진료 케이스(수술·영상·중환자) 상세 콘텐츠로 전문성 입증")
        if open_ch:
            actions.append(f"경쟁사가 비운 채널 — {', '.join(open_ch)}에서 전문성 콘텐츠로 우위 확보")
        actions.append("1차 병원(의뢰처) 대상 협진·회송 콘텐츠 — B2B 리퍼럴 신뢰 구축")
        if spec_open:
            actions.append(f"특화 빈자리 선점 — {', '.join(spec_open[:3])} 진료 포지셔닝")

    return {"tier": tier, "headline": headline, "actions": actions,
            "maturity_grade": grade, "open_channels": open_ch, "spec_open": spec_open}
