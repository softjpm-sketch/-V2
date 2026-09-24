# -*- coding: utf-8 -*-
"""
자동 진단 오케스트레이터 — 캡처(capture) ↔ 비전 분석(ai_draft) 연결.

A단계(현재): URL을 받아 → 자동 캡처 → 기존 비전 분석(draft_channel_from_images) → 채널 진단.
B단계(예정): discover(address) 가 채널 URL을 자동으로 찾아주면 '주소만 넣으면'이 완성된다.

설계 원칙: 채널별 격리(하나 실패해도 나머지 계속) + 실패는 '수동 캡처 폴백'으로 표시.
"""
import os
import re
import urllib.parse

from . import ai_draft, capture

# 홈페이지 후보에서 제외: 플랫폼 + 병원 디렉터리/집계 사이트(진짜 홈페이지가 아님)
_SKIP_HOST = (
    # 플랫폼·검색·지도
    "naver.com", "naver.net", "instagram.com", "facebook.com", "youtube.com", "youtu.be",
    "kakao.com", "kakaocdn", "google.", "daum.net", "tistory.com", "band.us",
    "pf.kakao.com", "map.kakao.com", "blog.me", "modoo.at", "search.naver",
    "cr.shopping.naver", "adcr.naver", "openstreetmap.org", "wikipedia.org", "namu.wiki",
    # 동물병원 디렉터리/집계(진짜 홈페이지 아님)
    "bemypet.kr", "fitpetmall.com", "hospital.fitpetmall", "eolith.co.kr", "yakfact.kr",
    "catchtable", "ohou.se", "vet門", "petdoc", "mypetlife", "animal.go.kr",
    "product-pack.com", "petcaremap", "daangn.com", "karrotmarket.com", "karrot.com",
    "wadiz.kr", "app.catchtable", "place.map.kakao", "vetpartner", "dr-vet",
    "yourdogzone", "vet24.kr", "hospitalk.net", "ban-life.com", "kimgoon.kr",
    "mamama.kr", "sungyesa.com", "pervsi.com", "xn--", "goodoc", "moddoo",
    "go.kr", "or.kr", "petgo.kr", "mypet-119", "onkorea.co.kr", "bowwow.co.kr",
    "hancome.kr", "junkangworld", "hansangsoo", "duli.co.kr", "petfriends",
    "findataatlas", "114-service", "114.co.kr", "sori114", "financialpost",
    "petpro.me", "sbiz-info", "jmapedia", "diningcode", "wikitree", "biztour",
)


def _region(address):
    """주소에서 '시 구' 정도만 뽑아 검색 정확도용."""
    if not address:
        return ""
    toks = address.replace("특별시", "").replace("광역시", "").replace("특별자치도", "").split()
    return " ".join(toks[:2])


def _name_tokens(name):
    """병원명에서 검색·매칭용 토큰(영문/숫자 브랜드) 추출. 예: 'SKY동물의료센터'→['sky']."""
    import re
    toks = re.findall(r"[A-Za-z]{2,}", name or "")
    return [t.lower() for t in toks]


def _classify(links, name=""):
    found = {"homepage": None, "instagram": None, "blog": None, "naverplace": None}
    cands = []          # (href, text)
    seen = set()
    for l in links:
        href = (l.get("href") or "").split("#")[0]
        text = (l.get("text") or "")
        if not href or href in seen:
            continue
        seen.add(href)
        low = href.lower()
        if "instagram.com/" in low and "/p/" not in low and "/explore" not in low:
            found["instagram"] = found["instagram"] or href.split("?")[0]
        elif ("blog.naver.com/" in low or "m.blog.naver.com/" in low):
            # 'MyBlog.naver' 같은 템플릿/가짜 링크 제외 — 실제 블로그ID만
            if "myblog.naver" not in low and not low.rstrip("/").endswith("blog.naver.com"):
                found["blog"] = found["blog"] or href.split("?")[0]
        elif "place.naver.com" in low or "pcmap.place.naver.com" in low:
            found["naverplace"] = found["naverplace"] or href.split("?")[0]
        elif low.startswith("http") and not any(h in low for h in _SKIP_HOST):
            cands.append((href.split("?")[0], text))
    # 홈페이지 우선순위: ① 병원명 브랜드 토큰이 도메인에 있음 ② 앵커텍스트가 '홈페이지'/병원명 ③ 첫 후보
    toks = _name_tokens(name)
    def score(c):
        href, text = c
        host = href.split("//")[-1].split("/")[0].lower()
        s = 0
        if any(t in host for t in toks):
            s += 3                       # 도메인에 브랜드 토큰(가장 강한 신호)
        if "홈페이지" in text or (name and name[:3] in text):
            s += 1
        return s
    if cands and not found["homepage"]:
        best = max(cands, key=score)
        found["homepage"] = best[0]
    found["homepage_candidates"] = [c[0] for c in cands[:8]]
    return found


def discover(name, address="", site="naver"):
    """병원명(+주소)로 네이버 검색을 열어 홈페이지·인스타·블로그·플레이스 URL을 발견.
       반환 {homepage, instagram, blog, naverplace, homepage_candidates}."""
    q = (name + " " + _region(address)).strip()
    url = "https://search.naver.com/search.naver?query=" + urllib.parse.quote(q)
    links = capture.get_links(url, site=site)
    out = _classify(links, name=name)
    out["_query"] = q
    out["_link_count"] = len(links)
    return out

# ai_draft 채널유형(ctype) → 캡처 시 실을 로그인 세션 사이트
CHANNEL_SITE = {
    "homepage": None,        # 공개 페이지 — 세션 불필요
    "instagram": "instagram",
    "naverplace": "naver",
    "blog": "naver",
    "kakao": None,
    "map": None,
    "aeo_geo": None,
}


