# -*- coding: utf-8 -*-
"""병원 1곳의 채널 센서스 — 네이버 플레이스 '등록 공식채널' + 인스타 검색 폴백.

리포트 경쟁사 분석과 동일한 판정 로직을 재사용(캡처·AI 없음 → 대량 수집용으로 가벼움).
반환 dict: place_id, review_count, homepage/blog/instagram/youtube(0/1), *_url,
          insta_via_search, collect_status(ok/not_found/error), collect_error
"""
import re

from engine import naver_place, autopilot

# 시도 축약 — 행안부 전체주소(서울특별시…)를 네이버 검색용 짧은 형태로
_SIDO_SHORT = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원",
    "충청북도": "충북", "충청남도": "충남", "전라북도": "전북", "전북특별자치도": "전북",
    "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주",
}


def _region_hint(address):
    """행안부 전체주소 → (시도축약, 시군구). 예: '서울특별시 강북구 삼양로 190, …' → ('서울','강북구')."""
    toks = str(address or "").replace(",", " ").split()
    if not toks:
        return "", ""
    sido = _SIDO_SHORT.get(toks[0], toks[0][:2])
    gu = ""
    for t in toks[1:]:                              # 시도 다음의 시/군/구 첫 토큰
        if t.endswith(("시", "군", "구")):
            gu = t
            break
    return sido, gu


def _find_place_smart(name, address):
    """전체주소를 그대로 붙이면 네이버 플레이스 검색이 실패한다(도로명·건물·동 노이즈).
       'name 시도 시군구'로 축약해 조회하고, 실패 시 'name 시군구' → 'name'으로 폴백."""
    sido, gu = _region_hint(address)
    tried = []
    for q in (f"{name} {sido} {gu}".strip(), f"{name} {gu}".strip(), name):
        q = re.sub(r"\s+", " ", q).strip()
        if not q or q in tried:
            continue
        tried.append(q)
        pl = naver_place.find_place(q)
        if not pl:
            continue
        # name만으로 찾은 경우 다른 지역 동명이원(同名) 오매칭 방지 — 주소에 시군구 포함 확인
        if q == name and gu and gu not in (pl.get("address") or ""):
            continue
        return pl
    return None


def collect_one(name, address=""):
    out = {"homepage": 0, "blog": 0, "instagram": 0, "youtube": 0,
           "insta_via_search": 0, "collect_status": "ok"}
    try:
        pl = _find_place_smart(name, address) if address else naver_place.find_place(name)
    except Exception as e:
        out["collect_status"] = "error"
        out["collect_error"] = f"{type(e).__name__}: {e}"[:200]
        return out
    if not pl:
        # 플레이스에서 못 찾음 → 인스타 검색만 폴백 시도
        out["collect_status"] = "not_found"
        try:
            ig = autopilot.search_instagram(name)
            if ig:
                out.update(instagram=1, instagram_url=ig, insta_via_search=1)
        except Exception:
            pass
        return out

    out["place_id"] = pl.get("id")
    out["review_count"] = pl.get("total_reviews")
    for u in pl.get("channels", []):
        low = u.lower()
        if "instagram.com" in low:
            out.update(instagram=1, instagram_url=u)
        elif "blog.naver.com" in low:
            out.update(blog=1, blog_url=u)
        elif "youtube.com" in low or "youtu.be" in low:
            out["youtube"] = 1
        elif "facebook.com" in low:
            continue
        else:
            out.update(homepage=1, homepage_url=u)
    # 인스타 미등록 → 인스타 직접검색 폴백
    if not out["instagram"]:
        try:
            ig = autopilot.search_instagram(name)
            if ig:
                out.update(instagram=1, instagram_url=ig, insta_via_search=1)
        except Exception:
            pass
    return out
