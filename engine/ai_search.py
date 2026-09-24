# -*- coding: utf-8 -*-
"""AI 검색 노출 검증 러너 — AEO·GEO 뒷단(작동 검증).

AI 앤서/생성 엔진에 "{지역} OO 잘하는 동물병원 추천" 류를 직접 질의해,
답변·인용에 우리 병원이 나오는지 / 어떤 채널이 인용됐는지(귀속)를 측정한다.

1단계 = Perplexity Sonar API(공식 API, 인용 배열 반환 → 파싱 깔끔, 계정 차단 위험 없음).
이후 ChatGPT(OpenAI)·Claude(Anthropic) API를 같은 인터페이스로 확장.
구글 AI Overviews·네이버 큐:는 API가 없어 반자동 캡처(별도).

키는 웹 화면(/settings)에서 입력 — 채팅으로 받지 않는다(kakao 패턴과 동일).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

KEY_FILE = os.path.expanduser("~/.config/petamos/perplexity_key")
_API_URL = "https://api.perplexity.ai/chat/completions"
_MODEL = "sonar"


# ────────────────────────── 키 관리(kakao 패턴 동일) ──────────────────────────
def has_saved_key():
    return os.path.isfile(KEY_FILE)


def load_saved_key():
    if os.environ.get("PERPLEXITY_API_KEY"):
        return True
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            os.environ["PERPLEXITY_API_KEY"] = key
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
    if (key or "").strip():
        os.environ["PERPLEXITY_API_KEY"] = key.strip()


def forget_saved_key():
    try:
        os.remove(KEY_FILE)
    except FileNotFoundError:
        pass
    os.environ.pop("PERPLEXITY_API_KEY", None)


def available():
    return bool(os.environ.get("PERPLEXITY_API_KEY")) or has_saved_key()


def status_text():
    return "Perplexity 검증 사용 가능" if available() else "Perplexity API 키 미설정(/settings에서 입력)"


# ────────────────────────── 질의 세트 생성 ──────────────────────────
def _sigungu(address):
    """행안부/일반 주소에서 시군구 토큰 추출(서울특별시 강북구 … → 강북구)."""
    toks = str(address or "").replace(",", " ").split()
    for t in toks[1:]:
        if t.endswith(("시", "군", "구")):
            return t
    return toks[0] if toks else ""


def _emr_targets(cfg):
    """cfg에서 EMR 강점 진료 키워드(AI 추천 타겟) 추출 → 질의 소재."""
    try:
        tg = (cfg.get("emr", {}).get("roadmap", {}).get("aeo", {}) or {}).get("targets", [])
        return [t.get("keyword") for t in tg if t.get("keyword")]
    except Exception:
        return []


def build_queries(clinic, cfg=None, max_strength=3):
    """병원·지역·EMR 강점으로 타겟 질문 목록 생성.
       반환 [{"q", "kind"(base/strength), "basis"}]."""
    cfg = cfg or {}
    region = _sigungu(clinic.get("address", "")) or clinic.get("address", "")
    name = clinic.get("name", "")
    is24 = "24시" in name or "24시" in json.dumps(cfg, ensure_ascii=False)
    out = []
    if region:
        if is24:
            out.append({"q": f"{region} 24시 동물병원 추천", "kind": "base", "basis": "24시간 야간 검색"})
        out.append({"q": f"{region} 동물병원 추천", "kind": "base", "basis": "지역 일반 추천"})
    for kw in _emr_targets(cfg)[:max_strength]:      # EMR 강점 → 강점질의(엔티티 타겟)
        if region:
            out.append({"q": f"{region} {kw} 잘하는 동물병원", "kind": "strength",
                        "basis": f"EMR 강점: {kw}"})
    return out


# ────────────────────────── 인용 파서(노출·귀속 판정) ──────────────────────────
def _norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def _host(url):
    m = re.search(r"https?://([^/]+)", str(url or ""))
    return (m.group(1).lower().replace("www.", "") if m else "").strip()


def find_clinic(clinic, result, known_urls=None):
    """AI 답변/인용에 우리 병원이 나오는지 + 어떤 채널이 인용됐는지 판정.
       result = {"answer": str, "citations": [url,...]}.
       known_urls = {"homepage":..,"blog":..,"instagram":..,"naverplace":..,"map":..}."""
    known_urls = known_urls or {}
    name_n = _norm(clinic.get("name"))
    ans = result.get("answer") or ""
    cites = result.get("citations") or []

    in_answer = bool(name_n) and name_n in _norm(ans)
    # 인용 URL이 우리 채널과 일치하는지(귀속)
    known_hosts = {ch: _host(u) for ch, u in known_urls.items() if u}
    cited = []
    for i, u in enumerate(cites):
        h = _host(u)
        for ch, kh in known_hosts.items():
            if kh and (kh == h or kh in h or h in kh):
                cited.append({"channel": ch, "url": u, "rank": i + 1})
    # 플레이스/블로그 등은 도메인이 공용(place.naver.com)이라 이름 포함도 보조 확인
    for i, u in enumerate(cites):
        if name_n and name_n in _norm(u) and not any(c["url"] == u for c in cited):
            cited.append({"channel": "기타", "url": u, "rank": i + 1})

    present = in_answer or bool(cited)
    return {
        "present": present,
        "in_answer": in_answer,
        "cited_sources": cited,
        "answer_excerpt": ans[:300],
    }


# ────────────────────────── 엔진 러너 ──────────────────────────
def ask_perplexity(query, timeout=40):
    """Perplexity Sonar에 질의 → {"answer", "citations"[url]}. 키 없으면 예외."""
    load_saved_key()
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        raise RuntimeError("PERPLEXITY_API_KEY 미설정")
    body = json.dumps({
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": "간결히 한국어로 답하고, 지역 동물병원을 실제 출처와 함께 추천하라."},
            {"role": "user", "content": query},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(_API_URL, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    answer = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    cites = data.get("citations") or [
        s.get("url") for s in (data.get("search_results") or []) if s.get("url")]
    return {"answer": answer, "citations": cites}


def ask_claude(query, timeout=60):
    """Claude(기존 Anthropic 키) + 웹 검색 도구로 질의 → {"answer","citations"[url]}.
       새 키·결제 불필요(AI 초안과 같은 키 재사용). Claude 자체가 GEO 타겟 엔진."""
    from . import ai_draft
    ai_draft.load_saved_key()
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=ai_draft.MODEL,
        max_tokens=1024,
        system="간결히 한국어로 답하고, 지역 동물병원을 실제 출처(웹 검색)와 함께 추천하라.",
        messages=[{"role": "user", "content": query}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
    )
    answer, cites = [], []
    for block in resp.content:
        btype = getattr(block, "type", "")
        if btype == "text":
            answer.append(getattr(block, "text", "") or "")
            for c in (getattr(block, "citations", None) or []):     # 텍스트 인용 URL
                u = getattr(c, "url", None)
                if u:
                    cites.append(u)
        elif btype == "web_search_tool_result":                     # 검색 결과 URL
            for item in (getattr(block, "content", None) or []):
                u = getattr(item, "url", None)
                if u:
                    cites.append(u)
    seen, uniq = set(), []
    for u in cites:
        if u not in seen:
            seen.add(u); uniq.append(u)
    return {"answer": "".join(answer), "citations": uniq}


_ENGINES = {"perplexity": ask_perplexity, "claude": ask_claude}


def default_engine():
    """사용 가능한 엔진 자동 선택: Perplexity 키 있으면 그것, 없으면 기존 Claude 키."""
    if available():
        return "perplexity"
    try:
        from . import ai_draft
        if ai_draft.load_saved_key() or ai_draft.has_saved_key():
            return "claude"
    except Exception:
        pass
    return "perplexity"


def run(clinic, cfg=None, known_urls=None, engine=None, queries=None):
    """타겟 질의를 엔진에 돌려 노출·귀속 측정 → 스코어카드.
       engine=None이면 사용 가능한 엔진 자동 선택(Perplexity→Claude).
       반환 {"engine","results":[{q,kind,basis,present,in_answer,cited_sources,...}],"summary":{...}}."""
    engine = engine or default_engine()
    asker = _ENGINES.get(engine)
    if not asker:
        return {"error": f"미지원 엔진: {engine}"}
    qs = queries or build_queries(clinic, cfg)
    results = []
    for q in qs:
        row = {"q": q["q"], "kind": q.get("kind"), "basis": q.get("basis")}
        try:
            res = asker(q["q"])
            row.update(find_clinic(clinic, res, known_urls))
        except Exception as e:
            row.update(present=None, error=f"{type(e).__name__}: {e}"[:160])
        results.append(row)
    ok = [r for r in results if r.get("present") is not None]
    hit = [r for r in ok if r["present"]]
    # 귀속 집계: 어떤 채널이 인용됐나
    attr = {}
    for r in hit:
        for c in r.get("cited_sources", []):
            attr[c["channel"]] = attr.get(c["channel"], 0) + 1
    summary = {
        "engine": engine,
        "queries": len(qs),
        "measured": len(ok),
        "present": len(hit),
        "presence_rate": round(len(hit) / len(ok), 3) if ok else None,
        "attribution": attr,
    }
    return {"engine": engine, "results": results, "summary": summary}
