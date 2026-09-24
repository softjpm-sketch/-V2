# -*- coding: utf-8 -*-
"""엔티티 구독 대행 파이프라인 — 최신화 → 심기 → 검증까지의 생애주기 오케스트레이션.

BM: 5만원 진단엔 코드가 없고(결핍만), 구독 전환 시 우리가 대행한다.
흐름(각 단계가 data/entity/<slug>.json 게이트 저장소에 상태로 남음):

  0 기준선(baseline)  심기 전 AI 검색에 안 나온다는 증거(ai_search)
  1 최신화(refresh)   최신 데이터로 schema.org 코드 재생성(입력 바뀌면 hash 변경)
  2 심기(install)     완성 코드를 홈피에 심고(우리 대행) 심은 버전 기록
  3 대기(reindex)     재크롤 대기(며칠~몇 주)
  4 사후검증(verify)  다시 AI 검색 → baseline 대비 delta(노출·인용 상승) 증명

네트워크(ai_search=Claude 웹검색, naver/kakao)는 각 단계에서 호출. 테스트/재실행을 위해
결과 주입(_search_result / _code)도 지원한다.
"""
from __future__ import annotations

import json
import os
import time

from . import schema_org

STORE_DIR = schema_org.STORE_DIR


def _path(slug):
    return os.path.join(STORE_DIR, f"{slug}.json")


def _load(slug):
    try:
        with open(_path(slug), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save(slug, rec):
    os.makedirs(STORE_DIR, exist_ok=True)
    rec["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(_path(slug), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(_path(slug), 0o600)     # 구독 산출물 — 소유자만
    except Exception:
        pass
    return _path(slug)


def _blank(slug, clinic):
    return {"slug": slug, "clinic_name": clinic.get("name", ""),
            "clinic": {"name": clinic.get("name", ""), "address": clinic.get("address", "")},
            "known_urls": {},
            "subscription": {"active": False, "since": None},
            "baseline": None, "code": None,
            "install": {"status": "pending", "installed_at": None, "installed_hash": None},
            "post_verify": None}


def _clinic_of(rec, clinic=None):
    if clinic:
        return clinic
    c = rec.get("clinic") or {}
    return {"name": c.get("name") or rec.get("clinic_name", ""), "address": c.get("address", "")}


def _in_answer_count(res):
    return sum(1 for r in (res or []) if r.get("in_answer"))


# ────────────────────────── 단계별 ──────────────────────────
def measure(clinic, cfg=None, known_urls=None, engine=None, _search_result=None):
    """AI 검색 노출 측정(ai_search.run). _search_result 주입 시 그걸 사용(테스트/재실행)."""
    if _search_result is not None:
        return _search_result
    from . import ai_search
    return ai_search.run(clinic, cfg, known_urls=known_urls, engine=engine)


def start_subscription(slug, clinic, cfg=None, known_urls=None,
                       measure_baseline=True, _search_result=None, _code=None):
    """구독 시작 = 기준선 측정(심기 전 증거) + 최신 코드 생성·보관. 반환 상태 rec."""
    rec = _load(slug) or _blank(slug, clinic)
    rec["clinic"] = {"name": clinic.get("name", ""), "address": clinic.get("address", "")}
    if known_urls:
        rec["known_urls"] = known_urls
    rec["subscription"] = {"active": True, "since": time.strftime("%Y-%m-%d %H:%M:%S")}
    if measure_baseline and not rec.get("baseline"):
        sc = measure(clinic, cfg, known_urls, _search_result=_search_result)
        rec["baseline"] = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "engine": sc.get("engine"), "summary": sc.get("summary"),
                           "results": sc.get("results")}
    rec = _apply_code(rec, clinic, cfg, known_urls, _code=_code)
    _save(slug, rec)
    return rec


def _apply_code(rec, clinic, cfg, known_urls, _code=None):
    """최신 데이터로 코드 생성 → rec['code'] 갱신(입력 바뀌면 content_hash 변경)."""
    res = _code if _code is not None else schema_org.generate(
        clinic, cfg, known_urls=known_urls, enrich=(_code is None))
    import hashlib
    digest = hashlib.sha256(json.dumps(res.get("jsonld", {}), ensure_ascii=False,
                                       sort_keys=True).encode("utf-8")).hexdigest()[:12]
    rec["code"] = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "content_hash": digest, "jsonld": res.get("jsonld"),
                   "script": res.get("script"), "sources": res.get("sources"),
                   "missing": res.get("missing")}
    return rec


