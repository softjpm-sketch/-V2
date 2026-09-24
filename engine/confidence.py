# -*- coding: utf-8 -*-
"""신뢰도 플래그 — 자동 생성된 진단(config)이 '스스로 틀림을 알도록' 점검한다.

무인 자동화 전환의 핵심: 고신뢰는 자동 통과, 저신뢰(낮음)만 운영자가 1분 검수.
이번 세션에서 손으로 찾은 오판(디렉토리 오탐·스텁·미수집)을 규칙으로 축적한다.
반환: {"level": 높음/보통/낮음, "low": n, "warn": n, "flags": [{sev, area, msg, url}]}
"""
from . import autopilot   # _SKIP_HOST(디렉토리 blocklist) 재사용


def _is_stub(ch):
    """AI 미연결/분석 실패 시 나오는 예시 스텁 채널."""
    return "[예시]" in (ch.get("one_liner") or "") or (
        ch.get("score") == 60 and not ch.get("subscores"))


def assess(cfg):
    flags = []

    def add(sev, area, msg, url=None):
        flags.append({"sev": sev, "area": area, "msg": msg, "url": url})

    mk = cfg.get("marketing", {}) or {}
    chs = mk.get("channels", []) or []
    ctypes = {c.get("type") for c in chs}

    # ── 마케팅(우리 병원 채널) ──
    if not chs:
        add("low", "마케팅", "우리 병원 채널이 하나도 분석되지 않음(AI/캡처 실패 가능)")
    for c in chs:
        t = c.get("type")
        if _is_stub(c):
            add("low", "마케팅", f"‘{t}’ 채널이 예시(스텁) — AI 미연결/분석 실패", c.get("_source_url"))
        if t == "homepage":
            u = (c.get("_source_url") or "").lower()
            if u and any(h in u for h in autopilot._SKIP_HOST):
                add("low", "마케팅", "홈페이지가 디렉토리/집계 사이트로 잡힘(오탐 의심)", c.get("_source_url"))
            elif not c.get("_dom_facts"):
                add("warn", "마케팅", "홈페이지 코드(DOM) 추출 실패 — CTA·SEO 미확인", c.get("_source_url"))
    for must, lab in (("homepage", "홈페이지"), ("blog", "블로그"),
                      ("instagram", "인스타"), ("naverplace", "플레이스")):
        if must not in ctypes:
            add("warn", "마케팅", f"{lab} 채널 미발견/미분석")

    # ── 리뷰 ──
    rv = cfg.get("review", {}) or {}
    if not rv.get("channels"):
        add("warn", "리뷰", "리뷰 데이터 없음/미수집")

    # ── 경쟁 ──
    comp = cfg.get("competition", {}) or {}
    rms = comp.get("rival_marketing", []) or []
    clinics = comp.get("clinics", []) or []
    if not clinics:
        add("low", "경쟁", "경쟁 병원 목록이 비어 있음(카카오 수집 실패)")
    if not rms:
        add("warn", "경쟁", "경쟁사 채널(rival_marketing) 미수집")
    elif all(r.get("homepage") == "없음" and r.get("blog") == "없음"
             and r.get("instagram") == "없음" for r in rms):
        add("warn", "경쟁", "추천 경쟁사 채널이 전부 ‘없음’ — 수집 실패 가능")
    if clinics and not any(c.get("review_count") for c in clinics):
        add("warn", "경쟁", "경쟁사 리뷰수 미수집")

    # ── 상권 ──
    ta = cfg.get("trade_area", {}) or {}
    warn = (ta.get("_ingest", {}) or {}).get("warn")
    if not ta:
        add("low", "상권", "상권 데이터 없음")
    elif warn:
        add("warn", "상권", str(warn))

    lows = sum(1 for f in flags if f["sev"] == "low")
    warns = sum(1 for f in flags if f["sev"] == "warn")
    level = "낮음" if lows else ("보통" if warns >= 2 else "높음")
    return {"level": level, "low": lows, "warn": warns, "flags": flags}
