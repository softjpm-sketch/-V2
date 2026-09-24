# -*- coding: utf-8 -*-
"""
진료(EMR) 데이터 분석 — 개인정보 보호 + 마케팅 지표 + 12개월 로드맵.

Petamos `~/petamos/petamos/{loader,anonymizer,emr_analyzer,marketing_planner}.py`의
방법론을 pandas 없이 **stdlib(+선택적 openpyxl)**로 이식한 모듈.
파라미터·후보 컬럼명·임계값은 원본과 1:1 동일(방법론 §3~§6).

설계 원칙(방법론 §0):
    - Privacy-first: 보호자명·전화·주소(PII)는 원본을 보관하지 않는다.
      환자 구분이 필요한 분석은 세션 솔티드 SHA-256 가명 ID로만 처리.
    - 마케팅 지향: 재진율·휴면·객단가·주력질환 등 액션 직결 지표만 계산.
    - 결측 내성: 컬럼이 없으면 해당 지표만 건너뛴다. 최소 필수 = visit_date + amount.
    - 키 없이 동작: 로드맵은 규칙 기반(deterministic).

⚠️ 이는 기술적 안전장치일 뿐. 실제 위탁 처리 시 개인정보 처리위탁 계약·
   정보주체 동의 등 법적 절차가 선행돼야 한다.
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import io
import re
import secrets

# ────────────────────────────── 설정(config) ──────────────────────────────
# 표준 필드 → EMR 내보내기에서 흔히 쓰이는 컬럼명 후보(소문자 비교)
COLUMN_CANDIDATES = {
    "patient_id": ["환자번호", "차트번호", "고객번호", "환자id", "patient_id", "chart_no", "id"],
    "guardian_name": ["보호자", "보호자명", "고객명", "이름", "성명", "guardian", "owner", "name"],
    "phone": ["연락처", "전화번호", "휴대폰", "핸드폰", "phone", "tel", "mobile"],
    "address": ["주소", "거주지", "address", "addr"],
    "visit_date": ["진료일", "방문일", "내원일", "일자", "날짜", "visit_date", "date"],
    "amount": ["금액", "매출", "결제금액", "진료비", "수납액", "청구액", "amount", "revenue", "price"],
    "diagnosis": ["진단명", "질환", "진료과목", "증상", "diagnosis", "disease", "category"],
    "species": ["축종", "종", "동물종류", "species", "animal"],
}
PII_FIELDS = ["guardian_name", "phone", "address"]

DORMANT_MONTHS = 6          # 마지막 내원 후 N개월 이상 미방문 = 휴면
REVISIT_WINDOW_DAYS = 365   # 재진율 산정 기간(참고)
HIGH_VALUE_QUANTILE = 0.8   # 상위 20% 객단가 = 고관여 진료 후보


def available() -> bool:
    """xlsx 처리 가능 여부(csv는 항상 가능). openpyxl 유무."""
    try:
        import openpyxl  # noqa: F401
        return True
    except Exception:
        return False


# ────────────────────────────── ① 로드 ──────────────────────────────
def load_table(file_bytes, filename: str):
    """업로드 바이트(.csv/.xlsx) → (headers, rows[dict]).

    CSV 인코딩: utf-8-sig → utf-8 → cp949 → euc-kr 순차 시도.
    XLSX: openpyxl(read_only, data_only).
    """
    name = (filename or "").lower()
    if hasattr(file_bytes, "read"):
        file_bytes = file_bytes.read()

    if name.endswith(".csv") or (not name.endswith((".xlsx", ".xls")) and _looks_csv(file_bytes)):
        text = None
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                text = file_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("CSV 인코딩을 인식할 수 없습니다(utf-8/cp949 시도 실패).")
        reader = csv.DictReader(io.StringIO(text))
        headers = [str(h).strip() for h in (reader.fieldnames or [])]
        rows = []
        for r in reader:
            # DictReader 키를 strip한 헤더로 재매핑
            rows.append({str(k).strip(): v for k, v in r.items() if k is not None})
        return headers, rows

    if name.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
        except Exception:
            raise ValueError("xlsx를 읽으려면 openpyxl이 필요합니다. CSV로 올리거나 openpyxl을 설치하세요.")
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        try:
            first = next(it)
        except StopIteration:
            raise ValueError("빈 엑셀 파일입니다.")
        headers = [str(c).strip() if c is not None else f"col{i}" for i, c in enumerate(first)]
        rows = []
        for r in it:
            if r is None or all(c is None or c == "" for c in r):
                continue
            row = {}
            for i, h in enumerate(headers):
                row[h] = r[i] if i < len(r) else None
            rows.append(row)
        wb.close()
        return headers, rows

    raise ValueError(f"지원하지 않는 형식입니다: {filename} (.csv, .xlsx 지원)")


def _looks_csv(b: bytes) -> bool:
    head = b[:4]
    # xlsx=zip(PK), xls=OLE(D0CF) 시그니처가 아니면 텍스트로 간주
    return not (head[:2] == b"PK" or head[:4] == b"\xd0\xcf\x11\xe0")


# ────────────────────────────── ② 컬럼 자동매핑 ──────────────────────────────
def auto_map_columns(headers) -> dict:
    """헤더 목록 → {표준필드: 실제컬럼명}. 정확매칭 우선 → 부분포함."""
    mapping: dict = {}
    lowered = {str(c).strip().lower(): c for c in headers}
    for std_field, candidates in COLUMN_CANDIDATES.items():
        matched = False
        for cand in candidates:                     # 정확 매칭 우선
            key = cand.lower()
            if key in lowered:
                mapping[std_field] = lowered[key]
                matched = True
                break
        if matched:
            continue
        for cand in candidates:                     # 부분 포함('결제금액(원)'⊃'금액')
            key = cand.lower()
            hit = next((orig for low, orig in lowered.items() if key in low), None)
            if hit and hit not in mapping.values():
                mapping[std_field] = hit
                break
    return mapping


def missing_required(mapping: dict) -> list:
    return [f for f in ("visit_date", "amount") if f not in mapping]


# ────────────────────────────── ③ 익명화 ──────────────────────────────
def _salted_hash(value: str, salt: str) -> str:
    h = hashlib.sha256((salt + "|" + str(value)).encode("utf-8")).hexdigest()
    return "P" + h[:10]


def anonymize(rows, field_map: dict, salt: str | None = None):
    """PII를 마스킹한 표준 행 목록과 처리 리포트 반환.

    Returns: (std_rows[dict(pseudo_id + 비PII 표준필드)], report)
    """
    if salt is None:
        salt = secrets.token_hex(16)  # 세션 랜덤 솔트 → 함수 종료 시 소멸(재식별 불가)

    report = {"masked_fields": [], "dropped_fields": [], "salt_discarded": True}
    dropped = set()

    has_pid = "patient_id" in field_map
    std_rows = []
    for idx, row in enumerate(rows):
        # 환자 구분용 base: patient_id 있으면 그것, 없으면 보호자명|전화 조합, 둘 다 없으면 행 인덱스
        if has_pid and field_map["patient_id"] in row:
            base = str(row.get(field_map["patient_id"], ""))
        else:
            parts = []
            for f in ("guardian_name", "phone"):
                if f in field_map and field_map[f] in row:
                    parts.append(str(row.get(field_map[f], "")))
            base = "|".join(parts) if parts else str(idx)

        out = {"pseudo_id": _salted_hash(base, salt)}
        for std_field, col in field_map.items():
            if std_field == "patient_id":
                continue                       # pseudo_id로 대체됨
            if col not in row:
                continue
            if std_field in PII_FIELDS:
                dropped.add(col)               # 원본 PII는 버림(결과에 미포함)
                continue
            out[std_field] = row.get(col)
        std_rows.append(out)

    report["dropped_fields"] = sorted(dropped)
    report["masked_fields"] = [f for f in PII_FIELDS if f in field_map]
    return std_rows, report


# ────────────────────────────── ④ 지표 분석 ──────────────────────────────
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d",
                 "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%m/%d/%Y", "%Y년 %m월 %d일")


def _parse_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    s = str(v).strip()
    # 시분초 붙은 경우 날짜부만
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # 마지막 시도: 앞 10자(YYYY-MM-DD 류)
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        try:
            return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _parse_amount(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v))  # '12,000원' → '12000'
    if s in ("", "-", ".", "-."):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _months_before(d: _dt.date, months: int) -> _dt.date:
    """d에서 months개월 전 날짜(말일 보정)."""
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    day = min(d.day, [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return _dt.date(y, m, day)


def _percentile(sorted_vals, q):
    """선형보간 분위수(numpy/pandas 기본과 동일)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(sorted_vals):
        return float(sorted_vals[-1])
    return float(sorted_vals[lo] + (sorted_vals[lo + 1] - sorted_vals[lo]) * frac)


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2:
        return float(s[n // 2])
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def analyze(std_rows) -> dict:
    """익명화된 표준 행 목록 → 마케팅 지표 딕셔너리."""
    # _prep: visit_date 파싱 + 유효행만, amount 정제
    prepped = []
    for r in std_rows:
        d = _parse_date(r.get("visit_date"))
        if d is None:
            continue                    # 유효 진료일 없는 행 제외(dropna)
        rr = dict(r)
        rr["_date"] = d
        if "amount" in r:
            rr["_amount"] = _parse_amount(r.get("amount"))
        prepped.append(rr)

    if not prepped:
        return {"error": "유효한 진료일 데이터가 없습니다."}

    has_id = any("pseudo_id" in r for r in prepped)
    has_amount = any("_amount" in r for r in prepped)
    has_diag = any(r.get("diagnosis") not in (None, "") for r in prepped)

    dates = [r["_date"] for r in prepped]
    period_start, period_end = min(dates), max(dates)
    total_visits = len(prepped)

    # 환자 그룹핑
    patients = {}
    for r in prepped:
        pid = r.get("pseudo_id")
        patients.setdefault(pid, []).append(r)
    n_patients = len(patients) if has_id else None

    result = {
        "period": {"start": period_start.strftime("%Y-%m-%d"),
                   "end": period_end.strftime("%Y-%m-%d")},
        "total_visits": int(total_visits),
        "unique_patients": int(n_patients) if n_patients is not None else None,
    }

    # 재진율
    if has_id and n_patients:
        visits_per = [len(v) for v in patients.values()]
        revisit_patients = sum(1 for c in visits_per if c >= 2)
        result["revisit"] = {
            "revisit_patients": revisit_patients,
            "revisit_rate": round(revisit_patients / n_patients, 4),
            "avg_visits_per_patient": round(sum(visits_per) / len(visits_per), 2),
        }

    # 객단가(ARPU)
    if has_amount:
        amts = [r["_amount"] for r in prepped if "_amount" in r]
        result["arpu"] = {
            "avg_per_visit": round(sum(amts) / len(amts), 0) if amts else 0,
            "median_per_visit": round(_median(amts), 0),
            "total_revenue": round(sum(amts), 0),
        }
        if has_id and n_patients:
            per_patient_sum = [sum(x.get("_amount", 0) for x in v) for v in patients.values()]
            result["arpu"]["avg_per_patient"] = round(sum(per_patient_sum) / len(per_patient_sum), 0)
        # 고관여 진료 후보: 진단명별 평균 객단가 상위 5
        if has_diag:
            by_diag = {}
            for r in prepped:
                dg = r.get("diagnosis")
                if dg in (None, ""):
                    continue
                by_diag.setdefault(str(dg), []).append(r.get("_amount", 0))
            means = sorted(((k, sum(v) / len(v)) for k, v in by_diag.items()),
                           key=lambda x: x[1], reverse=True)
            result["high_value_candidates"] = [
                {"diagnosis": k, "avg_amount": round(m, 0)} for k, m in means[:5]]
            result["high_value_threshold"] = round(_percentile(sorted(amts), HIGH_VALUE_QUANTILE), 0)

    # 질환 유입 믹스 Top 8
    if has_diag:
        counts = {}
        for r in prepped:
            dg = r.get("diagnosis")
            key = str(dg) if dg not in (None, "") else "미분류"
            counts[key] = counts.get(key, 0) + 1
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8]
        result["diagnosis_mix"] = [
            {"diagnosis": k, "visits": int(v), "share": round(v / total_visits, 4)}
            for k, v in top]

    # 휴면 환자
    if has_id and n_patients:
        cutoff = _months_before(period_end, DORMANT_MONTHS)
        dormant = 0
        for v in patients.values():
            last = max(x["_date"] for x in v)
            if last < cutoff:
                dormant += 1
        result["dormant"] = {
            "months_threshold": DORMANT_MONTHS,
            "dormant_patients": int(dormant),
            "dormant_rate": round(dormant / n_patients, 4),
            "recall_target": int(dormant),
        }

    return result


# ────────────────────────────── ⑤ 12개월 로드맵 ──────────────────────────────
BASELINE = {
    "네이버": "스마트플레이스 정보 최신화 · 블로그 주 1~2회 발행",
    "카카오": "카카오톡 채널 관리 · 예약/재진 알림톡 운영",
    "소셜미디어·타겟": "인스타그램 콘텐츠 주 2~3회 · 스토리 운영",
    "지도·내비": "네이버/카카오/T맵 지도 정보 점검",
    "AI 검색 노출": "구조화 데이터(schema.org)·NAP 일관성 유지 · AI가 인용할 강점 진료 전문 콘텐츠 축적",
}
QUARTER_THEME = {
    1: "기반 정비 (플레이스·지도·AI 검색 세팅)",
    2: "리텐션 구축 (알림톡·리콜 자동화)",
    3: "신규 유입 확대 (소셜미디어·타겟 광고)",
    4: "객단가·평판 강화 (고관여 콘텐츠·리뷰)",
}


def _aeo_targets(analysis: dict) -> list:
    """EMR이 실측한 강점(주력 유입 질환 + 고관여 진료)을 'AI 검색이 이 병원을 추천할
    엔티티 키워드'로 전환. 추정 키워드가 아니라 '실제로 많이·비싸게 보는 진료'라 근거가 강함.

    Returns: [{"keyword", "kind"(주력/고관여), "basis"(근거)}] 최대 5.
    """
    mix = analysis.get("diagnosis_mix", [])
    hv = analysis.get("high_value_candidates", [])
    seen, targets = set(), []
    for m in mix[:3]:                        # 주력 유입 = 대외 강점
        dg = str(m.get("diagnosis", "")).strip()
        if dg and dg != "미분류" and dg not in seen:
            seen.add(dg)
            targets.append({"keyword": dg, "kind": "주력",
                            "basis": f"유입 {m.get('share', 0)*100:.0f}%"})
    for h in hv[:3]:                         # 고관여 = 수익 레버
        dg = str(h.get("diagnosis", "")).strip()
        if dg and dg != "미분류" and dg not in seen:
            seen.add(dg)
            targets.append({"keyword": dg, "kind": "고관여",
                            "basis": f"객단가 {int(round(h.get('avg_amount', 0))):,}원"})
    return targets[:5]


def _priorities(analysis: dict) -> list:
    pris = []
    rev = analysis.get("revisit", {})
    dorm = analysis.get("dormant", {})
    mix = analysis.get("diagnosis_mix", [])
    hv = analysis.get("high_value_candidates", [])
    aeo = _aeo_targets(analysis)

    if rev.get("revisit_rate") is not None and rev["revisit_rate"] < 0.4:
        pris.append({
            "issue": f"재진율 {rev['revisit_rate']*100:.0f}% (낮음)",
            "focus": "리텐션 강화",
            "actions": ["카카오 알림톡 재진 리마인드 자동화", "정기검진 리콜 캠페인 설계"],
            "weight": 3})
    if dorm.get("recall_target", 0) > 0:
        pris.append({
            "issue": f"휴면 환자 {dorm['recall_target']}명 (최근 {dorm.get('months_threshold')}개월 미방문)",
            "focus": "휴면 리콜",
            "actions": ["휴면 대상 타겟 알림톡/문자 리콜", "예방접종·검진 시즌 캠페인"],
            "weight": 3})
    if hv:
        top = ", ".join(h["diagnosis"] for h in hv[:3])
        pris.append({
            "issue": f"고객단가 진료 후보: {top}",
            "focus": "객단가 상향",
            "actions": [f"{hv[0]['diagnosis']} 등 고관여 진료 콘텐츠/패키지화", "네이버 블로그 전문성 콘텐츠"],
            "weight": 2})
    if mix:
        lead = mix[0]["diagnosis"]
        pris.append({
            "issue": f"주력 유입 질환: {lead} ({mix[0]['share']*100:.0f}%)",
            "focus": "강점 극대화",
            "actions": [f"{lead} 특화 콘텐츠·광고 집중", "인스타/블로그 사례 콘텐츠"],
            "weight": 2})
    if aeo:
        kws = ", ".join(t["keyword"] for t in aeo[:3])
        pris.append({
            "issue": f"AI 검색 추천 최적화: {kws} (EMR 강점 → 엔티티)",
            "focus": "AI 검색 노출(AEO·GEO)",
            "actions": [
                f"{aeo[0]['keyword']} 등 강점 진료를 schema.org(VeterinaryCare·medicalSpecialty) 구조화 데이터로 명시",
                "홈피·플레이스·지도 NAP(상호·주소·전화) 일치 + 강점 진료 전문 콘텐츠로 AI 인용 근거 축적",
            ],
            "weight": 3})

    pris.sort(key=lambda p: p["weight"], reverse=True)
    return pris


def build_roadmap(analysis: dict) -> dict:
    priorities = _priorities(analysis)
    months = []
    for m in range(1, 13):
        q = (m - 1) // 3 + 1
        focus_actions = []
        if priorities:
            p = priorities[(m - 1) % len(priorities)]
            focus_actions = [f"[{p['focus']}] {a}" for a in p["actions"]]
        months.append({"month": m, "quarter": q, "theme": QUARTER_THEME[q],
                       "baseline": BASELINE, "focus_actions": focus_actions})
    return {
        "priorities": priorities,
        "months": months,
        "channels": list(BASELINE.keys()),
        "aeo": {
            "targets": _aeo_targets(analysis),
            "note": ("미래 고객은 네이버·구글 검색보다 AI(챗봇·생성형 검색)에게 "
                     "'우리 동네 OO 잘하는 동물병원'을 묻는다. EMR이 증명한 실제 강점을 "
                     "엔티티(구조화 데이터·NAP 일관성·전문 콘텐츠)로 노출해야 AI 추천에 오른다."),
        },
    }


# ────────────────────────────── 파이프라인 ──────────────────────────────
def run(file_bytes, filename: str, hospital_name: str = "", field_map: dict | None = None) -> dict:
    """업로드 파일 → 익명화 → 지표 → 로드맵. 원본 행/PII는 반환하지 않는다.

    Returns: {hospital_name, column_mapping, missing, mask_report, analysis, roadmap, n_rows}
    """
    headers, rows = load_table(file_bytes, filename)
    mapping = field_map or auto_map_columns(headers)
    missing = missing_required(mapping)
    if missing:
        raise ValueError(
            "필수 컬럼을 찾지 못했습니다: " + ", ".join(missing) +
            f" · 인식된 헤더: {', '.join(str(h) for h in headers[:20])}")
    std_rows, mask_report = anonymize(rows, mapping)
    analysis = analyze(std_rows)
    roadmap = build_roadmap(analysis)
    return {
        "hospital_name": hospital_name,
        "column_mapping": mapping,
        "missing": missing,
        "mask_report": mask_report,
        "analysis": analysis,
        "roadmap": roadmap,
        "n_rows": len(rows),
    }