def refresh(slug, clinic, cfg=None, known_urls=None, _code=None):
    """구독 중 최신화 — 코드 재생성 후 이전 hash와 비교. 반환 {changed, old_hash, new_hash, rec}."""
    rec = _load(slug)
    if not rec:
        return {"error": "구독 레코드 없음(먼저 start_subscription)"}
    clinic = _clinic_of(rec, clinic)
    known_urls = known_urls or rec.get("known_urls") or {}
    old = (rec.get("code") or {}).get("content_hash")
    rec = _apply_code(rec, clinic, cfg, known_urls, _code=_code)
    new = rec["code"]["content_hash"]
    changed = old != new
    # 코드가 바뀌었는데 이미 심어둔 상태면 '재심기 필요'로 표시
    if changed and rec["install"]["status"] == "installed":
        rec["install"]["status"] = "stale"      # 심은 버전이 최신과 다름 → 재심기 대상
    _save(slug, rec)
    return {"changed": changed, "old_hash": old, "new_hash": new, "rec": rec}


def mark_installed(slug):
    """심기 완료 기록 — 현재 code 버전을 '심은 버전'으로 확정."""
    rec = _load(slug)
    if not rec or not rec.get("code"):
        return {"error": "생성된 코드 없음"}
    rec["install"] = {"status": "installed",
                      "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                      "installed_hash": rec["code"]["content_hash"]}
    _save(slug, rec)
    return rec


def verify(slug, clinic, cfg=None, known_urls=None, engine=None, _search_result=None):
    """사후 검증 — 심은 뒤 다시 AI 검색 측정 → baseline 대비 delta 저장."""
    rec = _load(slug)
    if not rec:
        return {"error": "구독 레코드 없음"}
    if rec["install"]["status"] not in ("installed", "stale"):
        return {"error": "아직 심기 전(mark_installed 필요) — 사후검증은 심은 뒤"}
    clinic = _clinic_of(rec, clinic)
    known_urls = known_urls or rec.get("known_urls") or {}
    sc = measure(clinic, cfg, known_urls, engine=engine, _search_result=_search_result)
    post = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "engine": sc.get("engine"), "summary": sc.get("summary"),
            "results": sc.get("results")}
    base = rec.get("baseline") or {}
    b_sum, p_sum = base.get("summary", {}) or {}, post["summary"] or {}
    post["delta"] = {
        "presence_rate": [b_sum.get("presence_rate"), p_sum.get("presence_rate")],
        "in_answer": [_in_answer_count(base.get("results")), _in_answer_count(post["results"])],
        "attribution": [list((b_sum.get("attribution") or {}).keys()),
                        list((p_sum.get("attribution") or {}).keys())],
    }
    rec["post_verify"] = post
    _save(slug, rec)
    return rec


def status(slug):
    """생애주기 요약 + 다음 할 일."""
    rec = _load(slug)
    if not rec:
        return {"slug": slug, "state": "none", "next": "start_subscription"}
    if not rec["subscription"]["active"]:
        nxt = "start_subscription"
    elif not rec.get("code"):
        nxt = "refresh(코드 생성)"
    elif rec["install"]["status"] in ("pending", "stale"):
        nxt = "심기 → mark_installed"
    elif not rec.get("post_verify"):
        nxt = "재크롤 대기 후 verify"
    else:
        nxt = "완료 — 주기적 refresh/verify 반복"
    return {"slug": slug, "clinic": rec.get("clinic_name"),
            "subscribed": rec["subscription"]["active"],
            "has_code": bool(rec.get("code")),
            "code_hash": (rec.get("code") or {}).get("content_hash"),
            "install": rec["install"]["status"],
            "baseline": bool(rec.get("baseline")),
            "post_verify": bool(rec.get("post_verify")),
            "next": nxt}
