# -*- coding: utf-8 -*-
"""전국 동물병원 명단(로스터) 적재.

- seed_kakao(region)  : 카카오 키워드검색으로 지역 병원 명단 시드(즉시 사용, 지점당 최대 45)
- import_mois_csv(path): 행정안전부/지자체 인허가 CSV 임포트(전국 전수용)

로스터는 hospitals 테이블에 upsert(중복 namekey 무시).
"""
import csv

from engine import kakao
from . import db


def _region_of(addr):
    toks = ((addr or "").replace("특별자치도", "도").replace("특별시", "")
            .replace("광역시", "").split())
    sido = toks[0] if toks else ""
    sigungu = toks[1] if len(toks) > 1 else ""
    return sido, sigungu


def seed_kakao(region_query, radius_m=5000):
    """지역명(예: '인천 남동구')으로 카카오 검색 → 명단 시드. 반환 (추가수, 총수)."""
    kakao.load_saved_key()
    coord = kakao.geocode(region_query)
    if not coord:
        return (0, 0)
    clinics, _ = kakao.search_animal_hospitals(coord[0], coord[1], radius_m)
    conn = db.connect()
    added = 0
    for c in clinics:
        road = c.get("road", "")
        sido, sigungu = _region_of(road)
        if db.upsert_hospital(conn, {
                "name": c.get("name"), "address": road, "sido": sido, "sigungu": sigungu,
                "source": "kakao"}):
            added += 1
    conn.commit()
    conn.close()
    return (added, len(clinics))


# 행안부/지자체 CSV의 흔한 컬럼명 후보(파일마다 조금씩 다름)
_COL = {
    "name": ["사업장명", "업소명", "상호", "병원명", "기관명"],
    "road": ["도로명전체주소", "도로명주소", "소재지도로명주소"],
    "jibun": ["소재지전체주소", "지번주소", "소재지주소"],
    "phone": ["소재지전화", "전화번호", "연락처"],
    "status": ["영업상태명", "상세영업상태명", "영업상태구분명"],
}


def _pick(row, keys):
    for k in keys:
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
    return ""


def _open_csv(path):
    """정부 CSV 인코딩 자동 감지(대개 cp949/euc-kr, 가끔 utf-8)."""
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            with open(path, encoding=enc) as f:
                f.read(4096)
            return open(path, encoding=enc, newline="")
        except UnicodeDecodeError:
            continue
    return open(path, encoding="cp949", errors="replace", newline="")


def import_mois_csv(path):
    """행안부/지자체 동물병원 인허가 CSV → 명단 적재. 반환 (추가수, 읽은행수).
       좌표(EPSG:5174)는 이 단계에선 저장 안 함 — 필요 시 카카오 지오코딩으로 후처리."""
    conn = db.connect()
    added = n = 0
    with _open_csv(path) as f:
        for row in csv.DictReader(f):
            n += 1
            name = _pick(row, _COL["name"])
            if not name:
                continue
            addr = _pick(row, _COL["road"]) or _pick(row, _COL["jibun"])
            sido, sigungu = _region_of(addr)
            status = _pick(row, _COL["status"])
            if status and ("폐업" in status or "취소" in status or "말소" in status):
                continue                      # 폐업·취소 병원 제외
            if db.upsert_hospital(conn, {
                    "name": name, "address": addr, "sido": sido, "sigungu": sigungu,
                    "phone": _pick(row, _COL["phone"]), "status": status or "영업",
                    "source": "mois_csv"}):
                added += 1
    conn.commit()
    conn.close()
    return (added, n)
