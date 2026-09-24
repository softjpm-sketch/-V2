# -*- coding: utf-8 -*-
"""
카카오 로컬 API — 경쟁 자동수집(요청2) 기반.
  - 주소 → 좌표 지오코딩
  - 반경 내 '동물병원' 키워드 검색(거리순, 페이지네이션)
  - REST API 키 영구저장(Anthropic 키와 동일 방식) + 유효성 검증

키 발급: https://developers.kakao.com → 애플리케이션 → REST API 키
인증 헤더: Authorization: KakaoAK {REST_API_KEY}
stdlib urllib만 사용(무의존성).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

KEY_FILE = os.path.expanduser("~/.config/petamos/kakao_key")
_BASE = "https://dapi.kakao.com/v2/local"
TIMEOUT = 10
_SEOUL = (37.5665, 126.9780)  # 검증용 기준 좌표(서울시청)


# ── 키 저장/로드(ai_draft와 동일 패턴) ─────────────────────────
def has_saved_key():
    return os.path.isfile(KEY_FILE)


def load_saved_key():
    if os.environ.get("KAKAO_REST_KEY"):
        return False
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            os.environ["KAKAO_REST_KEY"] = key
            return True
    except Exception:
        pass
    return False


def save_key_to_disk(key):
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write((key or "").strip())
    try:
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass


def forget_saved_key():
    try:
        os.remove(KEY_FILE)
    except FileNotFoundError:
        pass
    os.environ.pop("KAKAO_REST_KEY", None)


def _key():
    return os.environ.get("KAKAO_REST_KEY")


def available():
    return bool(_key())


def status_text():
    return "카카오 자동수집 사용 가능" if available() else "카카오 REST 키 미설정"


# ── API 호출 ─────────────────────────────────────────────────
def _get(path, params):
    key = _key()
    if not key:
        raise RuntimeError("카카오 키 없음")
    url = f"{_BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {key}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def validate_key():
    """무료 호출로 키 유효성 확인. 반환 (ok, msg)."""
    if not _key():
        return (False, "키가 설정되지 않았습니다")
    try:
        _get("search/keyword.json",
             {"query": "동물병원", "x": _SEOUL[1], "y": _SEOUL[0], "radius": 500, "size": 1})
        return (True, "키 확인됨 — 카카오 자동수집 사용 가능")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return (False, "키가 유효하지 않습니다(인증 실패). REST API 키인지 확인하세요")
        return (False, f"카카오 응답 오류 HTTP {e.code}")
    except Exception as e:
        return (False, f"검증 실패: {type(e).__name__}")


def geocode(address):
    """주소 → (lat, lng). 실패 시 None. 주소검색 실패하면 키워드검색으로 폴백."""
    address = (address or "").strip()
    if not address:
        return None
    try:
        r = _get("search/address.json", {"query": address})
        docs = r.get("documents", [])
        if docs:
            return (float(docs[0]["y"]), float(docs[0]["x"]))
    except Exception:
        pass
    try:  # 지번/도로명 검색 실패 시 키워드로 좌표 획득
        r = _get("search/keyword.json", {"query": address, "size": 1})
        docs = r.get("documents", [])
        if docs:
            return (float(docs[0]["y"]), float(docs[0]["x"]))
    except Exception:
        pass
    return None


def region(address):
    """주소 → (시도, 시군구). 실패 시 (None, None). SGIS·등록수 조회용."""
    address = (address or "").strip()
    if not address:
        return (None, None)
    try:
        r = _get("search/address.json", {"query": address})
        docs = r.get("documents", [])
        if docs:
            a = docs[0].get("address") or docs[0].get("road_address") or {}
            s1, s2 = a.get("region_1depth_name"), a.get("region_2depth_name")
            if s1:
                return (s1, (s2 or "").split()[-1] if s2 else s2)  # '성남시 분당구'→'분당구'
    except Exception:
        pass
    try:  # 키워드 폴백: address_name 문자열의 앞 2토큰
        r = _get("search/keyword.json", {"query": address, "size": 1})
        docs = r.get("documents", [])
        if docs:
            toks = (docs[0].get("address_name", "") or "").split()
            if len(toks) >= 2:
                return (toks[0], toks[1])
    except Exception:
        pass
    return (None, None)


def region_clinic_count(lat, lng, radius_m):
    """반경 내 '동물병원' 총 개수(카카오 meta.total_count · 45건 페이징과 무관하게 실제 총계)."""
    try:
        r = _get("search/keyword.json", {
            "query": "동물병원", "x": lng, "y": lat,
            "radius": min(int(radius_m), 20000), "size": 1})
        return int(r.get("meta", {}).get("total_count", 0))
    except Exception:
        return 0


def dong_code(address):
    """주소 → (행정동코드 8자리, 행정동명). 소상공인 빅데이터 dongCd용. 실패 시 (None, None)."""
    coord = geocode(address)
    if not coord:
        return (None, None)
    try:
        r = _get("geo/coord2regioncode.json", {"x": coord[1], "y": coord[0]})
        for d in r.get("documents", []):
            if d.get("region_type") == "H":          # 행정동
                code = d.get("code") or ""
                return (code[:8] if code else None, d.get("region_3depth_name"))
    except Exception:
        pass
    return (None, None)


def nearest_station(lat, lng, radius_m=1500):
    """가장 가까운 지하철역까지 거리(m)와 이름. 없으면 (None, None). (카카오 카테고리 SW8)"""
    try:
        r = _get("search/category.json", {
            "category_group_code": "SW8", "x": lng, "y": lat,
            "radius": min(int(radius_m), 20000), "sort": "distance", "size": 1})
        docs = r.get("documents", [])
        if docs:
            return (int(docs[0].get("distance") or 0), docs[0].get("place_name", ""))
    except Exception:
        pass
    return (None, None)


def category_count(code, lat, lng, radius_m=500):
    """반경 내 특정 카테고리(FD6 음식점·CE7 카페·CS2 편의점 등) 총 개수."""
    try:
        r = _get("search/category.json", {
            "category_group_code": code, "x": lng, "y": lat,
            "radius": min(int(radius_m), 20000), "size": 1})
        return int(r.get("meta", {}).get("total_count", 0))
    except Exception:
        return 0


def apartment_count(lat, lng, radius_m=500):
    """반경 내 '아파트' 총 개수(밀집 판정용). meta.total_count."""
    try:
        r = _get("search/keyword.json", {
            "query": "아파트", "x": lng, "y": lat,
            "radius": min(int(radius_m), 20000), "size": 1})
        return int(r.get("meta", {}).get("total_count", 0))
    except Exception:
        return 0


def find_place_url(name, address=""):
    """병원명(+주소 좌표 바이어스)으로 카카오 장소검색 → 대표 카카오맵 place_url. 실패 None."""
    if not available() or not name:
        return None
    params = {"query": name, "size": 5}
    coord = geocode(address) if address else None
    if coord:
        params.update({"x": coord[1], "y": coord[0], "radius": 3000, "sort": "distance"})
    try:
        docs = _get("search/keyword.json", params).get("documents", [])
    except Exception:
        return None
    core = name.replace(" ", "")[:3]
    for d in docs:                                  # 이름 앞부분이 일치하는 장소 우선
        if core and core in d.get("place_name", "").replace(" ", ""):
            return d.get("place_url") or None
    return (docs[0].get("place_url") if docs else None) or None


def find_place_nap(name, address=""):
    """병원명(+주소 좌표 바이어스)으로 카카오 장소검색 → NAP(상호·주소·전화).
       반환 {name, address, phone, place_url} 또는 None. 카카오 로컬 API는 phone을 제공."""
    if not available() or not name:
        return None
    params = {"query": name, "size": 5}
    coord = geocode(address) if address else None
    if coord:
        params.update({"x": coord[1], "y": coord[0], "radius": 3000, "sort": "distance"})
    try:
        docs = _get("search/keyword.json", params).get("documents", [])
    except Exception:
        return None
    if not docs:
        return None
    core = name.replace(" ", "")[:3]
    d = next((x for x in docs
              if core and core in x.get("place_name", "").replace(" ", "")), docs[0])
    return {
        "name": d.get("place_name", "") or None,
        "address": d.get("road_address_name", "") or d.get("address_name", "") or None,
        "phone": (d.get("phone", "") or "").strip() or None,
        "place_url": d.get("place_url") or None,
    }


def search_animal_hospitals(lat, lng, radius_m):
    """반경 내 '동물병원' 검색(거리순). 반환 (clinics[], total_count).
       카카오 키워드검색은 최대 45건(15×3p) 조회 가능."""
    radius = min(int(radius_m), 20000)   # 카카오 최대 20km
    clinics, total = [], 0
    for page in range(1, 4):             # 최대 3페이지 = 45건
        try:
            r = _get("search/keyword.json", {
                "query": "동물병원", "x": lng, "y": lat, "radius": radius,
                "sort": "distance", "page": page, "size": 15})
        except Exception:
            break
        total = r.get("meta", {}).get("total_count", total)
        for d in r.get("documents", []):
            try:
                dist = int(d.get("distance") or 0)
            except ValueError:
                dist = 0
            clinics.append({
                "name": d.get("place_name", ""),
                "category": d.get("category_name", ""),
                "distance_m": dist,
                "road": d.get("road_address_name", "") or d.get("address_name", ""),
                "url": d.get("place_url", ""),
            })
        if r.get("meta", {}).get("is_end"):
            break
    return clinics, total


def collect_competition(address, radius_m, self_name=""):
    """주소 → 좌표 → 반경 내 동물병원 목록(analyze_competition 입력 형식).
       반환 dict: {ok, clinics, total, coord, capped, error}."""
    coord = geocode(address)
    if not coord:
        return {"ok": False, "error": "주소 지오코딩 실패 — 주소를 확인하세요", "clinics": []}
    clinics, total = search_animal_hospitals(coord[0], coord[1], radius_m)
    return {
        "ok": True, "clinics": clinics, "total": total,
        "coord": coord, "radius_m": min(int(radius_m), 20000),
        "capped": total > len(clinics),   # 45건 초과라 일부만 수집
    }


# CLI: python3 -m engine.kakao "<주소>" [반경m]
if __name__ == "__main__":
    import sys
    print("키 상태:", status_text())
    if len(sys.argv) > 1 and available():
        rad = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
        res = collect_competition(sys.argv[1], rad)
        print(json.dumps(res, ensure_ascii=False, indent=2)[:1500])
