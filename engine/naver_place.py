# -*- coding: utf-8 -*-
"""
네이버 플레이스 리뷰 자동 수집 — 로그인 세션 + Apollo 전역상태 파싱.

네이버 지도/플레이스는 SPA라 <a> 스크래핑이 안 되지만, 데이터를 window.__APOLLO_STATE__
전역에 담는다. 이를 읽어 place id·리뷰수를 안정적으로 얻는다(iframe 클릭 불필요).

검증(2026-09, 부평24시SKY): 방문자리뷰 1,101 + 블로그리뷰 251 = 총 1,352 (네이버 화면 총계와 일치).
네이버는 별점을 없앴으므로(visitorReviewsScore 0) 리뷰 '수'(방문자+블로그)를 기준으로 한다.

의존: capture(playwright + naver 로그인 세션).
"""
import json
import urllib.parse

from . import capture


def _apollo(page):
    try:
        return json.loads(page.evaluate("()=>JSON.stringify(window.__APOLLO_STATE__||{})") or "{}")
    except Exception:
        return {}


def _num(x):
    """'1,385' / 1385 / None → 정수."""
    if x is None:
        return 0
    s = str(x).replace(",", "").strip()
    return int(s) if s.isdigit() else 0


def _find_typename(node, typename):
    """Apollo state를 재귀 순회해 __typename이 일치하는 첫 dict 반환(중첩 inline 객체 대응)."""
    if isinstance(node, dict):
        if node.get("__typename") == typename:
            return node
        for v in node.values():
            r = _find_typename(v, typename)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_typename(v, typename)
            if r is not None:
                return r
    return None


def _registered_channels(state):
    """APOLLO 상태에서 병원이 '플레이스 정보'에 등록한 공식 채널 URL을 수집.
       homepages.repr/etc.url 경로에 담긴 홈페이지·블로그·SNS 링크."""
    urls = []
    seen = set()

    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, path + "/" + k)
        elif isinstance(o, list):
            for v in o:
                walk(v, path)
        elif (isinstance(o, str) and o.startswith("http")
              and "homepage" in path.lower() and "landingurl" not in path.lower()):
            u = o.split("?")[0].rstrip("/")
            if u not in seen and "pcmap" not in u and "place.naver" not in u:
                seen.add(u)
                urls.append(o)

    walk(state)
    return urls


def find_place(query, timeout_ms=30000):
    """네이버 플레이스 검색 → 첫 병원의 리뷰 데이터.
       반환 {id,name,category,address,visitor_reviews,blog_reviews,total_reviews} 또는 None."""
    if not capture.available():
        return None
    from playwright.sync_api import sync_playwright
    sess = capture.session_path("naver") if capture.has_session("naver") else None
    q = urllib.parse.quote(query)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=capture._UA, locale="ko-KR",
                            viewport={"width": 500, "height": 1000}, storage_state=sess)
        pg = ctx.new_page()
        # ① 목록 → place id + 블로그 리뷰수
        try:
            pg.goto(f"https://pcmap.place.naver.com/pet/list?query={q}",
                    wait_until="networkidle", timeout=timeout_ms)
        except Exception:
            pass
        place = None
        for k, v in _apollo(pg).items():
            if (isinstance(v, dict) and k.startswith("PlaceListBusinessesItem")
                    and str(v.get("id", "")).isdigit() and v.get("name")):
                place = {"id": str(v["id"]), "name": v.get("name"),
                         "category": v.get("category"),
                         "address": v.get("roadAddress") or v.get("address"),
                         "blog_reviews": _num(v.get("blogCafeReviewCount"))}
                break
        if not place:
            b.close()
            return None
        # ② 상세 → 방문자 리뷰수(+별점 있으면)
        try:
            pg.goto(f"https://pcmap.place.naver.com/pet/{place['id']}/home",
                    wait_until="networkidle", timeout=timeout_ms)
        except Exception:
            pass
        _state = _apollo(pg)
        for k, v in _state.items():
            if isinstance(v, dict) and str(v.get("id", "")) == place["id"] and "visitorReviewsTotal" in v:
                place["visitor_reviews"] = _num(v.get("visitorReviewsTotal"))
                if v.get("visitorReviewsScore"):
                    place["rating"] = v.get("visitorReviewsScore")
                ph = v.get("phone") or v.get("virtualPhone") or v.get("phoneNo")
                if ph:
                    place["phone"] = str(ph).strip()
                if v.get("roadAddress") or v.get("address"):   # 상세가 더 정확
                    place["address"] = v.get("roadAddress") or v.get("address")
                break
        if not place.get("phone"):        # 상세 상태에 없으면 전 상태에서 전화 탐색
            for k, v in _state.items():
                if isinstance(v, dict):
                    ph = v.get("phone") or v.get("virtualPhone") or v.get("phoneNo")
                    if ph and str(ph).strip():
                        place["phone"] = str(ph).strip()
                        break
        bsd = _find_typename(_state, "BusinessStatusDescription")  # 영업시간(중첩 객체) 재귀탐색
        if bsd:
            bh = " · ".join(x for x in ((bsd.get("status") or "").strip(),
                                        (bsd.get("description") or "").strip()) if x)
            if bh:
                place["business_hours"] = bh
        nb = _find_typename(_state, "PlaceDetailNaverBooking")   # 네이버 예약(온라인 예약) 연동 여부
        if nb is not None:
            url = nb.get("naverBookingUrl") or nb.get("naverBookingHubUrl")
            active = bool(url or nb.get("bookingBusinessId"))     # URL·businessId 있으면 실연동
            place["naver_booking"] = {"active": active, "url": url}
        place["channels"] = _registered_channels(_state)   # 병원 등록 공식 채널 URL
        place.setdefault("visitor_reviews", 0)
        place["total_reviews"] = place["visitor_reviews"] + place["blog_reviews"]
        place["place_url"] = f"https://pcmap.place.naver.com/pet/{place['id']}/home"
        place["review_url"] = f"https://pcmap.place.naver.com/pet/{place['id']}/review/visitor"
        b.close()
        return place
