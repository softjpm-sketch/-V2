# -*- coding: utf-8 -*-
"""
소상공인 빅데이터(bigdata.sbiz.or.kr) 상권 지표 — 행정동(dongCd) 단위.

간단분석 PDF 없이 주소만으로 유동인구·(대표업종)매출을 자동 수집한다.
sg.sbiz.or.kr(웹)이 아니라 그 백엔드 데이터 API를 병원당 1~2회 호출(공개 JSON·로그인 없음).

검증(2026-09, 부평5동 dongCd=28237550):
  - 유동인구: PDF '일일평균 유동인구' 119,494 ↔ API cnt 116,464 (≈1:1) → daily_footfall 로 그대로 사용.
  - 매출: API는 대표 소비업종 5종(편의점·카페·한식·빵·치킨) 점포당 월매출(만원)만 제공.
"""
import json
import urllib.request

_BASE = "https://bigdata.sbiz.or.kr/sbiz/api/bizonSttus"
_HDR = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Referer": "https://bigdata.sbiz.or.kr/",
    "X-Requested-With": "XMLHttpRequest",
}


def _get(ep, dong_cd, timeout=20):
    u = f"{_BASE}/{ep}/search.json?dongCd={dong_cd}&tpbizClscd="
    req = urllib.request.Request(u, headers=_HDR)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("data")


def daily_footfall(dong_cd, dong_name=None):
    """행정동 일일평균 유동인구(명). 없으면 None. (PDF '일일평균 유동인구'와 1:1 검증)"""
    try:
        data = _get("DynPplCmpr", dong_cd) or []
    except Exception:
        return None
    for d in data:                      # 응답: [동, 시군구] — 동을 우선
        if dong_name and d.get("nm") == dong_name:
            return d.get("cnt")
    return data[0].get("cnt") if data else None


def dong_sales_manwon(dong_cd, dong_name=None):
    """행정동 대표 매출액(만원) — 동 vs 시군구 비교의 '동' 값. 상권 소득·소비력 신호."""
    try:
        data = _get("DongMTpctdCmpr", dong_cd) or []
    except Exception:
        return None
    for d in data:                      # 응답: [동, 시군구]
        if dong_name and d.get("nm") == dong_name:
            return d.get("amt")
    return data[0].get("amt") if data else None


def rep_store_sales(dong_cd):
    """대표 소비업종 점포당 월매출(만원) dict {업종명: 매출}. 상권 소비력 참고용."""
    try:
        data = _get("DongSmkndTpbizStorUnitSlsAvg", dong_cd) or []
    except Exception:
        return {}
    return {d.get("tpbizClscdNm"): d.get("mmavgSlsAmt") for d in data if d.get("tpbizClscdNm")}


def dong_store_count(dong_cd):
    """행정동 전체 점포 수. 없으면 None."""
    try:
        d = _get("cfrStcnt", dong_cd)
        return d.get("stcnt") if isinstance(d, dict) else None
    except Exception:
        return None