def build_trade_area_auto(address, radius_m=3000):
    """주소만으로 상권 입력(trade_area) 자동 생성 — PDF 없이.
       카카오(반경 병원수=포화도 분모) + SGIS(시군구 가구→반려가구) + 참조CSV(등록 반려동물수).
       ingest.build_trade_area 와 같은 dict 형식이라 scoring.analyze_trade_area 가 그대로 소비."""
    from . import kakao, sgis, ingest, sbiz
    kakao.load_saved_key()
    sgis.load_saved_key()
    ta = {"_ingest": {"source": "주소 기반 자동", "radius_m": radius_m}}

    # ① 좌표 + 반경 내 동물병원 총계(포화도 분모 · 추정)
    coord = kakao.geocode(address) if kakao.available() else None
    if coord:
        cnt = kakao.region_clinic_count(coord[0], coord[1], radius_m)
        if cnt:
            ta["clinics_in_region"] = cnt
            ta["region_clinics"] = cnt
        ta["_ingest"]["coord"] = coord
        # 입지·역세권: 가장 가까운 지하철역 거리 + 아파트 밀집(가점)
        stn_m, stn_name = kakao.nearest_station(coord[0], coord[1])
        if stn_m is not None:
            ta["nearest_station_m"] = stn_m
            ta["_ingest"]["nearest_station"] = {"m": stn_m, "name": stn_name}
        # 주변 업종(반경 500m): 아파트=주거, 음식점+카페=상업 → 밀집·상권유형 추정
        apt = kakao.apartment_count(coord[0], coord[1], 500)
        food = kakao.category_count("FD6", coord[0], coord[1], 500)
        cafe = kakao.category_count("CE7", coord[0], coord[1], 500)
        if apt:
            ta["apartment_dense"] = apt >= 20        # 반경 500m 아파트 20+ = 밀집
        comm = food + cafe
        if apt or comm:
            ratio = comm / max(apt, 1)
            ta["area_type"] = ("상업 중심" if ratio >= 8
                               else "주거·상업 혼합" if ratio >= 2.5
                               else "주거 밀집형")
            ta["_ingest"]["area_scan"] = {"apt": apt, "food": food, "cafe": cafe,
                                          "ratio": round(ratio, 1)}
    else:
        ta["_ingest"]["warn"] = "지오코딩 실패 — 주소 확인 필요"

    # ② 시도·시군구 → 등록 반려동물수 + SGIS 가구·인구(반려가구 계산 근거)
    sido, sigungu = kakao.region(address) if kakao.available() else (None, None)
    if sido:
        ta["region_label"] = f"{sido} {sigungu}".strip()
        reg = ingest.registered_pets(sido, sigungu)
        if reg:
            ta["registered_pets"] = reg
            ta["_ingest"]["registered_pets"] = reg
        if sgis.available():
            hh = sgis.lookup(sido, sigungu)
            if hh and hh.get("households"):
                ta["households"] = hh["households"]
                if hh.get("population"):
                    ta["population"] = hh["population"]
                ta["_ingest"]["sgis"] = hh
                ta["_ingest"]["source"] += " + SGIS 인구·가구"
    # ③ 유동인구: 소상공인 빅데이터(행정동 단위) — PDF '일일평균 유동인구'와 1:1 검증됨
    dong_cd, dong_nm = kakao.dong_code(address)
    if dong_cd:
        foot = sbiz.daily_footfall(dong_cd, dong_nm)
        if foot:
            ta["daily_footfall"] = foot
        sales = sbiz.dong_sales_manwon(dong_cd, dong_nm)   # 소득·소비력: 동 대표 매출(만원)
        if sales:
            ta["monthly_sales_manwon"] = sales
        ta["_ingest"]["sbiz"] = {"dongCd": dong_cd, "dong": dong_nm,
                                 "daily_footfall": foot, "dong_sales_manwon": sales,
                                 "rep_sales": sbiz.rep_store_sales(dong_cd)}
    return ta


def build_competition_auto(address, clinic_name="", radius_m=3000):
    """주소만으로 경쟁 입력(competition) 자동 생성 — 카카오 반경 경쟁병원 목록.
       analyze_competition이 그대로 소비(밀도·빈자리·프로필은 이름/거리 기반 자동).
       상대 포지션(리뷰수 비교)은 리뷰 수집이 붙어야 채워짐."""
    from . import kakao
    kakao.load_saved_key()
    res = kakao.collect_competition(address, radius_m, self_name=clinic_name)
    if not res.get("ok"):
        return {"clinics": [], "_ingest": {"warn": res.get("error", "카카오 수집 실패")}}
    return {"clinics": res.get("clinics", []),
            "_ingest": {"source": "카카오 반경 경쟁 수집", "total": res.get("total"),
                        "radius_m": res.get("radius_m"), "capped": res.get("capped")}}


def build_review_auto(clinic, slug="auto"):
    """네이버 플레이스에서 리뷰 자동 수집 — 정확한 리뷰수(방문자+블로그) + 비전 감정·키워드.
       못 찾으면 빈 dict."""
    from . import naver_place
    place = naver_place.find_place(clinic.get("name", ""))
    if not place:
        return {}
    rv = {}
    try:                                # 감정·키워드: 리뷰 탭 화면 캡처 → 비전(실제 리뷰 텍스트)
        _, images = capture_channel(place.get("review_url") or place["place_url"], "naverplace", slug=slug)
        rv = ai_draft.draft_review_from_images(clinic, images) or {}
    except Exception:
        rv = {}
    chs = rv.get("channels") or []
    nv = next((c for c in chs if c.get("type") == "naverplace"
               or "네이버" in (str(c.get("source", "")) + str(c.get("name", "")))), None)
    if nv is None:
        nv = {"source": "네이버 플레이스", "type": "naverplace", "sentiment": {}}
        chs.append(nv)
    nv["review_count"] = place["total_reviews"]   # 정확한 총계로 덮어씀(방문자+블로그)
    nv["_visitor"], nv["_blog"] = place["visitor_reviews"], place["blog_reviews"]
    if place.get("rating"):
        nv["rating"] = place["rating"]
    rv["channels"] = chs
    rv["_place"] = place
    # 구글 리뷰 채널(키 있으면) — 평점·리뷰수·별점 기반 감정
    from . import google_places
    google_places.load_saved_key()
    if google_places.available():
        try:
            gc = google_places.review_channel(clinic.get("name", ""))
            if gc and gc.get("review_count"):
                chs.append(gc)
                rv["channels"] = chs
        except Exception:
            pass
    syn = ai_draft.synthesize_reviews(clinic, rv)
    if syn:
        rv["synthesis"] = syn
    return rv


_VET_HINT = ("동물병원", "동물의료", "메디컬", "진료", "수의", "예약", "반려", "펫")


def _brand_variants(name):
    """병원명에서 지역·'24시'·일반 접미어를 벗겨 식별용 브랜드 토큰 후보를 만든다."""
    base = re.sub(r"(24시|365일|동물메디컬센터|동물의료센터|메디컬센터|의료센터|"
                  r"동물병원|동물의료|동물|병원|의료|센터)", "", name).strip()
    out = {name.strip(), base}
    if len(base) > 2:                      # 앞 2글자(지역)를 벗긴 변형도(예: 인천유앤미→유앤미)
        out.add(base[2:])
    return {v for v in out if len(v) >= 2}


# 디렉토리·집계 사이트의 전형적 경로(개별 병원 상세페이지) — 자기 홈페이지 아님
_DIR_PATH = re.compile(
    r"/(hospital|hospitals|clinic|clinics|detail|store|places?|view|profile|list|services"
    r"|sbiz-info|map|search|info|shop|company|business)(/|$)"
    r"|[0-9a-f]{8}-[0-9a-f]{4}", re.I)


def _looks_like_own_site(url):
    """디렉토리 상세페이지가 아닌, 자기 도메인 루트/얕은 경로인가."""
    low = url.lower()
    if any(h in low for h in _SKIP_HOST):
        return False
    path = "/" + url.split("//")[-1].split("/", 1)[1] if "/" in url.split("//")[-1] else "/"
    if _DIR_PATH.search(path):
        return False
    return True


def _verify_channel_page(url, name, site=None):
    """채널 페이지를 실제로 열어(렌더 텍스트) 병원 브랜드가 등장하는지 확인.
       (검색에 URL이 떴다는 이유만으로 '운영' 처리하지 않기 위함)."""
    try:
        text = capture.get_text(url, site=site)
    except Exception:
        return False
    return bool(text) and any(v in text for v in _brand_variants(name))


