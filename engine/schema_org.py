# -*- coding: utf-8 -*-
"""schema.org JSON-LD 생성기 — AEO·GEO '엔티티 심기'의 산출물.

AI·검색엔진이 병원을 '글자'가 아니라 '실체(엔티티)'로 인식하도록, 우리가 이미
실측한 데이터(NAP·영업시간·EMR 강점 진료·공식 채널)를 schema.org 구조화데이터로
코드 선언한다. 홈페이지 <head>에 붙이는 <script type="application/ld+json"> 산출.

핵심 매핑:
    @type          = ["VeterinaryCare","LocalBusiness"]  (동물병원 실체)
    name/url/telephone/address = NAP (엔티티 정체성)
    openingHoursSpecification  = 영업시간(24시간이면 야간 검색 노출↑)
    knowsAbout     = EMR 강점 진료 (이 병원이 '잘 아는' 분야 → AI 추천 근거)
    sameAs         = 공식 채널(플레이스·블로그·인스타·유튜브) → 흩어진 채널을 같은 실체로 연결
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# 게이트 저장소 — 고객 리포트 폴더(reports/)가 아닌 서버측 별도 폴더.
# 완성 코드는 구독 산출물이라 리포트에 딸려가면 안 됨(BM: 코드는 상품이지 사은품이 아님).
_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE_DIR = os.path.join(_PROJ, "data", "entity")


def _clean_phone(p):
    if not p:
        return None
    s = str(p).strip()
    return s or None


def _hours_spec(business_hours):
    """'24시간 진료 · 연중무휴' 등 → openingHoursSpecification. 24시간이면 전요일 00:00-23:59."""
    if not business_hours:
        return None
    bh = str(business_hours)
    if "24시간" in bh or "24시" in bh:
        return [{
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": _DAYS,
            "opens": "00:00", "closes": "23:59",
        }]
    return None                                  # 그 외 영업시간은 원장 확인 필요(추정 금지)


def build_jsonld(name, homepage=None, phone=None, address=None,
                 business_hours=None, specialties=None, sameas=None, geo=None):
    """실측 값으로 schema.org JSON-LD(dict) 생성. 값 없는 필드는 넣지 않는다(추정 금지)."""
    data = {
        "@context": "https://schema.org",
        "@type": ["VeterinaryCare", "LocalBusiness"],
        "name": name,
    }
    if homepage:
        data["url"] = homepage
    ph = _clean_phone(phone)
    if ph:
        data["telephone"] = ph
    if address:
        data["address"] = {"@type": "PostalAddress",
                           "streetAddress": address, "addressCountry": "KR"}
    if geo and geo.get("lat") and geo.get("lng"):
        data["geo"] = {"@type": "GeoCoordinates",
                       "latitude": geo["lat"], "longitude": geo["lng"]}
    hs = _hours_spec(business_hours)
    if hs:
        data["openingHoursSpecification"] = hs
    specs = [s for s in (specialties or []) if s]
    if specs:
        data["knowsAbout"] = specs               # EMR 강점 진료 = 이 병원이 잘 아는 분야
    sa = [u for u in (sameas or []) if u]
    if sa:
        data["sameAs"] = sa
    return data


def to_script(jsonld):
    """JSON-LD dict → 홈페이지 <head>에 붙이는 <script> 블록 문자열."""
    body = json.dumps(jsonld, ensure_ascii=False, indent=2)
    return '<script type="application/ld+json">\n' + body + '\n</script>'


def _specialties_from_cfg(cfg):
    """cfg의 EMR AEO 타겟(강점 진료) → knowsAbout 목록."""
    try:
        tg = (cfg.get("emr", {}).get("roadmap", {}).get("aeo", {}) or {}).get("targets", [])
        return [t.get("keyword") for t in tg if t.get("keyword")]
    except Exception:
        return []


def generate(clinic, cfg=None, known_urls=None, specialties=None, enrich=False):
    """병원+수집데이터로 JSON-LD 자동 조립 → {jsonld, script, sources, missing}.
       enrich=True면 네이버플레이스·카카오에서 전화·주소·영업시간·좌표·채널을 보강(네트워크)."""
    cfg = cfg or {}
    name = clinic.get("name", "")
    address = clinic.get("address")
    phone = None
    business_hours = None
    geo = None
    known_urls = dict(known_urls or {})
    specs = specialties or _specialties_from_cfg(cfg)
    sources = []

    if enrich:
        try:
            from . import naver_place, kakao, autopilot
            pl = naver_place.find_place((name + " " + (address or "")).strip()) or \
                naver_place.find_place(name)
            if pl:
                sources.append("naver_place")
                phone = pl.get("phone") or phone
                address = pl.get("address") or address
                business_hours = pl.get("business_hours") or business_hours
                for u in (pl.get("channels") or []):
                    lab = ("instagram" if "instagram" in u else "blog" if "blog.naver" in u
                           else "youtube" if "youtu" in u else "homepage")
                    known_urls.setdefault(lab, u)
                if pl.get("place_url"):
                    known_urls.setdefault("naverplace", pl["place_url"])
            kp = kakao.find_place_nap(name, address or "")   # 실전화(안심번호 아닌) 보강
            if kp:
                sources.append("kakao")
                if kp.get("phone") and not (phone and not phone.startswith("0507")):
                    phone = kp.get("phone") or phone
                if kp.get("place_url"):
                    known_urls.setdefault("map", kp["place_url"])
            try:
                co = kakao.geocode(address or "")
                if co:
                    geo = {"lat": co[0], "lng": co[1]}
            except Exception:
                pass
        except Exception:
            pass

    homepage = known_urls.get("homepage")
    sameas = [known_urls[k] for k in ("naverplace", "blog", "instagram", "youtube", "map")
              if known_urls.get(k)]
    jsonld = build_jsonld(name, homepage=homepage, phone=phone, address=address,
                          business_hours=business_hours, specialties=specs,
                          sameas=sameas, geo=geo)
    missing = [f for f in ("url", "telephone", "address", "openingHoursSpecification",
                           "knowsAbout", "sameAs") if f not in jsonld]
    return {"jsonld": jsonld, "script": to_script(jsonld),
            "sources": sources, "missing": missing}


# ────────────────────────── 게이트 저장소 (구독 산출물) ──────────────────────────
def preview(jsonld, keep=("@type", "name")):
    """리포트용 '가려진 미리보기' — 실체가치(NAP·강점·채널)는 감추고 구조만 보여준다.
       고객이 '이런 코드가 필요하다'는 건 알되, 붙여넣기용 완성본은 못 가져가게."""
    masked = {"@context": "https://schema.org"}
    for k, v in jsonld.items():
        if k in keep:
            masked[k] = v
        elif k == "knowsAbout":
            masked[k] = ["●●● (구독 시 제공)"]
        elif k in ("telephone", "url", "address", "sameAs", "geo", "openingHoursSpecification"):
            masked[k] = "🔒 구독 제공"
    return masked


def save_entity_code(slug, result, inputs=None):
    """생성된 엔티티 코드를 서버측 게이트 저장소에 보관(버전=타임스탬프, 입력 스냅샷 동봉).
       리포트 폴더가 아니라 data/entity/<slug>.json 에만 저장한다."""
    os.makedirs(STORE_DIR, exist_ok=True)
    jsonld = result.get("jsonld", {})
    digest = hashlib.sha256(
        json.dumps(jsonld, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    rec = {
        "slug": slug,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "content_hash": digest,           # 입력(NAP·강점 등) 바뀌면 해시가 바뀜 → 재생성 판단
        "jsonld": jsonld,
        "script": result.get("script"),
        "sources": result.get("sources"),
        "missing": result.get("missing"),
        "inputs": inputs or {},
    }
    path = os.path.join(STORE_DIR, f"{slug}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)             # 소유자만 읽기(구독 산출물 보호)
    except Exception:
        pass
    return path


def load_entity_code(slug):
    """게이트 저장소에서 엔티티 코드 로드(구독 확인 후 제공용). 없으면 None."""
    path = os.path.join(STORE_DIR, f"{slug}.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
