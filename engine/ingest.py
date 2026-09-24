# -*- coding: utf-8 -*-
"""
상권 자동화 — '간단분석 리포트'(소상공인 상권정보) PDF + 참조 등록수 CSV → trade_area 입력.

  세팅(1회): reference/pet_registration_sigungu.csv (전국 시군구 반려동물 등록수)
  사용: 간단분석 PDF만 넣으면 → 지역·월매출·유동인구·동물병원 업소수 자동 추출
        + 참조 CSV에서 등록 반려동물수 조회 → trade_area dict 생성.

PDF에서 뽑는 값(소상공인 간단분석 형식):
  - 분석지역(시도/시군구/동), 월평균 추정매출(만원), 일일평균 유동인구(명),
  - 동물병원 업소수(동/시군구) — 시군구 값이 시장 포화도 분모.
없는 값(가구수·역세권·상권유형)은 채우지 않음(등록기반 포화도로 대체).
"""
import csv
import io
import os
import re

REF_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "reference", "pet_registration_sigungu.csv")

_SIDO_SUFFIX = ["특별자치도", "특별자치시", "특별시", "광역시", "자치도", "도", "시"]


def _norm_sido(s):
    s = (s or "").strip()
    for suf in _SIDO_SUFFIX:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


_ref_cache = None


def _load_ref():
    """{(시도정규화, 시군구): 총등록} 로드(캐시)."""
    global _ref_cache
    if _ref_cache is not None:
        return _ref_cache
    d = {}
    try:
        with open(REF_CSV, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    total = int(row.get("총등록") or 0)
                except ValueError:
                    total = 0
                d[(_norm_sido(row["시도"]), row["시군구"].strip())] = total
    except FileNotFoundError:
        pass
    _ref_cache = d
    return d


def registered_pets(sido, sigungu):
    """(시도, 시군구) → 등록 반려동물수. 없으면 None."""
    ref = _load_ref()
    key = (_norm_sido(sido), (sigungu or "").strip())
    return ref.get(key)


# ── PDF 파싱 ────────────────────────────────────────────────
def _pdf_text(pdf):
    """pdf: 경로(str) 또는 bytes → 전체 텍스트."""
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf) if isinstance(pdf, (bytes, bytearray)) else pdf)
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def parse_report(pdf):
    """간단분석 PDF → 추출 필드 dict. 실패 항목은 None."""
    text = _pdf_text(pdf)
    out = {"region_label": None, "sido": None, "sigungu": None, "dong": None,
           "monthly_sales_manwon": None, "daily_footfall": None,
           "clinics_dong": None, "clinics_in_region": None}

    m = re.search(r"([가-힣]{2,}[시도])\s+([가-힣]{1,}[구군시])\s+([가-힣0-9]+[동읍면리])", text)
    if m:
        out["sido"], out["sigungu"], out["dong"] = m.group(1), m.group(2), m.group(3)
        out["region_label"] = f"{m.group(1)} {m.group(2)} {m.group(3)}"

    m = re.search(r"월평균 추정매출은\s*([\d,]+)\s*만원", text)
    if m:
        out["monthly_sales_manwon"] = int(m.group(1).replace(",", ""))

    m = re.search(r"일일평균 유동인구는\s*([\d,]+)\s*명", text)
    if m:
        out["daily_footfall"] = int(m.group(1).replace(",", ""))

    m = re.search(r"업소수는\s*(\d+)\s*개", text)
    if m:
        dong = int(m.group(1))
        out["clinics_dong"] = dong
        # 시군구 업소수: "구의 업소수보다 -81.2% 적/많" 로 역산
        m2 = re.search(r"구의 업소수보다\s*(-?[\d.]+)\s*%\s*(적|많)", text)
        if m2:
            p = abs(float(m2.group(1))) / 100.0
            if m2.group(2) == "적" and p < 1:
                out["clinics_in_region"] = round(dong / (1 - p))
            elif m2.group(2) == "많":
                out["clinics_in_region"] = round(dong / (1 + p))
    return out


def build_trade_area(pdf):
    """간단분석 PDF → scoring.analyze_trade_area 입력 dict (+진단 메타)."""
    r = parse_report(pdf)
    ta = {}
    if r["monthly_sales_manwon"]:
        ta["monthly_sales_manwon"] = r["monthly_sales_manwon"]
    if r["daily_footfall"]:
        ta["daily_footfall"] = r["daily_footfall"]
    if r["clinics_in_region"]:
        ta["clinics_in_region"] = r["clinics_in_region"]
    if r.get("clinics_dong"):
        ta["region_clinics"] = r["clinics_dong"]   # 상권영역(동) 내 동물병원 업소수
    reg = registered_pets(r["sido"], r["sigungu"]) if r["sido"] else None
    if reg:
        ta["registered_pets"] = reg
    ta["region_label"] = r["region_label"]
    ta["_ingest"] = {
        "source": "소상공인 상권정보 간단분석 PDF + 농림부 시군구 등록수(참조)",
        "parsed": r, "registered_pets": reg,
    }
    # 통계청 SGIS 연동: 시군구 가구수 자동 조회 → 반려가구 정석 계산(가구수×0.28)
    try:
        from . import sgis
        if r["sido"] and sgis.available():
            hh = sgis.lookup(r["sido"], r["sigungu"])
            if hh and hh.get("households"):
                ta["households"] = hh["households"]
                if hh.get("population"):
                    ta["population"] = hh["population"]
                ta["_ingest"]["sgis"] = hh
                ta["_ingest"]["source"] += " + 통계청 SGIS 인구·가구"
    except Exception:
        pass
    return ta


# CLI: python3 -m engine.ingest <pdf>
if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(build_trade_area(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        print("사용법: python3 -m engine.ingest <간단분석.pdf>")