def resolve_competitor_homepage(name, candidates, site="naver"):
    """후보 URL을 실제로 열어(렌더 텍스트) 병원명이 나오고 동물병원 사이트인 곳을 홈페이지로 확정.
       디렉토리 상세페이지(petgo·mypet 등)는 '자기 홈페이지'가 아니므로 제외, 루트 도메인 우선.
       반환 (url, page_text) 또는 (None, "")."""
    variants = _brand_variants(name)
    # 자기 사이트로 보이는 후보만, 경로가 얕은(루트) 순으로
    cands = [u for u in candidates if _looks_like_own_site(u)]
    cands.sort(key=lambda u: (u.rstrip("/").count("/"), len(u)))
    for url in cands[:6]:
        try:
            text = capture.get_text(url, site=None)
        except Exception:
            continue
        if not text or len(text) < 40:
            continue
        if any(v in text for v in variants) and any(h in text for h in _VET_HINT):
            return url, text
    return None, ""


def enrich_competitor_reviews(competition, clinic=None, top_n=3):
    """리포트 '추천 Top3'와 동일한 상위 경쟁사에 네이버 리뷰수 + 구글 평점을 채움."""
    from . import naver_place, google_places, scoring
    google_places.load_saved_key()
    if clinic is not None:
        targets = [r["_ref"] for r in scoring.top_rivals(competition, clinic, top_n)]
    else:
        targets = competition.get("clinics", [])[:top_n]
    for c in targets:
        nm = c.get("name", "")
        if c.get("review_count") is None:
            try:
                pl = naver_place.find_place(nm)
                if pl:
                    c["review_count"] = pl["total_reviews"]
            except Exception:
                pass
        if c.get("rating") is None and google_places.available():
            try:
                g = google_places.find(nm)          # 네이버는 별점 폐지 → 구글 평점 보강
                if g and g.get("rating"):
                    c["rating"] = g["rating"]
            except Exception:
                pass
    return competition


def search_instagram(name):
    """인스타에서 병원명 검색 → 계정 표시이름(full_name)이 병원 브랜드와 맞는 계정 URL. 실패 None.
       (플레이스에 인스타를 등록 안 한 병원용 폴백. 로그인 세션 필요.)"""
    import json as _json
    url = ("https://www.instagram.com/web/search/topsearch/?context=blended&query="
           + urllib.parse.quote(name))
    try:
        txt = capture.get_text(url, site="instagram")
    except Exception:
        return None
    if not txt:
        return None
    try:
        data = _json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return None
        try:
            data = _json.loads(m.group(0))
        except Exception:
            return None
    variants = _brand_variants(name)
    for u in data.get("users", []):
        info = u.get("user", {})
        full = info.get("full_name", "") or ""
        uname = info.get("username", "") or ""
        if uname and any(v in full for v in variants):    # 표시이름에 병원 브랜드가 들어간 계정만
            return "https://www.instagram.com/" + uname
    return None


def enrich_competitor_marketing(competition, clinic=None, region="", top_n=3):
    """리포트 '추천 Top3'만 대상. 채널 유무는 네이버 플레이스에 병원이 '직접 등록한 공식 채널'
       기준(등록=운영, 미등록=없음 — 관리 안 하는 것으로 간주). 인스타는 미등록 시 인스타
       직접검색으로 폴백. 홈페이지가 등록돼 있으면 본문에서 진료과목 판독.
       리포트 섹션 10(경쟁사 마케팅·특화 매트릭스)이 소비."""
    from . import scoring, naver_place
    if clinic is not None:
        rivals = scoring.top_rivals(competition, clinic, top_n)
    else:
        rivals = [{"name": c.get("name", ""), "_ref": c}
                  for c in competition.get("clinics", [])[:top_n]]
    rms = []
    for rv in rivals:
        nm = rv.get("name", "")
        c = rv.get("_ref", {})
        if not nm:
            continue
        # 미등록=없음(확인). 플레이스 등록 채널을 진실로 삼는다.
        entry = {"name": nm, "homepage": "없음", "blog": "없음", "instagram": "없음"}
        if c.get("review_count") is not None:
            entry["place_review"] = c["review_count"]
        homepage_url = None
        try:
            pl = naver_place.find_place(nm)
            for u in (pl or {}).get("channels", []):
                low = u.lower()
                if "instagram.com" in low:
                    entry["instagram"] = "운영"
                    entry["instagram_url"] = u
                elif "blog.naver.com" in low:
                    entry["blog"] = "운영"
                    entry["blog_url"] = u
                elif "youtube.com" in low or "youtu.be" in low or "facebook.com" in low:
                    continue                       # 부가 SNS — 3채널 집계엔 미포함
                else:
                    entry["homepage"] = "운영"
                    entry["homepage_url"] = u
                    homepage_url = homepage_url or u
        except Exception:
            pass
        # 인스타 미등록 → 인스타 직접검색 폴백
        if entry["instagram"] == "없음":
            try:
                ig = search_instagram(nm)
                if ig:
                    entry["instagram"] = "운영"
                    entry["instagram_url"] = ig
            except Exception:
                pass
        # 진료과목 판독: 홈페이지 + 블로그(모바일 iframe 우회) 본문에서
        spec_text = ""
        if homepage_url:
            try:
                spec_text += " " + (capture.get_text(homepage_url, site=None) or "")
            except Exception:
                pass
        if entry.get("blog_url"):
            m_url = entry["blog_url"].replace("blog.naver.com", "m.blog.naver.com")
            try:
                spec_text += " " + (capture.get_text(m_url, site="naver") or "")
            except Exception:
                pass
        if spec_text.strip():
            specs = sorted(scoring._match_specs(spec_text))
            if specs:
                entry["specialty"] = specs
        rms.append(entry)
    if rms:
        competition["rival_marketing"] = rms
    return competition


_UA_FETCH = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _fetch_html(url, timeout=8, max_bytes=600000):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": _UA_FETCH})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(max_bytes)
    try:
        return raw.decode("utf-8", "replace")
    except Exception:
        return raw.decode("cp949", "replace")


def discover_own_urls(name, address, disc):
    """자사 채널 URL 자동 수집. **네이버 플레이스 등록 공식채널을 진실로**(경쟁사와 동일 기준) —
       홈페이지/블로그/인스타는 병원이 플레이스에 등록한 URL 우선. 미등록만 검증된 검색결과로 폴백
       (홈피는 실제 열어 병원명 확인, 인스타는 인스타검색). + 카카오맵 + 홈피 내부링크(카톡·T맵).
       aeo_geo는 URL이 아니라 별도 분석."""
    from . import naver_place, kakao
    kakao.load_saved_key()
    url_map = {}
    # ① 플레이스 등록 채널(신뢰)
    try:
        pl = naver_place.find_place((name + " " + address).strip() if address else name)
    except Exception:
        pl = None
    if pl:
        if pl.get("place_url"):
            url_map["naverplace"] = pl["place_url"]
        for u in pl.get("channels", []):
            low = u.lower()
            if "instagram.com" in low:
                url_map.setdefault("instagram", u)
            elif "blog.naver.com" in low:
                url_map.setdefault("blog", u)
            elif "youtube.com" in low or "youtu.be" in low or "facebook.com" in low:
                continue                       # 부가 SNS — 8채널 진단엔 미포함
            else:
                url_map.setdefault("homepage", u)   # 등록된 자기 도메인(진짜 홈피)
    # ② 미등록 채널만 검색결과로 폴백(홈피·블로그는 실제 열어 검증, 인스타는 인스타검색)
    if "homepage" not in url_map:
        cands = ([disc["homepage"]] if disc.get("homepage") else []) + (disc.get("homepage_candidates") or [])
        hp, _ = resolve_competitor_homepage(name, cands)   # 병원명·동물병원 확인된 것만
        if hp:
            url_map["homepage"] = hp
    if "blog" not in url_map and disc.get("blog") and _verify_channel_page(disc["blog"], name, site="naver"):
        url_map["blog"] = disc["blog"]
    if "instagram" not in url_map:
        try:
            ig = search_instagram(name)
            if ig:
                url_map["instagram"] = ig
        except Exception:
            pass
    if "naverplace" not in url_map and disc.get("naverplace"):
        url_map["naverplace"] = disc["naverplace"]
    # 카카오맵
    try:
        murl = kakao.find_place_url(name, address)
        if murl:
            url_map["map"] = murl
    except Exception:
        pass
    # 홈페이지 내부 링크에서 카카오톡 채널·T맵 발견(있을 때만)
    hp = url_map.get("homepage")
    if hp:
        try:
            for l in capture.get_links(hp):
                low = (l.get("href") or "").lower()
                if "pf.kakao.com/" in low and "kakao" not in url_map:
                    url_map["kakao"] = l["href"]
                elif ("tmap" in low or "tmobiweb" in low) and "tmap" not in url_map:
                    url_map["tmap"] = l["href"]
        except Exception:
            pass
    return url_map


