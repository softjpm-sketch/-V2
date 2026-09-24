# -*- coding: utf-8 -*-
"""
통계청 SGIS(통계지리정보서비스) OpenAPI3 — 인구·가구 자동 조회.
  상권분석의 반려가구를 '가구수 × 양육률 0.28'(정석)로 계산하기 위해 시군구 가구수를 자동으로 가져온다.

인증(4시간 유효 accessToken):
  GET /OpenAPI3/auth/authentication.json?consumer_key=&consumer_secret=  → result.accessToken
가구수:  /OpenAPI3/stats/household.json?accessToken=&year=&adm_cd=&low_search=0  → household_cnt
인구:    /OpenAPI3/stats/searchpopulation.json?...  → population
행정코드: /OpenAPI3/addr/stage.json?accessToken=[&cd=]  → 시도/시군구 목록({cd, addr_name})

키 발급: https://sgis.kostat.go.kr/developer → 인증정보 신청 → 서비스 ID(consumer_key) + 보안 Key(consumer_secret)
stdlib urllib만 사용(무의존성).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

KEY_FILE = os.path.expanduser("~/.config/petamos/sgis_key")   # JSON: {consumer_key, consumer_secret}
# 통계청/국가데이터처 두 호스트 — 순서대로 시도
_HOSTS = ["https://sgisapi.kostat.go.kr/OpenAPI3", "https://sgisapi.mods.go.kr/OpenAPI3"]
_YEARS = (2023, 2022, 2021, 2020, 2019)   # 총조사 가용 연도(최신부터)
TIMEOUT = 10

_token = {"tok": None, "exp": 0, "host": None}
_adm_cache = {}

_SIDO_SUFFIX = ["특별자치도", "특별자치시", "특별시", "광역시", "자치도", "도", "시"]


def _norm_sido(s):
    s = (s or "").strip()
    for suf in _SIDO_SUFFIX:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


# ── 키 저장/로드(2키) ─────────────────────────────────────────
def has_saved_key():
    return os.path.isfile(KEY_FILE)


def load_saved_key():
    if os.environ.get("SGIS_KEY") and os.environ.get("SGIS_SECRET"):
        return False
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("consumer_key") and d.get("consumer_secret"):
            os.environ["SGIS_KEY"] = d["consumer_key"]
            os.environ["SGIS_SECRET"] = d["consumer_secret"]
            return True
    except Exception:
        pass
    return False


def save_key_to_disk(ck, cs):
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        json.dump({"consumer_key": (ck or "").strip(), "consumer_secret": (cs or "").strip()}, f)
    try:
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass


def forget_saved_key():
    try:
        os.remove(KEY_FILE)
    except FileNotFoundError:
        pass
    os.environ.pop("SGIS_KEY", None)
    os.environ.pop("SGIS_SECRET", None)
    _token.update({"tok": None, "exp": 0, "host": None})


def _creds():
    return os.environ.get("SGIS_KEY"), os.environ.get("SGIS_SECRET")


def available():
    ck, cs = _creds()
    return bool(ck and cs)


def status_text():
    return "SGIS 인구·가구 연동 사용 가능" if available() else "SGIS 서비스ID/보안Key 미설정"


# ── API 호출 ─────────────────────────────────────────────────
def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "PetamosAudit/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _auth():
    """accessToken 발급(+호스트 확정). 반환 (token, host) 또는 (None, None)."""
    ck, cs = _creds()
    if not (ck and cs):
        return (None, None)
    params = urllib.parse.urlencode({"consumer_key": ck, "consumer_secret": cs})
    for host in _HOSTS:
        try:
            r = _fetch(f"{host}/auth/authentication.json?{params}")
        except Exception:
            continue
        if str(r.get("errCd")) == "0":
            res = r.get("result") or {}
            tok = res.get("accessToken")
            if tok:
                _token.update({"tok": tok, "exp": time.time() + 3.5 * 3600, "host": host})
                return (tok, host)
    return (None, None)


def _get_token():
    if _token["tok"] and time.time() < _token["exp"]:
        return _token["tok"], _token["host"]
    return _auth()


def validate_key():
    """서비스ID/보안Key 유효성 확인. 반환 (ok, msg)."""
    ck, cs = _creds()
    if not (ck and cs):
        return (False, "서비스ID/보안Key가 설정되지 않았습니다")
    tok, host = _auth()
    if tok:
        return (True, "확인됨 — SGIS 인구·가구 연동 사용 가능")
    return (False, "인증 실패 — 서비스ID/보안Key를 확인하세요")


def _api(host, tok, path, params):
    p = dict(params); p["accessToken"] = tok
    r = _fetch(f"{host}/{path}?{urllib.parse.urlencode(p)}")
    if str(r.get("errCd")) != "0":
        raise RuntimeError(r.get("errMsg") or f"errCd {r.get('errCd')}")
    return r.get("result") or []


def _resolve_adm(sido, sigungu, tok, host):
    """(시도, 시군구) → 5자리 adm_cd. stage.json으로 해석(캐시)."""
    key = (_norm_sido(sido), (sigungu or "").strip())
    if key in _adm_cache:
        return _adm_cache[key]
    try:
        sidos = _api(host, tok, "addr/stage.json", {})              # 시도 목록
    except Exception:
        return None
    sido_cd = None
    ns = _norm_sido(sido)
    for s in sidos:
        nm = _norm_sido(s.get("addr_name", ""))
        if nm and (nm == ns or nm in ns or ns in nm):
            sido_cd = s.get("cd"); break
    if not sido_cd:
        return None
    try:
        sgg = _api(host, tok, "addr/stage.json", {"cd": sido_cd})   # 시군구 목록
    except Exception:
        return None
    target = (sigungu or "").strip()
    for g in sgg:
        nm = (g.get("addr_name") or "").strip()
        if nm == target or nm in target or target in nm:
            _adm_cache[key] = g.get("cd")
            return g.get("cd")
    return None


def lookup(sido, sigungu):
    """(시도, 시군구) → {households, population, year, adm_cd}. 실패 시 None."""
    if not available():
        return None
    tok, host = _get_token()
    if not tok:
        return None
    adm = _resolve_adm(sido, sigungu, tok, host)
    if not adm:
        return None
    out = {"adm_cd": adm, "sido": sido, "sigungu": sigungu}
    for yr in _YEARS:                       # 가구수(최신 연도부터)
        try:
            res = _api(host, tok, "stats/household.json",
                       {"year": yr, "adm_cd": adm, "low_search": 0})
            if res and res[0].get("household_cnt"):
                out["households"] = int(float(res[0]["household_cnt"]))
                out["year"] = yr
                break
        except Exception:
            continue
    for yr in _YEARS:                       # 인구(참고)
        try:
            res = _api(host, tok, "stats/searchpopulation.json",
                       {"year": yr, "adm_cd": adm, "low_search": 0})
            if res and res[0].get("population"):
                out["population"] = int(float(res[0]["population"]))
                break
        except Exception:
            continue
    return out if out.get("households") else None


# CLI: python3 -m engine.sgis "인천광역시" "남동구"
if __name__ == "__main__":
    import sys
    print("SGIS 상태:", status_text())
    if available():
        print("검증:", validate_key())
        if len(sys.argv) > 2:
            print(json.dumps(lookup(sys.argv[1], sys.argv[2]), ensure_ascii=False))