_AEO_SIGNALS = [
    ("application/ld+json", "구조화데이터(JSON-LD)"),
    ('name="description"', "메타 설명(description)"),
    ("og:title", "Open Graph(공유 카드)"),
    ("faqpage", "FAQ 구조화(FAQPage)"),
    ("tel:", "전화 tel: 링크"),
    ("viewport", "모바일 뷰포트"),
]


def _nap_phone(v):
    if not v:
        return None
    d = re.sub(r"[^\d]", "", str(v))
    return d or None


def _nap_name(v):
    if not v:
        return None
    return re.sub(r"[\s()]", "", str(v)).lower() or None


def _nap_addr(v):
    """도로명 주소 핵심 토큰만 남긴다 — 괄호(법정동)·층/호·구분자 제거 후 공백 삭제."""
    if not v:
        return None
    s = re.sub(r"\(.*?\)", "", str(v))          # (역삼동) 등 제거
    s = re.sub(r"\d+\s*층.*", "", s)            # '3층 …' 이하 제거
    s = re.sub(r"[,\-]", " ", s)
    s = re.sub(r"\s+", "", s)
    return s.lower() or None


def _nap_match(field, values):
    """소스별 정규화값 목록 → 일관 여부. name/phone은 포함관계 허용, address는 토큰 포함."""
    vals = [v for v in values if v]
    if len(vals) < 2:
        return None                             # 대조 불가(값 있는 소스 1개 이하)
    if field == "phone":
        return len(set(vals)) == 1
    if field == "name":                         # '24시샤인…' vs '샤인…' 같은 접두 차이 허용
        return all(a in b or b in a for a in vals for b in vals)
    # address: 짧은 쪽이 긴 쪽에 포함되면 동일 위치로 간주(층/호 표기차 흡수)
    return all(min(a, b, key=len) in max(a, b, key=len) for a in vals for b in vals)


def nap_consistency(clinic, homepage_facts=None):
    """홈페이지·네이버플레이스·카카오맵의 NAP(상호·주소·전화)를 코드로 실측 대조.
       AI 추정이 아니라 각 소스의 구조화값을 정규화해 일치 여부를 확정한다.
       반환 {sources, fields, score, checked, matched, summary} 또는 None(소스<2)."""
    name = clinic.get("name", "")
    address = clinic.get("address", "")
    sources = {}
    try:
        from . import naver_place, kakao
    except Exception:
        return None
    try:
        pl = (naver_place.find_place((name + " " + address).strip()) if address
              else naver_place.find_place(name)) or naver_place.find_place(name)
        if pl:
            sources["네이버 플레이스"] = {"name": pl.get("name"),
                                    "address": pl.get("address"), "phone": pl.get("phone")}
    except Exception:
        pass
    try:
        kakao.load_saved_key()
        kp = kakao.find_place_nap(name, address)
        if kp:
            sources["카카오맵"] = {"name": kp.get("name"),
                                "address": kp.get("address"), "phone": kp.get("phone")}
    except Exception:
        pass
    hf = homepage_facts or {}
    if hf.get("phone"):                          # 홈페이지는 전화(tel:)만 신뢰 — 상호/주소는 약함
        sources["홈페이지"] = {"name": None, "address": None, "phone": hf.get("phone")}

    if len(sources) < 2:
        return None

    norm = {"name": _nap_name, "address": _nap_addr, "phone": _nap_phone}
    labels = {"name": "상호", "address": "주소", "phone": "전화"}
    weight = {"name": 3, "address": 3, "phone": 4}     # 전화 불일치가 엔티티에 가장 치명적
    fields, checked, matched, penalty, wtotal = {}, 0, 0, 0, 0
    for f in ("name", "address", "phone"):
        raw_vals = {src: d.get(f) for src, d in sources.items() if d.get(f)}
        note = None
        if f == "phone":
            # 050x = 네이버 등 안심번호(가상). 원장 데이터 오류가 아니므로 실번호끼리만 대조.
            reals, has_virtual = {}, False
            for src, p in raw_vals.items():
                dd = _nap_phone(p)
                if not dd:
                    continue
                if dd.startswith("050"):
                    has_virtual = True
                else:
                    reals[src] = dd
            if len(raw_vals) < 2:
                cons = None
            elif len(set(reals.values())) >= 2:
                cons = False                    # 서로 다른 실번호 = 진짜 불일치
            else:
                cons = True
                if has_virtual:
                    note = "안심번호(0507 등) 사용 — 실번호와 표기가 달라 보일 뿐 정상"
        else:
            cons = _nap_match(f, [norm[f](v) for v in raw_vals.values()])
        fields[f] = {"label": labels[f], "values": raw_vals,
                     "consistent": cons, "note": note}
        if cons is None:
            continue
        checked += 1
        wtotal += weight[f]
        if cons:
            matched += 1
        else:
            penalty += weight[f]
    if checked == 0:
        return None
    score = round(100 * (wtotal - penalty) / wtotal) if wtotal else None
    bad = [labels[f] for f in ("name", "address", "phone")
           if fields[f]["consistent"] is False]
    if bad:
        summary = "NAP 불일치: " + "·".join(bad) + f" ({len(sources)}개 소스 대조)"
    else:
        summary = f"NAP 일관됨 — 상호·주소·전화가 {len(sources)}개 소스에서 일치"
    return {"sources": sources, "fields": fields, "score": score,
            "checked": checked, "matched": matched, "summary": summary}


def _nap_memo(nap):
    """nap_consistency 결과 → analyze_aeo raw에 붙일 실측 근거 텍스트."""
    if not nap:
        return ""
    lines = ["", "◆ NAP(상호·주소·전화) 실측 대조 — 코드로 확인된 사실(추정 아님):"]
    for f in ("name", "address", "phone"):
        fd = nap["fields"].get(f, {})
        cons = fd.get("consistent")
        mark = "확인불가(소스 부족)" if cons is None else ("일치 ✅" if cons else "불일치 ⚠️")
        vals = "; ".join(f"{src}={v}" for src, v in fd.get("values", {}).items()) or "값 없음"
        extra = f" — {fd['note']}" if fd.get("note") else ""
        lines.append(f"- {fd.get('label', f)}: {mark} [{vals}]{extra}")
    lines.append(f"→ NAP 실측 점수 {nap['score']}점. 이 사실을 근거로 '엔티티·NAP 일관성'을 진단하라(추정 금지).")
    lines.append("  NAP가 소스마다 다르면 AI/검색엔진이 '같은 병원'으로 확신하지 못해 추천에서 밀린다.")
    return "\n".join(lines)


def analyze_aeo(clinic, homepage_url):
    """홈페이지 렌더 DOM에서 AI검색 노출(AEO·GEO) 기술 신호를 추출해 채널로 진단.
       정적 HTML은 SPA에서 tel:·JSON-LD·og 등이 JS로 주입돼 누락되므로 렌더 DOM을 쓴다."""
    try:
        html = capture.get_dom(homepage_url)        # 렌더 후 실제 DOM
    except Exception:
        html = ""
    if not html:
        try:
            html = _fetch_html(homepage_url)         # 폴백(정적)
        except Exception:
            return None
    if not html:
        return None
    low = html.lower()
    lines = [f"- {label}: {'있음' if token in low else '없음'}" for token, label in _AEO_SIGNALS]
    raw = ("홈페이지 AEO·GEO(생성형 AI 검색 노출) 기술 신호 점검:\n" + "\n".join(lines) +
           f"\n(원본: {homepage_url})\nNAP(상호·주소·전화) 일관성과 생성엔진 노출 관점에서 진단하라.")
    # NAP 실측 대조: 홈페이지 전화(tel:) + 네이버플레이스 + 카카오맵을 코드로 비교
    tel = re.findall(r'href=["\']tel:([^"\']+)', html, re.I)
    hp_facts = {"phone": tel[0].strip()} if tel else {}
    nap = None
    try:
        nap = nap_consistency(clinic, hp_facts)
    except Exception:
        nap = None
    if nap:
        raw += "\n" + _nap_memo(nap)
    try:
        ch = ai_draft.draft_channel(clinic, "aeo_geo", raw)
    except Exception:
        return None
    if ch:
        ch["_source_url"] = homepage_url
        if nap:
            ch["_nap"] = nap        # 리포트/검수에서 실측 대조 표로 활용 가능
    return ch


def build_config_auto(name, address, tier=2, deep=False, slug=None, date=""):
    """주소만으로 전체 진단 입력(config)을 자동 조립.
       기본: 상권(100%)+경쟁(70%) — AI·캡처 없이 즉시.
       deep=True: + 마케팅(8채널 발견→캡처→비전)·리뷰(플레이스 캡처→비전) best-effort."""
    import re
    slug = slug or ("auto_" + (re.sub(r"[^0-9A-Za-z가-힣]", "", name)[:20] or "clinic"))
    clinic = {"name": name, "slug": slug, "address": address, "tier": tier, "date": date}
    cfg = {"clinic": clinic,
           "trade_area": build_trade_area_auto(address),
           "competition": build_competition_auto(address, clinic_name=name)}
    if not deep:
        return cfg

    ai_draft.load_saved_key()            # 정밀 분석은 AI 필수 — 스크립트 호출에도 키 보장
    try:
        from . import google_places
        google_places.load_saved_key()
    except Exception:
        pass

    # ── 정밀: 8채널 발견 → 마케팅(홈피·블로그·인스타·플레이스·카카오맵·카톡·T맵·AEO) + 리뷰 ──
    disc = discover(name, address)
    cfg["_discover"] = disc
    url_map = discover_own_urls(name, address, disc)
    if url_map:
        r = analyze_urls(clinic, url_map, slug=slug, dry_run=False)
        channels = [c for c in r.get("channels", []) if c.get("score") is not None]
        hp = url_map.get("homepage")
        if hp:                                        # AEO·GEO = 홈페이지 구조 분석(캡처 아님)
            aeo = analyze_aeo(clinic, hp)
            if aeo and aeo.get("score") is not None:
                channels.append(aeo)
        if channels:
            mk = {"channels": channels}
            syn = ai_draft.synthesize_marketing(clinic, channels)
            if syn:
                mk["synthesis"] = syn
            spec = ai_draft.extract_specialties(clinic, channels)
            if spec:
                mk["specialty_analysis"] = spec
            cfg["marketing"] = mk
    rv = build_review_auto(clinic, slug=slug)
    if rv:
        cfg["review"] = rv
    enrich_competitor_reviews(cfg["competition"], clinic)   # 추천 Top3 리뷰수+구글평점
    try:                                                    # 추천 Top3 채널·진료과목 실제 판독
        enrich_competitor_marketing(cfg["competition"], clinic, region=_region(address))
    except Exception:
        pass
    return cfg


def capture_channel(url, ctype, slug="auto"):
    """URL을 캡처해 (대표png경로, [(bytes,'image/png'), ...]) 반환. 실패 시 예외.
       홈페이지는 스크롤 애니메이션·플로팅 버튼 대응을 위해 뷰포트 단위 여러 장 캡처."""
    site = CHANNEL_SITE.get(ctype)
    if ctype == "homepage":
        seg_dir = os.path.join(capture.CAPTURE_DIR, slug, "homepage")
        paths = capture.screenshot_segments(url, site=site, out_dir=seg_dir)
        if not paths:                                   # 폴백: 단일 전체캡처
            out = os.path.join(capture.CAPTURE_DIR, slug, "homepage.png")
            paths = [capture.screenshot(url, site=site, out_path=out)]
    elif ctype == "instagram":
        # 프로필(그리드) + 릴스 탭 2장 — 그리드만 보고 '릴스 없음' 오판 방지
        paths = [capture.screenshot(url, site=site, full_page=False,
                                    out_path=os.path.join(capture.CAPTURE_DIR, slug, "instagram.png"))]
        try:
            reels = url.rstrip("/") + "/reels/"
            paths.append(capture.screenshot(reels, site=site, full_page=False,
                         out_path=os.path.join(capture.CAPTURE_DIR, slug, "instagram_reels.png")))
        except Exception:
            pass
    else:
        out = os.path.join(capture.CAPTURE_DIR, slug, f"{ctype}.png")
        paths = [capture.screenshot(url, site=site, out_path=out)]
    images = []
    for pth in paths:
        with open(pth, "rb") as f:
            images.append((f.read(), "image/png"))
    return paths[0], images


def _cta_position(probe):
    """전화/카카오 고정 플로팅 컨테이너의 computed 위치 → 한국어 위치 설명(병원마다 다름)."""
    if not probe or not probe.get("found"):
        return ""

    def num(v):
        try:
            return float(str(v).replace("px", "").strip())
        except Exception:
            return None
    right, left = num(probe.get("right")), num(probe.get("left"))
    top, bottom = num(probe.get("top")), num(probe.get("bottom"))
    width = num(probe.get("width"))
    vw, vh = probe.get("vw") or 1280, probe.get("vh") or 900
    # 하단 가로 바(모바일형): 폭이 화면 전체에 가깝고 하단 고정
    if width and width > vw * 0.8 and bottom is not None and bottom < 80:
        return "하단 바"
    # 가로: right/left 중 실제 지정된 쪽
    side = ""
    if right is not None and (left is None or right <= left):
        side = "우측"
    elif left is not None:
        side = "좌측"
    # 세로: bottom 지정이면 하단, 아니면 top 비율로
    ver = ""
    if bottom is not None and (top is None or bottom < top):
        ver = "하단"
    elif top is not None:
        r = top / vh
        ver = "상단" if r < 0.3 else ("하단" if r > 0.7 else "중앙")
    return (side + " " + ver).strip()      # 예: "우측 상단", "좌측 하단", "" (미상)


def homepage_dom_facts(url):
    """홈페이지 렌더 DOM(HTML)에서 CTA·SEO·SNS 사실을 코드로 직접 추출 → (facts, memo).
       화면 캡처엔 안 보이는 tel:·카카오·메타·구조화데이터를 코드에서 확정한다(하이브리드)."""
    try:
        html, cta_probe = capture.get_dom(url, with_cta=True)
    except Exception:
        return {}, ""
    if not html:
        return {}, ""
    low = html.lower()
    tel = re.findall(r'href=["\'](tel:[^"\']+)', html, re.I)
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([^"\']+)', html, re.I)
    f = {
        "phone": (tel[0].replace("tel:", "").strip() if tel else None),
        "kakao_channel": bool(re.search(r'pf\.kakao\.com/', low)),
        "naver_talk": bool(re.search(r'talk\.naver\.com/', low)),
        "booking": bool(re.search(r'예약|상담신청|온라인\s*예약|진료예약', html)),
        "instagram": bool(re.search(r'instagram\.com/', low)),
        "blog": bool(re.search(r'blog\.naver\.com/', low)),
        "youtube": bool(re.search(r'youtube\.com/|youtu\.be/', low)),
        "meta_description": (m.group(1)[:160] if m else None),
        "og": bool(re.search(r'og:title', low)),
        "json_ld": bool(re.search(r'application/ld\+json', low)),
        "viewport": bool(re.search(r'name=["\']viewport', low)),
    }
    cta = []
    if f["phone"]:
        cta.append(f"전화 {f['phone']}(tel: 링크)")
    if f["kakao_channel"]:
        cta.append("카카오톡 채널 상담")
    if f["naver_talk"]:
        cta.append("네이버 톡톡 상담")
    if f["booking"]:
        cta.append("예약/상담 메뉴")
    # 전화·카카오가 고정 플로팅 컨테이너에 있으면 '상시 노출 CTA' — 실제 위치까지 판정
    has_contact = bool(f["phone"] or f["kakao_channel"])
    floating = cta_probe.get("found") or (has_contact and bool(re.search(  # JS 실패 시 클래스 힌트 폴백
        r'class=["\'][^"\']*(quick[-_]?menu|quick[-_]?button|float|floating|'
        r'side[-_]?menu|fab|sticky[-_]?(btn|menu|bar))[^"\']*["\']', low)))
    f["cta_floating"] = bool(floating and has_contact)
    f["cta_position"] = (_cta_position(cta_probe) if cta_probe.get("found") else "") \
        if f["cta_floating"] else None      # "" = 플로팅 확정이나 위치 미상
    seo = [f"메타 description {'있음' if f['meta_description'] else '없음'}",
           f"OG태그 {'있음' if f['og'] else '없음'}",
           f"구조화데이터(JSON-LD) {'있음' if f['json_ld'] else '없음'}",
           f"모바일 뷰포트 {'있음' if f['viewport'] else '없음'}"]
    sns = [lab for k, lab in (("instagram", "인스타"), ("blog", "블로그"), ("youtube", "유튜브"))
           if f.get(k)]
    cta_line = "· 전환/연락 동선(코드 확인): " + (", ".join(cta) if cta else "전화·예약·상담 링크 미검출")
    if f["cta_floating"]:
        where = f"화면 {f['cta_position']}에" if f["cta_position"] else "화면에"
        cta_line += f" — {where} 고정된 플로팅 버튼으로 상시 노출됨"
    lines = [cta_line, "· SEO/AEO(코드 확인): " + ", ".join(seo)]
    if sns:
        lines.append("· 연결 SNS(코드 확인): " + ", ".join(sns))
    if f["meta_description"]:
        lines.append("· 메타설명 내용: " + f["meta_description"])
    if f["cta_floating"]:
        where = f"화면 {f['cta_position']}에" if f["cta_position"] else "화면에"
        rule = (f"\n※ 전화·카카오 상담이 {where} 고정 플로팅 버튼으로 상시 노출된다. 전환 동선을 "
                "양호 이상으로 평가하고, '시인성 확인 필요·명확히 안 보임·버튼이 안 보인다'류 표현을 쓰지 말 것.")
    else:
        rule = ""
    memo = ("[홈페이지 HTML 코드에서 직접 추출한 사실 — 배경영상/플로팅 위젯이라 화면상 겉으론 "
            "드러나지 않아도 실제 존재한다. 전환·SEO 평가에 반드시 반영하고, 여기 '있음'인 항목을 "
            "'없음/확인 불가'로 깎지 말 것]\n" + "\n".join(lines) + rule)
    return f, memo


def blog_cadence(blog_url, max_items=50):
    """네이버 블로그 RSS에서 최근 글의 발행 주기(전체·카테고리별)를 계산 → (facts, lines).
       스크린샷으론 못 보는 '얼마나 꾸준히·무슨 카테고리로 올리는지'를 수치로 확정."""
    import urllib.request
    from email.utils import parsedate_to_datetime
    from collections import defaultdict
    m = re.search(r'blog\.naver\.com/([^/?#]+)', blog_url)
    if not m:
        return {}, []
    try:
        req = urllib.request.Request(f"https://rss.blog.naver.com/{m.group(1)}.xml",
                                     headers={"User-Agent": _UA_FETCH})
        xml = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
    except Exception:
        return {}, []
    rows = []
    for it in re.findall(r'<item>(.*?)</item>', xml, re.S)[:max_items]:
        d = re.search(r'<pubDate>(.*?)</pubDate>', it)
        c = re.search(r'<category>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</category>', it, re.S)
        if not d:
            continue
        try:
            rows.append((parsedate_to_datetime(d.group(1)), (c.group(1).strip() if c else "기타")))
        except Exception:
            pass
    if len(rows) < 3:
        return {}, []
    rows.sort(key=lambda x: x[0], reverse=True)
    dates = [r[0] for r in rows]
    span = (dates[0] - dates[-1]).days or 1
    n = len(dates)
    per_wk = round(n / (span / 7), 1)
    cat = defaultdict(list)
    for dt, c in rows:
        cat[c].append(dt)
    cat_lines = []
    for c, ds in sorted(cat.items(), key=lambda x: -len(x[1]))[:6]:
        ds.sort()
        sp = (ds[-1] - ds[0]).days
        pw = round(len(ds) / (sp / 7), 1) if sp >= 7 else len(ds)
        cat_lines.append(f"{c} 주{pw}회")
    facts = {"posts_rss": n, "span_days": span, "per_week": per_wk,
             "latest": dates[0].strftime("%Y-%m-%d"), "by_category": cat_lines}
    lines = [f"발행 빈도(RSS 실측 최근 {n}개): 주 {per_wk}회 · 평균 {span/(n-1):.1f}일 간격 · 최신 {facts['latest']}",
             "카테고리별 발행: " + ", ".join(cat_lines)]
    return facts, lines


def blog_recent_post(blog_url):
    """RSS 최근 글 1개를 실제로 열어 콘텐츠 충실도(본문길이·사진수·해시태그·상담동선) 측정.
       블로그 리스트 화면만으론 안 되던 '개별 글 품질'을 실측으로 보완 → (facts, lines)."""
    import urllib.request
    m = re.search(r'blog\.naver\.com/([^/?#]+)', blog_url)
    if not m:
        return {}, []
    try:
        req = urllib.request.Request(f"https://rss.blog.naver.com/{m.group(1)}.xml",
                                     headers={"User-Agent": _UA_FETCH})
        xml = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
    except Exception:
        return {}, []
    items = re.findall(r'<item>(.*?)</item>', xml, re.S)
    if not items:
        return {}, []

    def clean(mm):
        return re.sub(r'<!\[CDATA\[|\]\]>', '', mm.group(1)).strip() if mm else ''

    # RSS 순서에 의존하지 않고 pubDate가 가장 최신인 글을 선택(고정공지·정렬어긋남 대비)
    from email.utils import parsedate_to_datetime
    best, best_dt = items[0], None
    for cand in items:
        d = re.search(r'<pubDate>(.*?)</pubDate>', cand)
        if not d:
            continue
        try:
            dt = parsedate_to_datetime(d.group(1))
        except Exception:
            continue
        if best_dt is None or dt > best_dt:
            best, best_dt = cand, dt
    it = best
    link = clean(re.search(r'<link>(.*?)</link>', it, re.S)).split('?')[0]
    title = clean(re.search(r'<title>(.*?)</title>', it, re.S))
    if not link:
        return {}, []
    try:
        text, imgs = capture.blog_post_metrics(link.replace("blog.naver.com", "m.blog.naver.com"),
                                               site="naver")
    except Exception:
        return {}, []
    if not text or len(text) < 100:
        return {}, []
    tags = re.findall(r'#[^\s#]{1,20}', text)[:8]
    has_cta = [w for w in ("예약", "상담", "문의", "오시는길", "전화") if w in text]
    kw = [w for w in ("진단", "수술", "치료", "증상", "케이스", "후기") if w in text]
    f = {"latest_title": title, "latest_url": link,
         "latest_date": best_dt.strftime("%Y-%m-%d") if best_dt else None,
         "post_chars": len(text), "post_images": imgs,
         "post_tags": tags, "post_cta": bool(has_cta)}
    parts = [f"본문 {len(text):,}자", f"사진 {imgs}장"]
    if tags:
        parts.append("해시태그 " + " ".join(tags[:5]))
    if kw:
        parts.append("전문키워드(" + "·".join(kw) + ")")
    if has_cta:
        parts.append("본문 내 " + "/".join(has_cta) + " 동선 있음")
    else:                                   # 부재도 실측 사실로 단정(‘확인 필요’ 방지)
        parts.append("본문 내 예약·상담·전화 동선 없음")
    lines = [f"최근 글 실측(예시 '{title[:24]}'): " + " · ".join(parts)]
    return f, lines


def blog_dom_facts(blog_url):
    """네이버 블로그 실측 지표: 이웃·방문(모바일) + 발행주기(RSS) + 최근 글 심층(본문·사진).
       스크린샷이 못 보는 것 → (facts, memo). 하이브리드 블로그 분석용."""
    f = {}
    lines = []
    m_url = blog_url.replace("blog.naver.com", "m.blog.naver.com")
    try:
        t = capture.get_text(m_url, site="naver")
    except Exception:
        t = ""
    if t:
        mm = re.search(r'([\d,]+)\s*명의?\s*이웃', t)
        if mm:
            f["buddies"] = int(mm.group(1).replace(",", ""))
            lines.append(f"이웃(구독) {f['buddies']:,}명")
        mv = re.search(r'오늘\s*([\d,]+)\s*전체\s*([\d,]+)', t)
        if mv:
            f["visits_today"] = int(mv.group(1).replace(",", ""))
            f["visits_total"] = int(mv.group(2).replace(",", ""))
            lines.append(f"누적 방문 {f['visits_total']:,} (오늘 {f['visits_today']})")
    cad_facts, cad_lines = blog_cadence(blog_url)      # RSS 발행주기
    f.update(cad_facts)
    lines += cad_lines
    post_facts, post_lines = blog_recent_post(blog_url)  # 최근 글 1개 본문·사진 실측
    f.update(post_facts)
    lines += post_lines
    if not lines:
        return f, ""
    memo = ("[네이버 블로그 실측 지표(블로그·RSS·최근 글 본문에서 직접 추출) — 화면상 드러나지 않아도 "
            "실제 값이다. 발행 주기·개별 글의 본문 충실도·사진 수·키워드는 아래 수치로 판단하고, "
            "여기 값이 있으면 '느슨/불규칙/화면만으론 확인 어렵다/확인 불가'로 깎지 말 것. "
            "예약·상담 CTA 유무는 최근 글 본문 기준으로 실측했으니 '동선 없음'이면 '확인 필요'가 아니라 "
            "'본문에 전환 동선 없음'으로 단정하고 개선안으로 연결할 것]\n· "
            + "\n· ".join(lines))
    return f, memo


def naverplace_facts(name):
    """네이버 플레이스 구조화 실측(find_place=Apollo 파싱) → (facts, memo).
       화면 비전이 총계를 방문자수로 오독하거나, 폐지된 별점을 약점으로 잡는 것을 방지."""
    from . import naver_place
    try:
        pl = naver_place.find_place(name)
    except Exception:
        return {}, ""
    if not pl:
        return {}, ""
    vr, br, tr = pl.get("visitor_reviews"), pl.get("blog_reviews"), pl.get("total_reviews")
    lines = []
    if tr:
        lines.append(f"리뷰: 방문자 {vr:,} + 블로그 {br:,} = 총 {tr:,} "
                     "(이 분해를 그대로 쓰고 상단 총계를 방문자 리뷰수로 오해하지 말 것)")
    labs = []
    for u in (pl.get("channels") or []):
        lab = ("인스타" if "instagram" in u else "블로그" if "blog.naver" in u
               else "유튜브" if "youtube" in u else "홈페이지")
        if lab not in labs:
            labs.append(lab)
    if labs:
        lines.append("플레이스 등록 공식채널: " + ", ".join(labs) +
                     " (연동 완료). 플레이스는 공식채널을 '링크'로만 노출하므로, 인스타·유튜브·홈페이지는 "
                     "'등록 여부'만 판정하라. 각 채널의 최신성·업로드 빈도·활성도·작동 여부는 플레이스 화면으로 "
                     "알 수 없으니 '확인 필요·활성 여부 미상'으로 약점 삼지 말 것 — 그건 각 채널 자체 분석의 몫이다. "
                     "(예외: 블로그 소식은 아래 최신 발행일로 판단)")
    # 소식 탭 = 블로그 연동. 블로그 RSS 최신 발행일을 실측해 '소식 최신성 확인 필요' 오탐 방지
    blog_url = next((u for u in (pl.get("channels") or []) if "blog.naver" in u), None)
    if blog_url:
        try:
            cad, _ = blog_cadence(blog_url)
        except Exception:
            cad = {}
        if cad.get("latest"):
            import datetime as _dt
            try:
                days = (_dt.date.today() - _dt.date.fromisoformat(cad["latest"])).days
            except Exception:
                days = None
            base = f"소식(블로그 연동) 최신 발행: {cad['latest']} · 주 {cad.get('per_week','?')}회 (RSS 실측)"
            if days is not None and days <= 30:      # 최근 발행 → '확인 필요' 오탐 금지
                base += f" — {days}일 전까지 꾸준히 발행 중이니 '소식 최신성/최신 발행 여부 확인 필요·과거 게시물로 보임'을 약점으로 잡지 말 것"
            elif days is not None:                   # 실제로 뜸함 → 정당한 약점(단, 사실로 단정)
                base += f" — 최근 발행이 {days}일 전으로 뜸함(추정 말고 이 사실로 판단)"
            lines.append(base)
    nbk = pl.get("naver_booking")
    if nbk is not None:
        if nbk.get("active"):
            lines.append("네이버 예약(온라인 예약) 연동됨 — 방문자가 플레이스에서 바로 예약 완료 가능한 "
                         "완결형 전환 동선이 구축됨. 강점으로 보고 '예약 동선/버튼 확인 필요'로 잡지 말 것")
        else:
            lines.append("네이버 예약(온라인 예약) 미연동(예약 URL·업체ID 없음, 코드 확인) — 전화 예약에 의존. "
                         "'확인 필요'가 아니라 '온라인 예약 미도입'을 사실로 단정하고, 도입을 개선안으로 제시할 것 "
                         "(플레이스의 '예약' 편의태그는 예약 접수 표시일 뿐 네이버 예약 연동과 무관)")
    bh = pl.get("business_hours")
    if bh:
        line = f"영업시간(플레이스 등록): {bh}"
        if "24시간" in bh or "24시" in bh:
            line += " — 24시간 영업이 등록돼 있어 네이버가 '영업 중'으로 상시 표시됨. " \
                    "'운영시간 표기 확인 필요/미표기'를 약점으로 잡지 말고, 야간 검색 노출에 유리한 강점으로 볼 것"
        lines.append(line)
    lines.append("네이버는 별점(평점)을 폐지함 — 전 업소 공통이니 '별점 없음/미확인'을 "
                 "약점·개선점으로 잡지 말 것")
    memo = "[네이버 플레이스 실측(코드 파싱) — 화면 숫자 오독 방지]\n· " + "\n· ".join(lines)
    return {"visitor_reviews": vr, "blog_reviews": br, "total_reviews": tr,
            "business_hours": bh}, memo


def _drop_channel_terms(ch, terms, fallback_note="정보·콘텐츠 기반 평판 신뢰"):
    """지정한 무효 용어(예: 폐지된 '별점/평점', 오독 유발 '맛집')를 약점·개선점·하위축 note·
       criteria에서 전부 걷어낸다. 플레이스·카카오맵 등의 오판 방지 보증 필터."""
    def _txt(x):
        return x if isinstance(x, str) else " ".join(
            str(x.get(k, "")) for k in ("title", "body", "text", "note"))
    for key in ("weaknesses", "improvements", "strengths"):
        if isinstance(ch.get(key), list):
            ch[key] = [x for x in ch[key] if not any(t in _txt(x) for t in terms)]
    for field in ("one_liner", "note"):             # 한줄평·비고: 무효용어 문장만 제거
        v = ch.get(field)
        if isinstance(v, str) and any(t in v for t in terms):
            parts = re.split(r'(?<=[.。])\s+|,\s*|—\s*', v)
            kept = [p for p in parts if not any(t in p for t in terms)]
            ch[field] = (", ".join(k for k in kept if k.strip())).strip() or v
    for s in ch.get("subscores", []) or []:
        note = s.get("note") or ""
        if any(t in note for t in terms):
            parts = re.split(r'(?<=[.。])\s+|,\s*|·\s*', note)
            kept = [p for p in parts if not any(t in p for t in terms)]
            s["note"] = (", ".join(k for k in kept if k.strip())).strip() or fallback_note
    if isinstance(ch.get("criteria"), list):
        ch["criteria"] = [c for c in ch["criteria"] if not any(
            t in (c.get("perspective", "") + " " + c.get("question", "")) for t in terms)]
    return ch


def analyze_channel(clinic, ctype, url, slug="auto", extra_memo="", dry_run=False):
    """한 채널: 자동 캡처 → (홈피/블로그/플레이스는 실측 사실 추출) → 비전 분석 → 채널 진단 dict."""
    try:
        path, images = capture_channel(url, ctype, slug=slug)
    except Exception as e:
        return {"type": ctype, "error": f"캡처 실패: {type(e).__name__}",
                "note": "자동 캡처 실패 — 수동 캡처로 폴백 필요", "_source_url": url}
    dom_facts = {}
    if not extra_memo:                              # 하이브리드: 캡처가 못 보는 사실을 코드/데이터로 보충
        try:
            if ctype == "homepage":
                dom_facts, extra_memo = homepage_dom_facts(url)     # CTA·SEO
            elif ctype == "blog":
                dom_facts, extra_memo = blog_dom_facts(url)         # 이웃·방문
            elif ctype == "naverplace":
                dom_facts, extra_memo = naverplace_facts(clinic.get("name", ""))  # 리뷰분해·별점폐지
            elif ctype == "instagram" and len(images) > 1:
                extra_memo = ("[첨부 2장 = ①프로필(그리드) ②릴스 탭. 릴스 유무·활용도는 릴스 탭 "
                              "이미지로 판단하고, 그리드만 보고 '릴스 없음/미미'로 단정하지 말 것. "
                              "릴스가 있으면 조회수 등도 반영하라.]")
        except Exception:
            dom_facts = {}
    ch = ai_draft.draft_channel_from_images(clinic, ctype, images,
                                            extra_memo=extra_memo, dry_run=dry_run)
    ch["_capture"] = path
    ch["_source_url"] = url
    if dom_facts:
        ch["_dom_facts"] = dom_facts
    if ctype == "naverplace":                       # 폐지된 별점·평점 관련 지적 제거(보증)
        ch = _drop_channel_terms(ch, ("별점", "평점"))
    elif ctype == "map":                            # 별점/평점 + '맛집'(주변추천 위젯 오독) 제거
        ch = _drop_channel_terms(ch, ("별점", "평점", "맛집"))
    return ch


def analyze_urls(clinic, url_map, slug=None, dry_run=False):
    """url_map: {ctype: url} → {"channels":[...정상...], "failed":[...캡처실패...]}.

    채널별로 격리해 하나가 실패해도 나머지는 계속 진단한다.
    """
    slug = slug or (clinic.get("slug") or clinic.get("name") or "auto")
    channels, failed = [], []
    for ctype, url in url_map.items():
        if not url:
            continue
        ch = analyze_channel(clinic, ctype, url, slug=slug, dry_run=dry_run)
        if ch.get("error"):
            failed.append({"type": ctype, "url": url, "error": ch["error"]})
        else:
            channels.append(ch)
    return {"channels": channels, "failed": failed}
