# -*- coding: utf-8 -*-
"""
병원 마케팅 리포트 생성기 — 웹 UI (순수 stdlib, 외부 패키지 불필요)

실행:
    cd ~/Desktop/병원마케팅V2
    python3 -m engine.webapp            # 기본 포트 8600
    python3 -m engine.webapp 8700       # 포트 지정
브라우저: http://localhost:8600

기능:
  GET  /                 병원 목록 + '새 병원 진단' 버튼
  GET  /new              입력 폼
  POST /generate         폼 → inputs/<slug>.json 저장 → 6리포트 생성 → 결과로 이동
  GET  /outputs/<...>    생성된 리포트(정적) 서빙
  POST /regenerate       기존 입력으로 재생성
"""
import email
import email.utils
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 캡처 비전 업로드를 쓰는 채널(§9-2) — 네이버·카카오톡·AEO(약관상 캡처)
CAPTURE_CHANNELS = ["naverplace", "blog", "kakao", "aeo_geo"]

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from engine import generate, scoring, policy, ai_draft, collectors, ingest, kakao, sgis, emr, autopilot, google_places, confidence, ai_search, schema_org, entity_pipeline
    from engine.design import CSS, esc
else:
    from . import generate, scoring, policy, ai_draft, collectors, ingest, kakao, sgis, emr, autopilot, google_places, confidence, ai_search, schema_org, entity_pipeline
    from .design import CSS, esc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUTS = os.path.join(ROOT, "inputs")
OUTPUTS = os.path.join(ROOT, "outputs")
BACKUPS = os.path.join(INPUTS, "_backups")   # 덮어쓰기 전 입력 JSON 자동 백업(병원별)
INQUIRIES = os.path.join(ROOT, "inquiries")  # 랜딩 상담 신청 접수함(JSON)
_INQ_LOCK = threading.Lock()                 # 동시 접수 시 파일명 충돌·유실 방지

AREA_TYPES = ["", "주거 밀집형", "주거·상업 혼합", "상업 중심"]

PAGE_CSS = CSS + """
.wrap{max-width:820px}
form label{display:block;font-size:13px;font-weight:700;color:#39424f;margin:14px 0 5px}
form .hint{font-weight:400;color:var(--muted);font-size:12px}
input[type=text],input[type=number],select,textarea{
  width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:9px;font-size:14px;
  font-family:inherit;background:#fff;color:var(--ink)}
textarea{min-height:90px;resize:vertical;line-height:1.6}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px 16px}
.chk{display:inline-flex;align-items:center;gap:7px;font-weight:600;font-size:13px;margin-top:8px}
.chk input{width:auto}
.rmrow{border:1px solid var(--line);border-radius:11px;padding:12px 14px;margin-bottom:9px;background:#fafcff}
.rmrow .rmhead{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.rmrow .rmno{flex:0 0 auto;width:24px;height:24px;border-radius:7px;background:var(--navy);color:#fff;
  font-weight:800;font-size:12px;display:flex;align-items:center;justify-content:center}
.rmrow .rmname{flex:1}.rmrow .rmname input{margin:0;font-weight:700}
.rmgrid{display:grid;grid-template-columns:1fr 1fr 1fr 0.8fr;gap:8px}
.rmgrid label{margin:0 0 3px;font-size:11.5px;color:var(--muted);font-weight:600}
.rmgrid select,.rmgrid input{margin:0;padding:8px 10px;font-size:13px}
@media(max-width:640px){.rmgrid{grid-template-columns:1fr 1fr}}
fieldset{border:1px solid var(--line);border-radius:12px;padding:6px 18px 18px;margin:18px 0;background:var(--card)}
legend{font-weight:800;font-size:14px;color:var(--navy);padding:0 8px}
.btn{display:inline-block;background:var(--navy);color:#fff;border:none;border-radius:10px;
  padding:12px 22px;font-size:15px;font-weight:800;cursor:pointer;text-decoration:none;margin-top:20px}
.btn.sec{background:#fff;color:var(--navy);border:1px solid var(--line);font-weight:700;padding:8px 15px;font-size:13px;margin-top:0}
.hcard{display:flex;gap:15px;align-items:center;background:var(--card);border:1px solid var(--line);
  border-radius:14px;padding:16px 20px;box-shadow:var(--shadow);margin:10px 0}
.hcard .hno{flex:0 0 auto;width:44px;height:44px;border-radius:11px;background:var(--sky);color:var(--navy);
  font-weight:800;display:flex;align-items:center;justify-content:center;font-size:15px}
.hcard h3{margin:0;font-size:16px}.hcard p{margin:2px 0 0;font-size:12.5px;color:var(--muted)}
.hcard .acts{margin-left:auto;display:flex;gap:8px}
.empty{color:var(--muted);text-align:center;padding:40px 0}
"""


def shell(title, body, sub=""):
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{esc(title)}</title>
<style>{PAGE_CSS}
header.hero{{background:linear-gradient(135deg,#152B54,#20406f)}}</style></head><body>
<header class="hero"><div class="wrap">
  <div class="kicker">{esc(policy.TOOL_LABEL)}</div>
  <h1>{esc(title)}</h1>{f'<p class="sub">{esc(sub)}</p>' if sub else ''}
</div></header>
<main class="wrap" style="padding-top:22px;padding-bottom:60px">{body}</main>
</body></html>"""


_CONF_COLOR = {"높음": ("#1f7a4d", "#e5f5ec"), "보통": ("#9a6a00", "#fdf3d7"),
               "낮음": ("#b0332a", "#fbe4e1")}


def _conf_badge(level, small=False):
    fg, bg = _CONF_COLOR.get(level, ("#5b6675", "#eef1f5"))
    pad = "2px 8px" if small else "4px 12px"
    return (f'<span style="background:{bg};color:{fg};border-radius:999px;'
            f'padding:{pad};font-size:12px;font-weight:700">신뢰도 {esc(level)}</span>')


def _assess_slug(slug):
    """INPUTS/<slug>.json 을 읽어 신뢰도 평가. 실패 시 None."""
    p = os.path.join(INPUTS, f"{slug}.json")
    if not os.path.isfile(p):
        return None
    try:
        return confidence.assess(json.load(open(p, encoding="utf-8")))
    except Exception:
        return None


def review_page():
    """④ 운영자 저신뢰-검수 화면 — 병원별 신뢰도 + 플래그. 낮음/주의 항목을 눈으로 검수."""
    rows = []
    items = []
    for fn in sorted(os.listdir(INPUTS)) if os.path.isdir(INPUTS) else []:
        if not fn.endswith(".json"):
            continue
        slug = fn[:-5]
        try:
            cfg = json.load(open(os.path.join(INPUTS, fn), encoding="utf-8"))
        except Exception:
            continue
        name = cfg.get("clinic", {}).get("name", slug)
        a = confidence.assess(cfg)
        items.append((slug, name, a))
    # 낮음 → 보통 → 높음 순으로(검수 우선순위)
    order = {"낮음": 0, "보통": 1, "높음": 2}
    items.sort(key=lambda x: (order.get(x[2]["level"], 3), -x[2]["low"], -x[2]["warn"]))
    n_low = sum(1 for _, _, a in items if a["level"] == "낮음")
    n_warn = sum(1 for _, _, a in items if a["level"] == "보통")

    for slug, name, a in items:
        q = urllib.parse.quote(slug)
        has_out = os.path.exists(os.path.join(OUTPUTS, slug, "index.html"))
        flag_html = ""
        for f in a["flags"]:
            color = "#b0332a" if f["sev"] == "low" else "#9a6a00"
            tag = "낮음" if f["sev"] == "low" else "주의"
            url = (f' <a href="{esc(f["url"])}" target="_blank" style="font-size:11px">↗확인</a>'
                   if f.get("url") else "")
            flag_html += (f'<div style="font-size:12.5px;margin:3px 0;color:#333">'
                          f'<b style="color:{color}">[{tag}]</b> <span class="hint">{esc(f["area"])}</span> '
                          f'{esc(f["msg"])}{url}</div>')
        if not flag_html:
            flag_html = '<div style="font-size:12.5px;color:#1f7a4d">✓ 특이 플래그 없음 — 자동 통과 가능</div>'
        report = (f'<a class="btn sec" href="/outputs/{q}/index.html" target="_blank" '
                  f'style="font-size:12px;padding:6px 12px">📄 리포트</a>' if has_out else
                  '<span class="hint">미생성</span>')
        rows.append(
            f'<div class="hcard" style="align-items:flex-start">'
            f'<div style="flex:1">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">'
            f'<h3 style="margin:0">{esc(name)}</h3>{_conf_badge(a["level"])}'
            f'<span class="hint">낮음 {a["low"]} · 주의 {a["warn"]}</span></div>'
            f'{flag_html}</div>'
            f'<div class="acts">{report}</div></div>')

    summary = (f'<div class="info" style="margin-bottom:16px">🔍 <b>검수 우선순위</b> — '
               f'신뢰도 <b style="color:#b0332a">낮음 {n_low}곳</b>, '
               f'<b style="color:#9a6a00">보통 {n_warn}곳</b>. '
               f'낮음은 고객 전달 전 꼭 확인, 높음은 자동 통과 가능합니다. '
               f'(구조화 소스로 판정 — 캡처 실패·디렉토리 오탐·미수집을 자동 감지)</div>')
    body = ('<a class="btn sec" href="/">← 홈</a>' + summary
            + ("".join(rows) if rows else '<div class="empty">평가할 병원이 없습니다.</div>'))
    return shell("운영자 검수 — 신뢰도 플래그", body,
                 "자동 진단이 스스로 저신뢰 항목을 골라줍니다. 애매한 것만 1분 검수 후 전달하세요.")


def _entity_records():
    store = schema_org.STORE_DIR
    recs = []
    if os.path.isdir(store):
        for fn in sorted(os.listdir(store)):
            if fn.endswith(".json"):
                try:
                    recs.append(json.load(open(os.path.join(store, fn), encoding="utf-8")))
                except Exception:
                    pass
    return recs


def _delta_html(pv):
    """post_verify.delta → 심기 전/후 비교 배지."""
    d = (pv or {}).get("delta") or {}
    if not d:
        return ""
    def arrow(pair, pct=False):
        a, b = pair
        fa = ("–" if a is None else (f"{a*100:.0f}%" if pct else a))
        fb = ("–" if b is None else (f"{b*100:.0f}%" if pct else b))
        up = (isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > a)
        color = "#1f7a4d" if up else "#5b6675"
        return f'<b style="color:{color}">{fa} → {fb}</b>'
    ch = d.get("attribution", [[], []])
    return ('<div class="info" style="margin-top:8px;font-size:13px">📈 <b>심기 전 → 후</b> &nbsp; '
            f'노출률 {arrow(d.get("presence_rate",[None,None]),pct=True)} · '
            f'추천문장 언급 {arrow(d.get("in_answer",[0,0]))} · '
            f'인용 채널 {len(ch[0])}종 → {len(ch[1])}종</div>')


def entity_page(msg=""):
    """운영자 게이트 — 엔티티 구독 대행(최신화→심기→검증) 파이프라인 콘솔."""
    recs = _entity_records()
    note = f'<div class="callout g" style="margin-bottom:14px">{esc(msg)}</div>' if msg else ""
    intro = ('<div class="info" style="margin-bottom:16px">🔒 <b>운영자 전용</b> — 구독 전환 병원의 '
             '<b>엔티티 구축 대행</b> 흐름입니다. 5만원 진단엔 코드가 없고, 구독 시 여기서 '
             '<b>①기준선 측정 → ②최신 코드 생성 → ③심기 → ④사후 검증(효과 증명)</b>을 진행합니다. '
             '완성 코드(schema.org)는 이 화면(운영자)에서만 보이며 고객 리포트엔 포함되지 않습니다.</div>')
    subform = (
        '<form method="POST" action="/entity_subscribe" class="card" style="margin-bottom:18px">'
        '<h3 style="margin:0 0 10px">➕ 구독 시작 (기준선 + 코드 생성)</h3>'
        '<div style="display:flex;gap:8px;flex-wrap:wrap">'
        '<input name="name" placeholder="병원명" style="flex:2;min-width:180px">'
        '<input name="address" placeholder="주소(도로명)" style="flex:2;min-width:180px">'
        '<input name="slug" placeholder="slug(영문/숫자, 선택)" style="flex:1;min-width:120px">'
        '</div>'
        '<label class="chk" style="margin-top:10px"><input type="checkbox" name="measure" value="1" checked> '
        'AI 검색 기준선도 지금 측정(수십 초 소요 · Claude 웹검색)</label>'
        '<div style="margin-top:12px"><button class="btn" type="submit">구독 시작 →</button></div>'
        '</form>')
    rows = []
    for r in recs:
        slug = r.get("slug", "")
        q = urllib.parse.quote(slug)
        st = entity_pipeline.status(slug)
        inst = st["install"]
        inst_tag = {"pending": ("t-warn", "심기 전"), "installed": ("t-good", "심음"),
                    "stale": ("t-bad", "재심기 필요")}.get(inst, ("t-warn", inst))
        code_hash = st.get("code_hash") or "–"
        base = "✓" if st.get("baseline") else "–"
        pv = "✓" if st.get("post_verify") else "–"
        acts = (
            f'<form method="POST" action="/entity_refresh" style="display:inline;margin:0">'
            f'<input type="hidden" name="slug" value="{esc(slug)}">'
            f'<button class="btn sec" type="submit" style="font-size:12px;padding:6px 10px">🔄 최신화</button></form> '
            f'<form method="POST" action="/entity_install" style="display:inline;margin:0">'
            f'<input type="hidden" name="slug" value="{esc(slug)}">'
            f'<button class="btn sec" type="submit" style="font-size:12px;padding:6px 10px">📌 심기완료</button></form> '
            f'<form method="POST" action="/entity_verify" style="display:inline;margin:0">'
            f'<input type="hidden" name="slug" value="{esc(slug)}">'
            f'<button class="btn sec" type="submit" style="font-size:12px;padding:6px 10px">🔎 사후검증</button></form> '
            f'<a class="btn sec" href="/entity_code?slug={q}" target="_blank" '
            f'style="font-size:12px;padding:6px 10px">&lt;/&gt; 코드보기</a>')
        rows.append(
            f'<div class="hcard" style="align-items:flex-start"><div style="flex:1">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">'
            f'<h3 style="margin:0">{esc(r.get("clinic_name") or slug)}</h3>'
            f'<span class="tag {inst_tag[0]}">{inst_tag[1]}</span>'
            f'<span class="hint">코드 {esc(code_hash)} · 기준선 {base} · 사후검증 {pv}</span></div>'
            f'<div style="font-size:12.5px;color:#333">다음 단계: <b>{esc(st["next"])}</b></div>'
            f'{_delta_html(r.get("post_verify"))}</div>'
            f'<div class="acts">{acts}</div></div>')
    body = ('<a class="btn sec" href="/">← 홈</a>' + note + intro + subform
            + ("".join(rows) if rows else '<div class="empty">구독 중인 병원이 없습니다.</div>'))
    return shell("엔티티 구독 대행 (운영자)", body,
                 "구독 전환 시 최신화→심기→검증까지 대행하는 흐름을 여기서 운영합니다.")


def entity_code_page(slug):
    """완성 코드 상세(운영자 전용) — schema.org 스크립트 + 설치 안내."""
    rec = entity_pipeline._load(slug)
    if not rec or not rec.get("code"):
        return shell("엔티티 코드", '<a class="btn sec" href="/entity">← 목록</a>'
                     '<div class="empty">생성된 코드가 없습니다. 먼저 구독 시작/최신화를 하세요.</div>')
    code = rec["code"]
    script = code.get("script", "")
    miss = code.get("missing") or []
    miss_html = (f'<div class="note">⚠️ 누락(값 없음) 필드: {esc(", ".join(miss))} — '
                 '해당 정보 확보 후 최신화 권장</div>' if miss else
                 '<div class="info">✅ 핵심 필드 모두 채워짐</div>')
    body = (
        '<a class="btn sec" href="/entity">← 목록</a>'
        f'<h2 style="margin:14px 0 4px">{esc(rec.get("clinic_name") or slug)} · 엔티티 코드</h2>'
        f'<div class="hint" style="margin-bottom:12px">생성 {esc(code.get("generated_at",""))} · '
        f'버전 {esc(code.get("content_hash",""))} · 소스 {esc(", ".join(code.get("sources") or []))}</div>'
        f'{miss_html}'
        '<div class="info" style="margin:12px 0">📌 <b>설치</b> — 이 코드를 병원 홈페이지 '
        '<code>&lt;head&gt;</code> 안에 붙여넣습니다(제작업체에 전달 가능). 방문자 화면은 안 바뀌며 '
        'AI·검색엔진만 읽습니다. 설치 후 <b>구글 Rich Results Test</b>로 인식 확인, 며칠 뒤 '
        '<b>사후검증</b>으로 효과를 측정하세요.</div>'
        f'<textarea readonly style="width:100%;height:340px;font-family:monospace;font-size:12px;'
        f'border:1px solid var(--line);border-radius:8px;padding:12px">{esc(script)}</textarea>')
    return shell("엔티티 코드 (운영자)", body, "구독 산출물 — 고객 리포트엔 포함되지 않습니다.")


def home_page():
    cards = []
    for fn in sorted(os.listdir(INPUTS)) if os.path.isdir(INPUTS) else []:
        if not fn.endswith(".json"):
            continue
        try:
            data = json.load(open(os.path.join(INPUTS, fn), encoding="utf-8"))
        except Exception:
            continue
        clinic = data.get("clinic", {})
        name = clinic.get("slug") or clinic.get("name", fn[:-5])
        has_out = os.path.exists(os.path.join(OUTPUTS, name, "index.html"))
        q = urllib.parse.quote(name)
        acts = (f'<a class="btn sec" href="/outputs/{q}/index.html">리포트 보기</a>'
                if has_out else '<span style="font-size:12px;color:#5b6675">미생성</span>')
        acts += f'<a class="btn sec" href="/edit?slug={q}">✏️ 수정·보완</a>'
        acts += (f'<form method="POST" action="/regenerate" style="margin:0">'
                 f'<input type="hidden" name="slug" value="{esc(name)}">'
                 f'<button class="btn sec" type="submit">재생성</button></form>')
        acts += (f'<form method="POST" action="/delete" style="margin:0" '
                 f'onsubmit="return confirm(\'{esc(clinic.get("name", name))} 병원을 삭제할까요? (입력·리포트 모두 삭제)\')">'
                 f'<input type="hidden" name="slug" value="{esc(name)}">'
                 f'<button class="btn sec" type="submit" style="color:var(--bad);border-color:#f0cfca">삭제</button></form>')
        try:
            _a = confidence.assess(data)
            badge = " " + _conf_badge(_a["level"], small=True)
        except Exception:
            badge = ""
        cards.append(
            f'<div class="hcard">'
            f'<input class="hpick" type="checkbox" name="slugs" value="{esc(name)}" '
            f'form="bulkdel" aria-label="선택" style="width:18px;height:18px;flex:0 0 auto;cursor:pointer">'
            f'<div class="hno">{esc(clinic.get("tier","–"))}차</div>'
            f'<div><h3>{esc(clinic.get("name",name))}{badge}</h3>'
            f'<p>{esc(clinic.get("address",""))} · {esc(clinic.get("date",""))}</p></div>'
            f'<div class="acts">{acts}</div></div>')
    ai_on = ai_draft.available()
    ai_stat = 'AI ✅' if ai_on else 'AI ✕'
    ka_stat = '카카오 ✅' if kakao.available() else '카카오 ✕'
    sg_stat = 'SGIS ✅' if sgis.available() else 'SGIS ✕'
    key_btn = (f'&nbsp;<a class="btn sec" href="/settings" style="padding:12px 18px;font-size:14px">'
               f'🔑 키 설정 <span class="hint">({ai_stat} · {ka_stat} · {sg_stat})</span></a>')
    if cards:
        bulkbar = (
            '<form id="bulkdel" method="POST" action="/delete_bulk" '
            'onsubmit="var n=this.querySelectorAll(\'input[name=slugs]:checked\').length;'
            'if(!n){alert(\'삭제할 병원을 먼저 선택하세요.\');return false;}'
            'return confirm(\'선택한 \'+n+\'개 병원을 삭제할까요? (입력·리포트 모두 삭제, 되돌릴 수 없음)\');">'
            '<div style="display:flex;align-items:center;gap:12px;margin:22px 0 10px">'
            '<label style="display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);cursor:pointer">'
            '<input type="checkbox" style="width:16px;height:16px" '
            'onclick="document.querySelectorAll(\'input.hpick\').forEach(function(c){c.checked=this.checked}.bind(this))">'
            '전체 선택</label>'
            '<button class="btn sec" type="submit" style="color:var(--bad);border-color:#f0cfca;font-size:13px;padding:8px 14px">'
            '🗑 선택 삭제</button>'
            '<span class="hint" style="font-size:12px;color:var(--muted)">테스트 병원을 골라 한 번에 정리하세요.</span>'
            '</div></form>')
        listing = bulkbar + "".join(cards)
    else:
        listing = '<div class="empty">아직 등록된 병원이 없습니다. ‘새 병원 진단’으로 시작하세요.</div>'
    body = ('<a class="btn" href="/auto">🤖 주소로 자동 진단</a>'
            '&nbsp;<a class="btn sec" href="/new" style="padding:12px 18px;font-size:14px">+ 새 병원(수동)</a>'
            '&nbsp;<a class="btn sec" href="/preview" style="padding:12px 18px;font-size:14px">👀 진단 미리보기</a>'
            '&nbsp;<a class="btn sec" href="/review" style="padding:12px 18px;font-size:14px">🔍 검수 대시보드</a>'
            '&nbsp;<a class="btn sec" href="/entity" style="padding:12px 18px;font-size:14px">🔒 엔티티 구독 대행</a>'
            f'{key_btn}'
            + listing)
    return shell("병원 마케팅 리포트 생성기", body,
                 "한 폼에 상권 PDF·경쟁 주소·마케팅/리뷰 원재료를 넣으면 6개 리포트(01 상권~06 12개월)를 자동 생성합니다.")


# ── 미리보기(맛보기) 대시보드 — 주소만 넣으면 "이렇게 진단돼요" 샘플을 즉시 표시 ──
# 전부 클라이언트 사이드(즉시·API 비용 0). 같은 주소는 항상 같은 숫자(주소 해시 기반).
_PREVIEW_HTML = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>병원 마케팅 진단 미리보기</title>
<style>
:root{--navy:#152B54;--accent:#6C5CE7;--accent2:#a99bff;--ink:#1b2330;--muted:#7a8598;
  --line:#e8ebf1;--bg:#f4f5f9;--card:#fff;--good:#12b886;--warn:#f59f00;--shadow:0 4px 20px rgba(20,40,80,.06)}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  background:var(--bg);color:var(--ink);line-height:1.6}
header.hero{background:linear-gradient(135deg,#152B54,#20406f);color:#fff;padding:26px 0}
.wrap{max-width:1000px;margin:0 auto;padding:0 20px}
.kicker{font-size:12px;letter-spacing:.14em;color:#a9bde0;font-weight:700;text-transform:uppercase}
header h1{margin:6px 0 4px;font-size:23px}
header .sub{margin:0;font-size:13.5px;color:#cdd8ee}
.searchbar{background:#fff;border-radius:14px;box-shadow:var(--shadow);padding:16px;margin:20px 0 8px;
  display:grid;grid-template-columns:1.1fr 2fr auto;gap:10px;align-items:end}
.searchbar label{display:block;font-size:12px;font-weight:700;color:#39424f;margin:0 0 5px}
.searchbar input{width:100%;padding:11px 13px;border:1px solid var(--line);border-radius:10px;font-size:14px;
  font-family:inherit;color:var(--ink)}
.searchbar input:focus{outline:none;border-color:var(--accent)}
.gobtn{background:var(--accent);color:#fff;border:none;border-radius:10px;padding:12px 24px;
  font-size:15px;font-weight:800;cursor:pointer;white-space:nowrap;height:44px}
.gobtn:hover{filter:brightness(1.06)}
.tip{font-size:12px;color:var(--muted);margin:2px 4px 26px}
@media(max-width:720px){.searchbar{grid-template-columns:1fr}}
.dash{display:none;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:8px}
.dash.on{display:grid}
.panel{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:26px 28px;box-shadow:var(--shadow)}
.panel h2{margin:0 0 4px;font-size:17px}
.panel .desc{margin:0 0 14px;font-size:12.5px;color:var(--muted)}
.scoretop{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}
.scoreleft{flex:1;min-width:0}
.scoreline{font-size:14px;margin:14px 0 2px}
.scoreline b{color:var(--navy)}
.bigscore{font-size:34px;font-weight:800;color:var(--accent);margin:0 0 12px}
.bigscore small{font-size:15px;color:var(--muted);font-weight:600}
.hlbox{background:#f3f1ff;border-radius:12px;padding:14px 16px;margin-top:8px}
.hlbox .hlk{color:var(--accent);font-weight:800;font-size:14px}
.hlbox p{margin:5px 0 0;font-size:13px;color:#40485a}
.hlbox p b{color:var(--navy)}
.info-row{display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--line);font-size:14px}
.info-row:last-child{border-bottom:none}
.info-row .k{color:var(--muted)}
.info-row .v{font-weight:700;color:var(--navy)}
.info-name{display:flex;align-items:center;gap:11px;padding:4px 0 14px;border-bottom:1px solid var(--line);margin-bottom:4px}
.info-name .ic{width:40px;height:40px;border-radius:11px;background:#eee9ff;color:var(--accent);
  display:flex;align-items:center;justify-content:center;font-size:20px;flex:0 0 auto}
.info-name .nm{font-size:17px;font-weight:800;color:var(--navy)}
.info-name .ad{font-size:12px;color:var(--muted)}
.mcgrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.mc{border:1px solid var(--line);border-radius:12px;padding:14px 12px;text-align:center}
.mc .mck{font-size:12px;color:var(--muted);font-weight:600;margin-bottom:8px}
.mc .mcv{font-size:22px;font-weight:800;color:var(--navy)}
.mc .mcv small{font-size:12px;color:var(--muted);font-weight:600}
.bar-row{display:flex;align-items:center;gap:12px;margin:12px 0}
.bar-row .bl{width:92px;flex:0 0 auto;font-size:13px;font-weight:600;color:#40485a}
.bar-track{flex:1;height:16px;background:#eef0f6;border-radius:9px;overflow:hidden}
.bar-fill{height:100%;border-radius:9px;background:linear-gradient(90deg,var(--accent2),var(--accent))}
.bar-row .bv{width:52px;flex:0 0 auto;text-align:right;font-size:12.5px;font-weight:700;color:var(--navy)}
.cta{background:linear-gradient(135deg,#6C5CE7,#8b7cf0);color:#fff;border-radius:18px;
  padding:28px 30px;margin:20px 0 10px;display:none;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap}
.cta.on{display:flex}
.cta h3{margin:0 0 4px;font-size:19px}
.cta p{margin:0;font-size:13.5px;color:#e9e6ff}
.cta a{background:#fff;color:var(--accent);border-radius:11px;padding:14px 26px;font-size:15px;
  font-weight:800;text-decoration:none;white-space:nowrap}
.disc{display:none;font-size:11.5px;color:var(--muted);margin:2px 4px 40px;line-height:1.7}
.disc.on{display:block}
.homelink{color:#a9bde0;font-size:13px;text-decoration:none}
@media(max-width:720px){.dash{grid-template-columns:1fr}.mcgrid{grid-template-columns:1fr 1fr}}
</style></head><body>
<header class="hero"><div class="wrap">
  <div class="kicker">__TOOL__ · 미리보기</div>
  <h1>우리 병원, 마케팅 진단하면 이렇게 나와요</h1>
  <p class="sub">주소만 넣어보세요. 정식 진단의 결과 화면을 30초 안에 미리 볼 수 있어요. <a class="homelink" href="/">← 홈으로</a></p>
</div></header>
<main class="wrap">
  <div class="searchbar">
    <div><label>병원 이름 <span style="color:var(--muted);font-weight:400">(선택)</span></label>
      <input type="text" id="pv-name" placeholder="○○동물병원" autocomplete="off"></div>
    <div><label>병원 주소</label>
      <input type="text" id="pv-addr" placeholder="예: 인천 부평구 부평대로 000" autocomplete="off"></div>
    <button class="gobtn" id="pv-go">진단 미리보기 →</button>
  </div>
  <p class="tip">💡 실제 데이터 수집 전 <b>예상 결과 샘플</b>입니다. 정확한 수치는 정식 진단에서 상권·경쟁·리뷰를 실제로 분석해 산출합니다.</p>

  <div class="dash" id="pv-dash">
    <!-- 1. 종합 스코어 + 레이더 -->
    <div class="panel">
      <div class="scoretop">
        <div class="scoreleft">
          <h2>마케팅 종합 스코어 <span style="color:var(--muted);font-size:13px">ⓘ</span></h2>
          <p class="scoreline"><b id="pv-clinic">이 병원</b>의 마케팅 스코어는</p>
          <p class="bigscore">★<span id="pv-star">4.2</span> <small>/ 5.0</small></p>
          <div class="hlbox">
            <span class="hlk" id="pv-hlk">온라인 노출 86점</span>
            <p id="pv-hlp"></p>
          </div>
        </div>
        <div style="flex:0 0 auto"><svg id="pv-radar" width="260" height="240" viewBox="0 0 260 240"></svg></div>
      </div>
    </div>
    <!-- 2. 병원 정보 -->
    <div class="panel">
      <h2>진단 대상 정보</h2>
      <p class="desc">입력한 주소 기준으로 상권·경쟁 환경을 추정했어요.</p>
      <div class="info-name">
        <div class="ic">🏥</div>
        <div><div class="nm" id="pv-iname">이 병원</div><div class="ad" id="pv-iaddr">주소 미입력</div></div>
      </div>
      <div class="info-row"><span class="k">추정 상권 유형</span><span class="v" id="pv-area">주거·상업 혼합</span></div>
      <div class="info-row"><span class="k">반경 1km 동물병원</span><span class="v" id="pv-comp">–</span></div>
      <div class="info-row"><span class="k">주변 반려가구(추정)</span><span class="v" id="pv-pet">–</span></div>
      <div class="info-row"><span class="k">시장 경쟁 강도</span><span class="v" id="pv-intensity">–</span></div>
    </div>
    <!-- 3. 마케팅 요약 -->
    <div class="panel">
      <h2>마케팅 요약</h2>
      <p class="desc">진단 리포트에서 산출되는 핵심 지표를 미리 보여드려요.</p>
      <div class="mcgrid">
        <div class="mc"><div class="mck">🔎 검색 노출력</div><div class="mcv"><span id="pv-m1">–</span><small>점</small></div></div>
        <div class="mc"><div class="mck">⭐ 예상 리뷰 평점</div><div class="mcv"><span id="pv-m2">–</span></div></div>
        <div class="mc"><div class="mck">💬 리뷰 자산</div><div class="mcv"><span id="pv-m3">–</span><small>개</small></div></div>
        <div class="mc"><div class="mck">🏁 경쟁 밀도</div><div class="mcv"><span id="pv-m4">–</span><small>점</small></div></div>
        <div class="mc"><div class="mck">📡 운영 채널</div><div class="mcv"><span id="pv-m5">–</span><small>/6</small></div></div>
        <div class="mc"><div class="mck">✍️ 월 콘텐츠</div><div class="mcv"><span id="pv-m6">–</span><small>건</small></div></div>
      </div>
    </div>
    <!-- 4. 채널 운영 현황 -->
    <div class="panel">
      <h2>채널 운영 현황</h2>
      <p class="desc">채널별 예상 활성도예요. 낮은 채널이 성장 여지가 큰 곳이에요.</p>
      <div id="pv-bars"></div>
    </div>
  </div>

  <div class="cta" id="pv-cta">
    <div><h3>실제 데이터로 정식 진단 받아보세요</h3>
      <p>상권 PDF·경쟁 주소·리뷰만 넣으면 6종 리포트(상권~12개월 계획)가 자동 생성됩니다.</p></div>
    <a href="/new">정식 진단 시작하기 →</a>
  </div>
  <p class="disc" id="pv-disc">※ 이 페이지의 숫자는 주소를 바탕으로 만든 <b>예시 샘플</b>이며 실제 측정값이 아닙니다.
  정식 진단은 카카오맵 경쟁 수집, 상권 통계(SGIS), 네이버 플레이스·블로그 리뷰, 진료 데이터를 실제로 분석해 산출합니다.</p>
</main>

<script>
(function(){
  var AXES=["상권력","경쟁우위","온라인 노출","리뷰 평판","진료 강점"];
  var AREA=["주거 밀집형","주거·상업 혼합","상업 중심"];
  var CHANS=["홈페이지","네이버 플레이스","네이버 블로그","인스타그램","카카오톡 채널","유튜브"];
  function hash(s){var h=2166136261;for(var i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);}return h>>>0;}
  function rng(seed){return function(){seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};}
  function pick(r,lo,hi){return Math.round(lo+r()*(hi-lo));}

  function radar(scores){
    var cx=130,cy=120,R=92,N=scores.length,svg="";
    function pt(i,rad){var a=-Math.PI/2+i*2*Math.PI/N;return[cx+rad*Math.cos(a),cy+rad*Math.sin(a)];}
    // 격자 링
    for(var lv=1;lv<=4;lv++){var pts=[];for(var i=0;i<N;i++){var p=pt(i,R*lv/4);pts.push(p[0].toFixed(1)+","+p[1].toFixed(1));}
      svg+='<polygon points="'+pts.join(" ")+'" fill="none" stroke="#e8ebf1" stroke-width="1"/>';}
    // 축선
    for(var i=0;i<N;i++){var p=pt(i,R);svg+='<line x1="'+cx+'" y1="'+cy+'" x2="'+p[0].toFixed(1)+'" y2="'+p[1].toFixed(1)+'" stroke="#e8ebf1" stroke-width="1"/>';}
    // 값 폴리곤
    var vp=[];for(var i=0;i<N;i++){var p=pt(i,R*scores[i]/100);vp.push(p[0].toFixed(1)+","+p[1].toFixed(1));}
    svg+='<polygon points="'+vp.join(" ")+'" fill="rgba(108,92,231,.22)" stroke="#6C5CE7" stroke-width="2"/>';
    for(var i=0;i<N;i++){var p=pt(i,R*scores[i]/100);svg+='<circle cx="'+p[0].toFixed(1)+'" cy="'+p[1].toFixed(1)+'" r="3" fill="#6C5CE7"/>';}
    // 라벨
    for(var i=0;i<N;i++){var p=pt(i,R+18);var anc="middle";if(p[0]>cx+8)anc="start";if(p[0]<cx-8)anc="end";
      svg+='<text x="'+p[0].toFixed(1)+'" y="'+(p[1]+4).toFixed(1)+'" font-size="11" fill="#7a8598" text-anchor="'+anc+'">'+AXES[i]+'</text>';}
    return svg;
  }

  function run(){
    var name=(document.getElementById("pv-name").value||"").trim();
    var addr=(document.getElementById("pv-addr").value||"").trim();
    if(!addr){document.getElementById("pv-addr").focus();return;}
    var r=rng(hash(addr+"|"+name));
    var scores=AXES.map(function(){return pick(r,58,94);});
    var avg=Math.round(scores.reduce(function(a,b){return a+b;},0)/scores.length);
    var star=(avg/20).toFixed(1);
    var maxi=0;for(var i=1;i<scores.length;i++)if(scores[i]>scores[maxi])maxi=i;
    var mini=0;for(var i=1;i<scores.length;i++)if(scores[i]<scores[mini])mini=i;

    var cname=name||"이 병원";
    document.getElementById("pv-clinic").textContent=cname;
    document.getElementById("pv-iname").textContent=cname;
    document.getElementById("pv-iaddr").textContent=addr;
    document.getElementById("pv-star").textContent=star;
    document.getElementById("pv-radar").innerHTML=radar(scores);

    document.getElementById("pv-hlk").textContent=AXES[maxi]+" "+scores[maxi]+"점";
    document.getElementById("pv-hlp").innerHTML="5개 진단 축 중 <b>"+AXES[maxi]+"</b>이(가) 가장 강해요. 반대로 <b>"+AXES[mini]+"</b>은(는) "+scores[mini]+"점으로 키우면 성과가 크게 오를 영역이에요.";

    // 정보 카드
    document.getElementById("pv-area").textContent=AREA[pick(r,0,2)];
    var comp=pick(r,4,17);
    document.getElementById("pv-comp").textContent=comp+"곳";
    document.getElementById("pv-pet").textContent=(pick(r,18,72)*100).toLocaleString()+"가구";
    document.getElementById("pv-intensity").textContent=comp>=12?"높음":(comp>=7?"보통":"낮음");

    // 요약 지표
    document.getElementById("pv-m1").textContent=scores[2];
    document.getElementById("pv-m2").textContent="★"+(3.9+r()*1.0).toFixed(1);
    document.getElementById("pv-m3").textContent=pick(r,40,520).toLocaleString();
    document.getElementById("pv-m4").textContent=scores[1];
    document.getElementById("pv-m5").textContent=pick(r,2,5);
    document.getElementById("pv-m6").textContent=pick(r,1,9);

    // 채널 막대
    var bars="";
    for(var i=0;i<CHANS.length;i++){var v=pick(r,15,95);
      bars+='<div class="bar-row"><span class="bl">'+CHANS[i]+'</span>'+
        '<span class="bar-track"><span class="bar-fill" style="width:'+v+'%"></span></span>'+
        '<span class="bv">'+v+'점</span></div>';}
    document.getElementById("pv-bars").innerHTML=bars;

    document.getElementById("pv-dash").classList.add("on");
    document.getElementById("pv-cta").classList.add("on");
    document.getElementById("pv-disc").classList.add("on");
    document.getElementById("pv-dash").scrollIntoView({behavior:"smooth",block:"start"});
  }
  document.getElementById("pv-go").addEventListener("click",run);
  document.getElementById("pv-addr").addEventListener("keydown",function(e){if(e.key==="Enter")run();});
  document.getElementById("pv-name").addEventListener("keydown",function(e){if(e.key==="Enter")document.getElementById("pv-addr").focus();});
  // URL ?addr= 프리필 시 자동 실행
  var q=new URLSearchParams(location.search);
  if(q.get("name"))document.getElementById("pv-name").value=q.get("name");
  if(q.get("addr")){document.getElementById("pv-addr").value=q.get("addr");run();}
})();
</script>
</body></html>"""


def preview_page():
    return _PREVIEW_HTML.replace("__TOOL__", esc(policy.TOOL_LABEL))


def auto_form_page(msg=""):
    """주소 한 줄 → 자동 진단 리포트 생성 폼(운영자용)."""
    flash = f'<div class="note">{esc(msg)}</div>' if msg else ""
    ai = "✅ 연결됨" if ai_draft.available() else "✕ 미연결(정밀분석 불가)"
    cap = "✅ 세션 있음" if (kakao.available()) else "✕"
    body = f"""{flash}
<div class="info" style="margin-bottom:16px">🤖 <b>주소만 넣으면 자동 진단</b> — 상권·경쟁은 즉시(카카오·통계청·소상공인 빅데이터),
정밀 분석(마케팅·리뷰)은 인스타·네이버 로그인 세션 캡처 + AI로 수집합니다.</div>
<form method="POST" action="/auto_generate">
<fieldset><legend>자동 진단</legend>
  <label>병원 이름</label>
  <input type="text" name="name" placeholder="○○동물병원" required>
  <label>병원 주소</label>
  <input type="text" name="address" placeholder="예: 인천 부평구 부평대로 168" required>
  <label>병원 등급</label>
  <select name="tier"><option value="2">2차 (전문·야간 진료)</option><option value="1">1차 (동네 동물병원)</option></select>
  <label class="chk" style="margin-top:12px"><input type="checkbox" name="deep" value="1">
    정밀 분석 포함 — 마케팅·리뷰 자동 수집 <span class="hint">(1~3분 소요 · AI {esc(ai)})</span></label>
  <div style="margin-top:16px"><button class="btn" type="submit">자동 진단 → 리포트 생성</button>
  &nbsp;<a class="btn sec" href="/">홈으로</a></div>
</fieldset>
</form>
<div class="note" style="margin-top:14px">
  상권 5지표(포화도·입지·상권유형·유동인구·소득)와 경쟁(밀도·빈자리·프로필)은 <b>주소만으로</b> 채워집니다.
  정밀 분석을 켜면 홈페이지·인스타·블로그를 자동 발견·캡처해 마케팅·리뷰까지 진단합니다(발견 실패 채널은 자동 제외).
</div>"""
    return shell("자동 진단", body, "주소 한 줄로 진단 리포트를 자동 생성합니다.")


# ── 랜딩 상담 신청 접수(리드) ──────────────────────────────────────────────
_INQ_FIELDS = ["clinic_name", "address", "manager", "phone", "email", "tier", "message"]


def save_inquiry(payload):
    """상담 신청 1건을 inquiries/<접수번호>.json 으로 저장하고 접수번호를 반환."""
    os.makedirs(INQUIRIES, exist_ok=True)
    ref = time.strftime("%Y%m%d-%H%M%S")
    rec = {k: str(payload.get(k, "")).strip()[:2000] for k in _INQ_FIELDS}
    if not rec["clinic_name"] and not rec["phone"] and not rec["email"]:
        raise ValueError("병원명과 연락처(전화 또는 이메일)를 입력해 주세요.")
    if not (rec["phone"] or rec["email"]):
        raise ValueError("연락받을 전화 또는 이메일을 입력해 주세요.")
    rec.update({"ref": ref, "received_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "신규", "contacted_at": "", "memo": "", "memo_at": "",
                "source": str(payload.get("source", "landing"))[:40]})
    # 동시·같은 초 접수 유실 방지: 락으로 직렬화 + O_EXCL로 원자적 생성
    with _INQ_LOCK:
        n = 1
        cur = ref
        while True:
            path = os.path.join(INQUIRIES, f"{cur}.json")
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                n += 1
                cur = f"{ref}-{n}"
                continue
            rec["ref"] = cur
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
            break
    return rec["ref"]


def load_inquiries():
    """접수함 전체를 최신순으로."""
    if not os.path.isdir(INQUIRIES):
        return []
    out = []
    for fn in os.listdir(INQUIRIES):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(INQUIRIES, fn), encoding="utf-8") as f:
                out.append(json.load(f))
        except Exception:
            continue
    out.sort(key=lambda r: r.get("ref", ""), reverse=True)
    return out


def _inq_path(ref):
    if not ref or "/" in ref or ".." in ref:
        return None
    p = os.path.join(INQUIRIES, f"{ref}.json")
    return p if os.path.isfile(p) else None


def load_inquiry(ref):
    p = _inq_path(ref)
    if not p:
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def set_inquiry_status(ref, status):
    p = _inq_path(ref)
    if not p:
        return False
    with open(p, encoding="utf-8") as f:
        rec = json.load(f)
    rec["status"] = status
    # 연락완료로 바꿀 때 시각 기록, 신규로 되돌리면 지움
    rec["contacted_at"] = time.strftime("%Y-%m-%d %H:%M") if status == "연락완료" else ""
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return True


def set_inquiry_memo(ref, memo):
    p = _inq_path(ref)
    if not p:
        return False
    with open(p, encoding="utf-8") as f:
        rec = json.load(f)
    rec["memo"] = str(memo or "").strip()[:4000]
    rec["memo_at"] = time.strftime("%Y-%m-%d %H:%M") if rec["memo"] else ""
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return True


def delete_inquiry(ref):
    p = _inq_path(ref)
    if not p:
        return False
    os.remove(p)
    return True


def set_inquiry_fields(ref, **fields):
    p = _inq_path(ref)
    if not p:
        return False
    with open(p, encoding="utf-8") as f:
        rec = json.load(f)
    rec.update(fields)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return True


def run_diagnosis_bg(ref):
    """[백그라운드 스레드] 주문의 병원명·주소로 자동 진단(정밀) → 리포트 생성.
       진행상태를 레코드에 기록(diag_status: 진단중→완료/실패)."""
    rec = load_inquiry(ref)
    if not rec:
        return
    name = rec.get("clinic_name", "")
    address = rec.get("address", "")
    tier = 1 if str(rec.get("tier", "")).startswith("1") else 2
    slug = "order_" + (rec.get("ref") or "x")
    set_inquiry_fields(ref, diag_status="진단중", report_slug=slug,
                       diag_started=time.strftime("%Y-%m-%d %H:%M"))
    try:
        cfg = autopilot.build_config_auto(name, address, tier=tier, deep=True,
                                          slug=slug, date=time.strftime("%Y-%m-%d"))
        path = os.path.join(INPUTS, f"{slug}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        generate.run(path)
        set_inquiry_fields(ref, diag_status="완료", report_slug=slug,
                           diag_done=time.strftime("%Y-%m-%d %H:%M"))
    except Exception as e:
        set_inquiry_fields(ref, diag_status="실패", diag_error=str(e)[:300])


# ── 투자자 시연(데모): 주소 → 실시간 정밀 진단 / 하이브리드 즉시 재생 ──────────
# 결제 단계 없이 랜딩에서 바로 리포트까지. 프리웜 매니페스트에 매칭되면 즉시 완료.
_DEMO = {}                         # slug -> {status, stage, name, address, started, error}
_DEMO_LOCK = threading.Lock()
DEMO_MANIFEST = os.path.join(ROOT, "demo_prewarm.json")   # [{slug,namekey,addrkey,name,address}]
DEMO_STAGES = ["상권·입지 분석", "경쟁 병원 스캔", "온라인 노출 진단", "리뷰·평판 분석", "리포트 생성"]


def _demo_norm(s):
    return re.sub(r"[^0-9a-z가-힣]", "", (s or "").lower())


def _load_prewarm():
    try:
        return json.load(open(DEMO_MANIFEST, encoding="utf-8"))
    except Exception:
        return []


def resolve_demo_slug(name, address, fresh=False):
    """하이브리드: 프리웜/기존 리포트에 매칭되면 (slug, True=즉시완료).
       없으면 (새 slug, False=실시간 진단 필요)."""
    if not fresh:
        nk, ak = _demo_norm(name), _demo_norm(address)
        for e in _load_prewarm():
            ek, eak = e.get("namekey", ""), e.get("addrkey", "")
            hit = (nk and nk == ek) or (ak and eak and (ak in eak or eak in ak))
            if hit and os.path.exists(os.path.join(OUTPUTS, e["slug"], "index.html")):
                return e["slug"], True
    h = hashlib.sha1((_demo_norm(name) + "|" + _demo_norm(address)).encode()).hexdigest()[:10]
    slug = "demo_" + h
    if not fresh and os.path.exists(os.path.join(OUTPUTS, slug, "index.html")):
        return slug, True
    return slug, False


def run_demo_bg(slug, name, address, tier=2):
    """[백그라운드] 실시간 정밀 진단 → outputs/<slug>. 상태는 _DEMO에 기록."""
    with _DEMO_LOCK:
        _DEMO[slug] = {"status": "진단중", "stage": DEMO_STAGES[0], "name": name,
                       "address": address, "started": time.time(), "error": ""}
    try:
        cfg = autopilot.build_config_auto(name, address, tier=tier, deep=True,
                                          slug=slug, date=time.strftime("%Y-%m-%d"))
        with open(os.path.join(INPUTS, f"{slug}.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        generate.run(os.path.join(INPUTS, f"{slug}.json"))
        with _DEMO_LOCK:
            if slug in _DEMO:
                _DEMO[slug].update(status="완료", stage="완료")
    except Exception as e:
        with _DEMO_LOCK:
            if slug in _DEMO:
                _DEMO[slug].update(status="실패", error=str(e)[:300])


def demo_status(slug):
    with _DEMO_LOCK:
        rec = dict(_DEMO.get(slug, {}))
    done = os.path.exists(os.path.join(OUTPUTS, slug, "index.html"))
    status = rec.get("status") or ("완료" if done else "없음")
    if status == "진단중" and done:
        status = "완료"
    return {"status": status, "stage": rec.get("stage", ""),
            "report_url": (f"/outputs/{urllib.parse.quote(slug)}/index.html"
                           if (status == "완료" and done) else ""),
            "error": rec.get("error", "")}


def demo_progress_page(slug, name, addr):
    """몰입형 실시간 분석 화면(단계 애니메이션 + 폴링). 자체 완결 HTML."""
    stages = "".join(
        f'<li data-i="{i}"><span class="sdot"></span><span class="slabel">{esc(s)}</span>'
        f'<span class="scheck">✓</span></li>' for i, s in enumerate(DEMO_STAGES))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>진단 분석 중 · {esc(name)}</title>
<style>
:root{{--ink:#0A1A2F;--pulse:#12D8A0;--coral:#FF6B5A;--mut:#8fa0b8;--line:#1c3350}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;background:radial-gradient(1200px 600px at 50% -10%,#12294a,var(--ink));
  color:#fff;font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;
  display:flex;align-items:center;justify-content:center;padding:28px}}
.box{{width:100%;max-width:560px;text-align:center}}
.eyebrow{{display:inline-flex;gap:8px;align-items:center;font-size:13px;color:var(--pulse);
  letter-spacing:.02em;font-weight:600;margin-bottom:14px}}
.eyebrow .hb{{width:9px;height:9px;border-radius:50%;background:var(--pulse);animation:hb 1.1s infinite}}
@keyframes hb{{0%,100%{{opacity:.35;transform:scale(.8)}}50%{{opacity:1;transform:scale(1.25)}}}}
h1{{margin:0 0 4px;font-size:23px;font-weight:800}}
.addr{{color:var(--mut);font-size:13.5px;margin-bottom:26px}}
.barwrap{{height:9px;background:#12233c;border-radius:99px;overflow:hidden;margin:0 0 8px}}
.bar{{height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,#0ea882,var(--pulse));
  transition:width .6s cubic-bezier(.4,0,.2,1)}}
.pct{{font-size:12.5px;color:var(--mut);margin-bottom:24px;font-variant-numeric:tabular-nums}}
ul.stages{{list-style:none;margin:0;padding:0;text-align:left}}
ul.stages li{{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:12px;
  border:1px solid transparent;color:var(--mut);font-size:15px;transition:.35s}}
ul.stages li .sdot{{width:20px;height:20px;border-radius:50%;border:2px solid #29456a;flex:0 0 auto;position:relative}}
ul.stages li .scheck{{margin-left:auto;opacity:0;color:var(--pulse);font-weight:800}}
ul.stages li.active{{color:#fff;border-color:var(--line);background:#0f2340}}
ul.stages li.active .sdot{{border-color:var(--pulse);
  box-shadow:0 0 0 4px rgba(18,216,160,.15);animation:pdot 1s infinite}}
@keyframes pdot{{0%,100%{{box-shadow:0 0 0 3px rgba(18,216,160,.10)}}50%{{box-shadow:0 0 0 6px rgba(18,216,160,.22)}}}}
ul.stages li.done{{color:#cfe}}
ul.stages li.done .sdot{{background:var(--pulse);border-color:var(--pulse)}}
ul.stages li.done .scheck{{opacity:1}}
.foot{{margin-top:22px;font-size:12.5px;color:#66788f}}
.done-cta{{margin-top:26px;display:none}}
.done-cta.on{{display:block;animation:fade .5s}}
@keyframes fade{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1}}}}
.btn{{display:inline-block;padding:15px 30px;border-radius:13px;background:var(--pulse);color:#04231a;
  font-weight:800;font-size:16px;text-decoration:none;border:none;cursor:pointer}}
.err{{margin-top:22px;color:var(--coral);font-size:14px;display:none}}
.err.on{{display:block}}
</style></head><body>
<div class="box">
  <div class="eyebrow"><span class="hb"></span>PETAMOS · 실시간 진단</div>
  <h1 id="hname">{esc(name)}</h1>
  <div class="addr">{esc(addr)}</div>
  <div class="barwrap"><div class="bar" id="bar"></div></div>
  <div class="pct" id="pct">분석 준비 중…</div>
  <ul class="stages">{stages}</ul>
  <div class="foot" id="foot">상권·경쟁·마케팅·리뷰를 실시간으로 수집·분석하고 있습니다.</div>
  <div class="done-cta" id="donecta"><a class="btn" id="openbtn" href="#">📄 진단 리포트 열기 &nbsp;→</a></div>
  <div class="err" id="err"></div>
</div>
<script>
(function(){{
  var slug={json.dumps(slug)};
  var stages=document.querySelectorAll('ul.stages li');
  var bar=document.getElementById('bar'),pct=document.getElementById('pct');
  var t0=Date.now();var reportUrl='';var finished=false;
  var MIN_MS=7000;               // 하이브리드도 최소 7초는 '분석중'으로 보여줌
  var DEEP_MS=300000;            // 실시간 정밀 예상치(~5분) 기준 곡선
  function setStage(idx){{
    stages.forEach(function(li,i){{
      li.classList.toggle('done',i<idx);
      li.classList.toggle('active',i===idx);
    }});
  }}
  function tick(){{
    var el=Date.now()-t0;
    // 완료 전까지 92%에 점근, 완료되면 100%
    var target=finished?100:Math.min(92,Math.round(92*(1-Math.exp(-el/90000))));
    bar.style.width=target+'%';
    var idx=Math.min(stages.length-1,Math.floor(target/92*stages.length));
    if(finished)idx=stages.length-1;
    setStage(finished?stages.length:idx);
    pct.textContent=finished?'분석 완료 · 100%':('분석 중 · '+target+'%  ·  '+Math.floor(el/1000)+'초 경과');
  }}
  function reveal(){{
    stages.forEach(function(li){{li.classList.remove('active');li.classList.add('done');}});
    bar.style.width='100%';pct.textContent='분석 완료 · 100%';
    document.getElementById('foot').textContent='6종 진단 리포트가 준비되었습니다.';
    var b=document.getElementById('openbtn');b.href=reportUrl;
    document.getElementById('donecta').classList.add('on');
    setTimeout(function(){{location.href=reportUrl;}},2200);   // 자동 이동(완료 순간 보여준 뒤)
  }}
  function poll(){{
    fetch('/demo_status?slug='+encodeURIComponent(slug)).then(function(r){{return r.json();}})
      .then(function(s){{
        if(s.status==='실패'){{
          document.getElementById('err').textContent='분석 중 오류가 발생했습니다: '+(s.error||'')+' — 다시 시도해 주세요.';
          document.getElementById('err').classList.add('on');pct.textContent='';return;
        }}
        if(s.status==='완료'&&s.report_url){{
          reportUrl=s.report_url;finished=true;tick();
          var wait=Math.max(0,MIN_MS-(Date.now()-t0));
          setTimeout(reveal,wait);return;
        }}
        setTimeout(poll,2500);
      }}).catch(function(){{setTimeout(poll,3000);}});
  }}
  var anim=setInterval(function(){{if(finished){{clearInterval(anim);tick();return;}}tick();}},700);
  poll();
}})();
</script></body></html>"""


def inquiries_csv(rows):
    """접수 목록 → CSV 바이트(엑셀 한글 대응 BOM)."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["접수일시", "병원명", "주소", "담당자", "전화", "이메일", "규모",
                "상태", "연락완료시각", "요청사항", "메모", "접수번호"])
    for r in rows:
        w.writerow([r.get("received_at", ""), r.get("clinic_name", ""), r.get("address", ""),
                    r.get("manager", ""), r.get("phone", ""), r.get("email", ""), r.get("tier", ""),
                    r.get("status", ""), r.get("contacted_at", ""), r.get("message", ""),
                    r.get("memo", ""), r.get("ref", "")])
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ── 어드민 접근 비밀번호(개인정보 보호) ──
ADMIN_PW_FILE = os.path.expanduser("~/.config/petamos/admin_pw")


def load_admin_pw():
    pw = (os.environ.get("PETAMOS_ADMIN_PW") or "").strip()
    if pw:
        return pw
    try:
        with open(ADMIN_PW_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def save_admin_pw(pw):
    os.makedirs(os.path.dirname(ADMIN_PW_FILE), exist_ok=True)
    with open(ADMIN_PW_FILE, "w", encoding="utf-8") as f:
        f.write((pw or "").strip())
    try:
        os.chmod(ADMIN_PW_FILE, 0o600)
    except Exception:
        pass


def forget_admin_pw():
    try:
        os.remove(ADMIN_PW_FILE)
    except Exception:
        pass


def admin_token(pw):
    import hashlib
    return hashlib.sha256(("petamos-admin|" + pw).encode("utf-8")).hexdigest()[:32]


_ADMIN_CSS = (
    '<style>'
    '.wrap{max-width:1120px}'
    '.abar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-bottom:16px}'
    '.badge{font-weight:800;font-size:13px;background:#e7fbf4;color:#0BA47B;border-radius:8px;padding:6px 12px}'
    '.badge.g{background:#eef1f5;color:#5b6675}'
    '.chip{font-size:13px;font-weight:700;padding:7px 13px;border-radius:999px;border:1px solid var(--line);'
    'background:#fff;color:#5b6675;text-decoration:none}'
    '.chip.on{background:var(--navy);color:#fff;border-color:var(--navy)}'
    '.asearch{display:flex;gap:6px;margin-left:auto}'
    '.asearch input{padding:8px 12px;border:1px solid var(--line);border-radius:9px;font-size:13.5px;min-width:170px}'
    '.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px}'
    'table.admin{width:100%;border-collapse:collapse;font-size:13.5px;background:#fff}'
    'table.admin th{text-align:left;background:#f6f8fb;color:#5b6675;font-weight:700;padding:11px 13px;'
    'border-bottom:1px solid var(--line);white-space:nowrap}'
    'table.admin td{padding:11px 13px;border-bottom:1px solid #eef1f5;vertical-align:top}'
    'table.admin tr:hover td{background:#fbfcfe}'
    'table.admin .sub{color:#8792a3;font-size:12px;margin-top:2px}'
    'table.admin .sub a,table.admin a.cl{color:var(--navy);text-decoration:none}'
    'table.admin a.cl{font-weight:800}table.admin a.cl:hover{text-decoration:underline}'
    'table.admin .msg{max-width:230px;color:#39424f}'
    'table.admin .mono{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;white-space:nowrap;color:#5b6675}'
    '.pill{font-size:12px;font-weight:800;border-radius:999px;padding:4px 11px;white-space:nowrap}'
    '.pill.new{background:#fff1ef;color:#d84a3a}.pill.done{background:#eef7f2;color:#0BA47B}'
    '.drow{display:flex;justify-content:space-between;gap:16px;padding:13px 0;border-bottom:1px solid var(--line);font-size:14.5px}'
    '.drow .k{color:var(--muted);flex:0 0 130px}.drow .v{font-weight:600;text-align:right;color:var(--navy)}'
    '.dcard{background:#fff;border:1px solid var(--line);border-radius:14px;padding:8px 22px 20px;box-shadow:var(--shadow-sm)}'
    '</style>')


def _contact_html(r):
    parts = []
    if r.get("phone"):
        parts.append(f'<a href="tel:{esc(r["phone"])}">{esc(r["phone"])}</a>')
    if r.get("email"):
        parts.append(f'<a href="mailto:{esc(r["email"])}">{esc(r["email"])}</a>')
    return " · ".join(parts) or "–"


def _match(r, q):
    if not q:
        return True
    q = q.lower()
    for k in ("clinic_name", "address", "manager", "phone", "email", "message", "memo", "tier"):
        if q in str(r.get(k, "")).lower():
            return True
    return False


def admin_page(q="", status_filter="all", flash=""):
    allrows = load_inquiries()
    new_cnt = sum(1 for r in allrows if r.get("status") == "신규")
    done_cnt = len(allrows) - new_cnt
    rows = [r for r in allrows
            if (status_filter in ("all", "") or r.get("status", "신규") == status_filter) and _match(r, q)]

    def chip(key, label):
        qs = urllib.parse.urlencode({k: v for k, v in (("status", key), ("q", q)) if v and v != "all"})
        on = " on" if status_filter == key or (key == "all" and status_filter in ("all", "")) else ""
        return f'<a class="chip{on}" href="/admin{("?" + qs) if qs else ""}">{label}</a>'

    warn = ("" if load_admin_pw() else
            '<div class="note">🔓 <b>이 화면은 지금 비밀번호 없이 열립니다.</b> 접수자 연락처 등 개인정보가 있으니 '
            '<a href="/settings">설정</a>에서 <b>관리자 비밀번호</b>를 지정하세요.</div>')
    flashhtml = f'<div class="note">{esc(flash)}</div>' if flash else ""

    exp_qs = urllib.parse.urlencode({k: v for k, v in (("status", status_filter), ("q", q)) if v and v != "all"})
    bar = (
        '<div class="abar">'
        f'<span class="badge">신규 {new_cnt}건</span>'
        f'<span class="badge g">연락완료 {done_cnt}건</span>'
        f'{chip("all", "전체")}{chip("신규", "신규")}{chip("연락완료", "연락완료")}'
        '<form class="asearch" method="GET" action="/admin">'
        + (f'<input type="hidden" name="status" value="{esc(status_filter)}">' if status_filter not in ("all", "") else "")
        + f'<input type="text" name="q" value="{esc(q)}" placeholder="병원명·연락처 검색">'
        '<button class="btn sec" type="submit">검색</button></form>'
        f'<a class="btn sec" href="/admin_export.csv{("?" + exp_qs) if exp_qs else ""}">CSV 내보내기</a>'
        '<a class="btn sec" href="/landing">랜딩</a>'
        '<a class="btn sec" href="/admin_logout">로그아웃</a>'
        '</div>')

    if not allrows:
        body = _ADMIN_CSS + warn + bar + '<div class="empty">아직 접수된 상담 신청이 없습니다.</div>'
        return shell("상담 신청 관리", body, "랜딩 페이지에서 접수된 상담 신청을 확인합니다.")
    if not rows:
        table = '<div class="empty">조건에 맞는 신청이 없습니다.</div>'
    else:
        trs = []
        for r in rows:
            st = r.get("status", "신규")
            if st == "신규":
                badge = '<span class="pill new">신규</span>'
            else:
                ca = esc(r.get("contacted_at", "") or "")
                badge = '<span class="pill done">연락완료</span>' + (f'<div class="sub">{ca}</div>' if ca else "")
            ref = esc(r.get("ref", ""))
            memo_mark = ' 📝' if r.get("memo") else ""
            nm = esc(r.get("clinic_name", "")) or "–"
            tier = esc(r.get("tier", "") or "–")
            msg = esc(r.get("message", "") or "")
            if len(msg) > 90:
                msg = msg[:90] + "…"
            toggle_to = "연락완료" if st == "신규" else "신규"
            toggle_label = "연락완료로" if st == "신규" else "신규로"
            trs.append(
                f'<tr><td class="mono">{esc(r.get("received_at",""))}</td>'
                f'<td><a class="cl" href="/admin_view?ref={ref}">{nm}</a>{memo_mark}'
                f'<div class="sub">{esc(r.get("address",""))}</div></td>'
                f'<td>{esc(r.get("manager","")) or "–"}<div class="sub">{_contact_html(r)}</div></td>'
                f'<td>{tier}</td>'
                f'<td class="msg">{msg or "–"}</td>'
                f'<td>{badge}</td>'
                f'<td><form method="POST" action="/inquiry_status" style="margin:0">'
                f'<input type="hidden" name="ref" value="{ref}">'
                f'<input type="hidden" name="status" value="{toggle_to}">'
                f'<input type="hidden" name="q" value="{esc(q)}">'
                f'<input type="hidden" name="sf" value="{esc(status_filter)}">'
                f'<button class="btn sec" type="submit">{toggle_label}</button></form></td></tr>')
        table = ('<div class="tablewrap"><table class="admin"><thead><tr>'
                 '<th>접수일시</th><th>병원</th><th>담당자·연락처</th><th>규모</th><th>요청사항</th><th>상태</th><th></th>'
                 '</tr></thead><tbody>' + "".join(trs) + '</tbody></table></div>')
    return shell("상담 신청 관리", _ADMIN_CSS + warn + flashhtml + bar + table,
                 "랜딩 페이지에서 접수된 상담 신청을 확인합니다.")


def admin_detail_page(ref, flash=""):
    r = load_inquiry(ref)
    if not r:
        return shell("없음", _ADMIN_CSS + '<p>신청을 찾을 수 없습니다. <a href="/admin">목록으로</a></p>')
    st = r.get("status", "신규")
    badge = ('<span class="pill new">신규</span>' if st == "신규"
             else '<span class="pill done">연락완료</span>'
                  + (f' <span class="sub" style="display:inline">{esc(r.get("contacted_at",""))}</span>'
                     if r.get("contacted_at") else ""))
    refq = esc(r.get("ref", ""))

    def row(k, v):
        return f'<div class="drow"><span class="k">{k}</span><span class="v">{v}</span></div>'

    info = (row("접수일시", f'<span class="mono">{esc(r.get("received_at",""))}</span>')
            + row("상태", badge)
            + row("병원 이름", esc(r.get("clinic_name", "")) or "–")
            + row("주소", esc(r.get("address", "")) or "–")
            + row("담당자", esc(r.get("manager", "")) or "–")
            + row("연락처", _contact_html(r))
            + row("병원 규모", esc(r.get("tier", "")) or "–")
            + row("접수번호", f'<span class="mono">{refq}</span>'))
    msg = esc(r.get("message", "")) or "<span style=\"color:var(--muted)\">(요청사항 없음)</span>"
    msg_block = (f'<h3 style="font-size:15px;margin:22px 0 8px">요청·궁금한 점</h3>'
                 f'<div style="background:#f6f8fb;border-radius:10px;padding:14px 16px;font-size:14px;'
                 f'line-height:1.7;white-space:pre-wrap">{msg}</div>')

    memo_at = f' <span class="hint">(마지막 저장 {esc(r.get("memo_at",""))})</span>' if r.get("memo_at") else ""
    memo_block = (
        f'<h3 style="font-size:15px;margin:24px 0 8px">상담 메모{memo_at}</h3>'
        f'<form method="POST" action="/inquiry_note">'
        f'<input type="hidden" name="ref" value="{refq}">'
        f'<textarea name="memo" placeholder="통화 결과·다음 할 일 등을 적어두세요" '
        f'style="width:100%;min-height:120px;padding:12px 13px;border:1px solid var(--line);border-radius:10px;'
        f'font-family:inherit;font-size:14px;line-height:1.6;resize:vertical">{esc(r.get("memo",""))}</textarea>'
        f'<div style="margin-top:10px"><button class="btn" type="submit">메모 저장</button></div></form>')

    toggle_to = "연락완료" if st == "신규" else "신규"
    toggle_label = "연락완료로 표시" if st == "신규" else "신규로 되돌리기"
    actions = (
        '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:26px;'
        'padding-top:20px;border-top:1px solid var(--line)">'
        f'<form method="POST" action="/inquiry_status" style="margin:0">'
        f'<input type="hidden" name="ref" value="{refq}"><input type="hidden" name="status" value="{toggle_to}">'
        f'<input type="hidden" name="back" value="view">'
        f'<button class="btn" type="submit">{toggle_label}</button></form>'
        f'<form method="POST" action="/inquiry_delete" style="margin:0" '
        f'onsubmit="return confirm(\'이 상담 신청을 삭제할까요? 되돌릴 수 없습니다.\')">'
        f'<input type="hidden" name="ref" value="{refq}">'
        f'<button class="btn sec" type="submit" style="color:var(--bad);border-color:#f0cfca">삭제</button></form>'
        '<a class="btn sec" href="/admin" style="margin-left:auto">← 목록으로</a></div>')

    # 자동 진단(정밀) 실행 + 상태 + 리포트 링크
    dstat = r.get("diag_status", "")
    rslug = r.get("report_slug", "")
    if dstat == "완료" and rslug:
        diag_inner = (
            f'<span class="pill done">진단 완료</span> '
            f'<span class="sub" style="display:inline">{esc(r.get("diag_done",""))}</span>'
            f'<div style="margin-top:12px"><a class="btn" target="_blank" '
            f'href="/outputs/{urllib.parse.quote(rslug)}/index.html">📄 리포트 열기</a> '
            f'<span class="hint">이 링크를 고객에게 전달하세요.</span></div>')
    elif dstat == "진단중":
        diag_inner = (
            '<span class="pill new">진단 중…</span> '
            '<span class="hint">자동 분석에 약 4~5분 걸립니다. 완료되면 리포트 링크가 표시됩니다. '
            '<a href="javascript:location.reload()">새로고침</a></span>')
    else:
        warn = (f'<div class="note" style="border-color:#f0cfca;color:#b23b2b">진단 실패 — {esc(r.get("diag_error",""))}</div>'
                if dstat == "실패" else "")
        btnlabel = "다시 진단 실행" if dstat == "실패" else "자동 진단 실행 (정밀·6종)"
        diag_inner = (
            warn + '<p class="hint" style="margin:0 0 10px">입금 확인 후 실행하세요. 병원명·주소로 '
            '상권·경쟁·마케팅·리뷰를 자동 수집해 6종 리포트를 만듭니다(약 4~5분).</p>'
            f'<form method="POST" action="/run_diagnosis" style="margin:0">'
            f'<input type="hidden" name="ref" value="{refq}">'
            f'<button class="btn" type="submit">{btnlabel} →</button></form>')
    diag_block = ('<h3 style="font-size:15px;margin:24px 0 8px">자동 진단 · 리포트</h3>'
                  f'<div style="background:#f6f8fb;border-radius:10px;padding:14px 16px">{diag_inner}</div>')

    flashhtml = f'<div class="note">{esc(flash)}</div>' if flash else ""
    body = _ADMIN_CSS + flashhtml + f'<div class="dcard">{info}{diag_block}{msg_block}{memo_block}{actions}</div>'
    return shell(f'{r.get("clinic_name","상담 신청")} — 상세', body, "정식 진단 주문 상세 · 자동 진단 실행")


def admin_login_page(error=""):
    err = f'<div class="note" style="border-color:#f0cfca;color:#b23b2b">{esc(error)}</div>' if error else ""
    body = f"""<style>.wrap{{max-width:420px}}</style>
{err}
<div class="info" style="margin-bottom:16px">🔐 <b>관리자 전용</b> — 상담 신청 접수함입니다. 비밀번호를 입력하세요.</div>
<form method="POST" action="/admin_login">
<fieldset><legend>관리자 로그인</legend>
  <label>비밀번호</label>
  <input type="password" name="pw" autocomplete="current-password" autofocus>
  <div style="margin-top:14px"><button class="btn" type="submit">로그인 →</button>
  &nbsp;<a class="btn sec" href="/landing">랜딩으로</a></div>
</fieldset>
</form>"""
    return shell("관리자 로그인", body, "상담 신청 관리자 페이지")


def _pv(prefill, key):
    """prefill 값 → HTML 속성/텍스트용(escape)."""
    return esc(prefill.get(key, "")) if prefill else ""


# ③ 채널 원재료 입력 스펙: (type, 라벨, link/capture, placeholder)
_CH_META = [
    ("homepage", "홈페이지", "link", "https://병원홈페이지.com"),
    ("tmap", "T맵", "link", "T맵 장소 URL"),
    ("map", "카카오맵", "link", "카카오맵 장소 URL (공개 메타만)"),
    ("instagram", "인스타그램", "link", "https://instagram.com/계정 (공개 메타만)"),
    ("naverplace", "네이버 플레이스", "capture", "★4.9 리뷰 210, 정보 충실…"),
    ("blog", "네이버 블로그", "capture", "이웃 1200, 월 1~2회 발행…"),
    ("kakao", "카카오톡 채널", "capture", "친구 300, 상담창구 없음…"),
    ("aeo_geo", "AEO·GEO", "capture", "구조화데이터 일부, FAQ 없음…"),
]


def _channel_raw_fields():
    """③ 마케팅 원재료 입력 HTML — (링크 자동수집 HTML, 캡처 업로드 HTML)."""
    link_html, cap_html = [], []
    for ct, lab, mode, ph in _CH_META:
        if mode == "link":
            note = ' <span class="hint">(공개 메타만·약관 준수)</span>' if ct in ("map", "instagram") else ""
            cap_hint = (' <span class="hint">— URL과 캡처를 <b>함께</b> 넣으면 더 정확(URL=팔로워·게시물, 캡처=화면·콘텐츠)</span>'
                        if ct == "instagram" else ' <span class="hint">(선택 · URL과 함께 넣으면 정확도↑)</span>')
            link_html.append(
                f'<label>{esc(lab)} URL{note}</label>'
                f'<input type="text" name="url_{ct}" placeholder="{esc(ph)}">'
                f'<label style="font-size:11.5px;color:var(--muted);margin:6px 0 3px">{esc(lab)} 캡처{cap_hint}</label>'
                f'<input type="file" name="cap_{ct}" accept="image/*" multiple>'
                f'<textarea name="raw_{ct}" placeholder="(선택) 보완 메모 — 예약버튼 없음, 후기 OFF…" style="min-height:44px"></textarea>')
        else:
            cap_html.append(
                f'<label>{esc(lab)} 캡처 이미지 <span class="hint">(여러 장 가능 · Claude 판독)</span></label>'
                f'<input type="file" name="cap_{ct}" accept="image/*" multiple>'
                f'<textarea name="raw_{ct}" placeholder="(선택) 캡처요약 메모 — {esc(ph)}" style="min-height:44px"></textarea>')
    return "".join(link_html), "".join(cap_html)


def _mk_select(name, val):
    """운영/없음/미확인 드롭다운(기본 미확인)."""
    cur = val if val in ("운영", "없음", "미확인") else "미확인"
    opts = "".join(f'<option value="{o}"{" selected" if o == cur else ""}>{o}</option>'
                   for o in ("미확인", "운영", "없음"))
    return f'<select name="{name}">{opts}</select>'


def _rival_marketing_rows(prefill):
    """경쟁사 마케팅 현황 — TOP 3 구조화 입력 행(이름 + 채널 드롭다운)."""
    prefill = prefill or {}
    rows = []
    for i in (1, 2, 3):
        nm = _pv(prefill, f"rm_name_{i}")
        rows.append(
            f'<div class="rmrow"><div class="rmhead">'
            f'<span class="rmno">{i}</span>'
            f'<span class="rmname"><input type="text" name="rm_name_{i}" value="{nm}" '
            f'placeholder="경쟁사 {i} 이름 (예: ○○동물메디컬센터)"></span></div>'
            f'<div class="rmgrid">'
            f'<div><label>홈페이지</label>{_mk_select(f"rm_home_{i}", prefill.get(f"rm_home_{i}"))}</div>'
            f'<div><label>블로그</label>{_mk_select(f"rm_blog_{i}", prefill.get(f"rm_blog_{i}"))}</div>'
            f'<div><label>인스타</label>{_mk_select(f"rm_insta_{i}", prefill.get(f"rm_insta_{i}"))}</div>'
            f'<div><label>리뷰수</label><input type="number" name="rm_review_{i}" '
            f'value="{_pv(prefill, f"rm_review_{i}")}" placeholder="선택"></div>'
            f'</div>'
            f'<label style="font-size:11.5px;color:var(--muted);margin:8px 0 3px">특화(선택) '
            f'<span class="hint">— 플레이스·홈피에서 확인한 진료 특화. 넣으면 포지셔닝 맵이 ‘✓ 확인’으로 정확해집니다</span></label>'
            f'<input type="text" name="rm_spec_{i}" value="{_pv(prefill, f"rm_spec_{i}")}" '
            f'placeholder="예: 치과, 심장, 영상(CT·MRI) — 쉼표로 구분">'
            f'<details style="margin:8px 0 0"><summary class="hint" style="cursor:pointer">🔎 실제 분석 자동화 — 홈피·인스타 URL / 블로그·리뷰 캡처</summary>'
            f'<div class="rmgrid" style="margin-top:6px">'
            f'<div><label>홈페이지 URL</label><input type="text" name="rm_home_url_{i}" '
            f'value="{_pv(prefill, f"rm_home_url_{i}")}" placeholder="https://… (자동수집)"></div>'
            f'<div><label>인스타 URL</label><input type="text" name="rm_insta_url_{i}" '
            f'value="{_pv(prefill, f"rm_insta_url_{i}")}" placeholder="https://instagram.com/…"></div>'
            f'</div>'
            f'<label style="font-size:11.5px;color:var(--muted);margin:8px 0 3px">캡처 업로드 '
            f'<span class="hint">— 경쟁사 네이버 플레이스·블로그·리뷰 캡처(여러 장). Claude가 리뷰수·별점·키워드·채널 운영을 판독</span></label>'
            f'<input type="file" name="rm_cap_{i}" accept="image/*" multiple>'
            f'</details>'
            f'</div>')
    return "".join(rows)


def new_form_page(prefill=None, edit_slug=None):
    prefill = prefill or {}
    kakao_on = kakao.available()
    ai_on = ai_draft.available()
    link_html, cap_html = _channel_raw_fields()
    ai_hint = ("" if ai_on else
               '<div class="note">✨ AI 초안(원재료→자동 진단)을 쓰려면 <a href="/settings">API 키 설정</a>이 필요합니다. '
               '키 없이도 상권·경쟁은 됩니다(마케팅·리뷰는 비거나 아래 JSON 직접 입력).</div>')
    emr_hint = ("" if emr.available() else
                "<br><span class=\"hint\">⚠️ 현재 xlsx 판독 라이브러리(openpyxl)가 없어 <b>CSV로 올려주세요</b>. (엑셀은 CSV로 저장 후 업로드)</span>")
    tier = str(prefill.get("tier", "2"))
    opts = "".join(
        f'<option value="{esc(a)}"{" selected" if prefill.get("area_type")==a else ""}>{esc(a or "선택 안 함")}</option>'
        for a in AREA_TYPES)
    ai_banner = ""
    if prefill.get("_ai_note"):
        cnote = f'<br>📥 {esc(prefill["_collect_note"])}' if prefill.get("_collect_note") else ""
        ai_banner = (f'<div class="note"><b>AI 초안이 채워졌습니다 — 검수 후 생성하세요.</b> '
                     f'{esc(prefill["_ai_note"])} · ③④ JSON을 확인·수정하고 상권/경쟁을 채운 뒤 아래 버튼을 누르세요.{cnote}</div>')
    collected = bool(prefill.get("_collect_result"))
    auto_chk = "" if collected else " checked"
    collect_banner = ""
    if collected:
        collect_banner = (f'<div class="info"><b>🗺️ 카카오 수집 결과입니다 — 확인·수정 후 생성하세요.</b> '
                          f'{esc(prefill["_collect_result"])}</div>')
    edit_banner = ""
    edit_hidden = ""
    action = "/generate"
    if edit_slug:
        action = "/update"
        edit_hidden = f'<input type="hidden" name="slug" value="{esc(edit_slug)}">'
        edit_banner = ('<div class="info"><b>✏️ 수정·보완 모드</b> — 기존 입력이 채워져 있습니다. '
                       '<b>빠진 부분만 채우거나 고친 뒤</b> 저장하세요. 건드리지 않은 값과 '
                       '<b>진료데이터(EMR)·기존 리포트</b>는 그대로 유지됩니다.</div>')
    sub = ("수정·보완 후 저장하면 리포트가 다시 생성됩니다." if edit_slug
           else "AI가 채운 초안을 검수·수정한 뒤 생성하세요." if prefill.get("_ai_note")
           else "카카오 수집 결과를 확인·수정한 뒤 생성하세요." if collected
           else "필수는 병원명뿐입니다. 나머지는 있는 데이터만 넣으면 됩니다.")
    body = f"""
{edit_banner}{ai_banner}{collect_banner}
<form method="POST" action="{action}" enctype="multipart/form-data">
{edit_hidden}
<fieldset><legend>기본 정보</legend>
  <label>병원명 *</label><input type="text" name="name" required value="{_pv(prefill,'name')}" placeholder="예: 송도스카이동물메디컬센터">
  <div class="grid2">
    <div><label>주소</label><input type="text" name="address" value="{_pv(prefill,'address')}" placeholder="인천 연수구 …"></div>
    <div><label>전화</label><input type="text" name="phone" value="{_pv(prefill,'phone')}" placeholder="032-000-0000"></div>
  </div>
  <div class="grid2">
    <div><label>병원 종류(tier)</label><select name="tier"><option value="2"{" selected" if tier=="2" else ""}>2차(전문·의료센터)</option><option value="1"{" selected" if tier=="1" else ""}>1차(동네 병원)</option></select></div>
    <div><label>진단일</label><input type="text" name="date" value="{_pv(prefill,'date')}" placeholder="2026-08-13"></div>
  </div>
</fieldset>

<fieldset><legend>① 상권</legend>
  <label>🅿 간단분석 리포트(PDF) 업로드 <span class="hint">(소상공인 상권정보 — 넣으면 월매출·유동인구·병원수·등록수 자동 채움)</span></label>
  <input type="file" name="sangkwon_pdf" accept="application/pdf,.pdf">
  {f'<div class="info" style="margin-top:6px">✅ PDF에서 추출된 상권 데이터가 유지됩니다: <b>{esc(prefill.get("region_label",""))}</b> · 매출 {prefill.get("monthly_sales_manwon","–")}만 · 유동 {prefill.get("daily_footfall","–")} · 가구수 {prefill.get("households","–")}. (다시 첨부 안 해도 됩니다)</div>' if prefill.get("region_label") else ""}
  <input type="hidden" name="region_label" value="{_pv(prefill,'region_label')}">
  <input type="hidden" name="region_clinics" value="{_pv(prefill,'region_clinics')}">
  <input type="hidden" name="population" value="{_pv(prefill,'population')}">
  <p class="hint">📄 PDF만 넣으면 아래 값이 자동 계산됩니다. 나머지(가구수·역세권·상권유형)는 있으면 보완 입력.</p>
  <div class="grid3">
    <div><label>시군구 가구수</label><input type="number" name="households" value="{_pv(prefill,'households')}" placeholder="168000"></div>
    <div><label>지역 동물병원 수</label><input type="number" name="clinics_in_region" value="{_pv(prefill,'clinics_in_region')}" placeholder="29"></div>
    <div><label>등록 반려동물수</label><input type="number" name="registered_pets" value="{_pv(prefill,'registered_pets')}" placeholder="41000"></div>
  </div>
  <div class="grid3">
    <div><label>최근접역</label><input type="text" name="nearest_station" value="{_pv(prefill,'nearest_station')}" placeholder="센트럴파크역"></div>
    <div><label>역 거리(m)</label><input type="number" name="nearest_station_m" value="{_pv(prefill,'nearest_station_m')}" placeholder="600"></div>
    <div><label>상권유형</label><select name="area_type">{opts}</select></div>
  </div>
  <div class="grid2">
    <div><label>월매출(만원)</label><input type="number" name="monthly_sales_manwon" value="{_pv(prefill,'monthly_sales_manwon')}" placeholder="5000"></div>
    <div><label>일유동인구</label><input type="number" name="daily_footfall" value="{_pv(prefill,'daily_footfall')}" placeholder="90000"></div>
  </div>
  <label class="chk"><input type="checkbox" name="parking" value="1"{" checked" if prefill.get("parking") else ""}> 주차 가능</label>
  &nbsp;&nbsp;<label class="chk"><input type="checkbox" name="apartment_dense" value="1"{" checked" if prefill.get("apartment_dense") else ""}> 아파트 밀집</label>
</fieldset>

<fieldset><legend>② 경쟁</legend>
  {f'''<div style="background:var(--sky);border:1px solid #cfe0f2;border-radius:10px;padding:12px 14px;margin-bottom:10px">
    <b>🗺️ 방법 A — 카카오로 먼저 수집 → 확인(권장)</b>
    <p class="hint" style="margin:4px 0 8px">기본정보에 <b>병원명·주소·tier</b>를 넣고 아래 버튼을 누르면, 반경 내 동물병원을 수집해 이 폼에 채워 다시 보여줍니다. 결과를 보고 <b>진짜 경쟁병원만 남기고</b> 나머지는 지운 뒤 생성하세요.</p>
    <button class="btn sec" type="submit" formaction="/collect_competition">🗺️ 카카오로 먼저 수집 → 결과 확인</button>
    <p class="hint" style="margin-top:8px">💡 이 버튼은 지금 입력한 값으로 수집만 합니다(생성 아님). <b>파일 첨부(PDF·캡처·EMR)는 수집 후에</b> 하세요.</p>
    <label class="chk" style="margin-top:6px"><input type="checkbox" name="auto_competition" value="1"{auto_chk}> 또는 <b>방법 B — 생성할 때 자동수집</b>(결과 확인 없이 바로)</label>
  </div>'''
   if kakao_on else
   '<div class="note">🗺️ 카카오 자동수집을 쓰려면 <a href="/settings">카카오 키 설정</a>이 필요합니다. 지금은 아래 목록을 직접 넣으세요.</div>'}
  <p class="hint">반경: 1차=1km · 2차=3km. 수집 병원은 경쟁(동급) vs 의뢰처(타 tier)로 자동 분류됩니다. {'주소가 비면 실패하니 위 주소를 꼭 넣으세요.' if kakao_on else ''}</p>
  <label style="margin-top:10px">직접 목록(선택·자동수집 대신/보완) <span class="hint">한 줄에 하나: 병원명, 카테고리, 거리(m)</span></label>
  <textarea name="clinics" placeholder="연수24시동물메디컬센터, 동물병원, 900&#10;송도1동물병원, 동물병원, 250&#10;…">{_pv(prefill,'clinics')}</textarea>
  <label style="margin-top:14px">🆚 경쟁사 마케팅 현황 — 핵심 경쟁 <b>3곳만</b> <span class="hint">(선택 · 넣으면 상권 온라인 성숙도·빈 채널·전략 제언 자동 분석)</span></label>
  <div class="info" style="margin:2px 0 10px">
    <b>가장 신경 쓰이는 경쟁병원 3곳</b>만 골라, 그 병원이 각 채널을 운영하는지 <b>드롭다운으로 선택</b>하세요.
    <ul style="margin:6px 0 0;padding-left:18px;font-size:13px;line-height:1.7">
      <li><b>운영</b> = 그 병원이 홈페이지/블로그/인스타를 <b>하고 있음</b></li>
      <li><b>없음</b> = 검색·지도에서 <b>찾아봐도 없음</b> → <b>우리에겐 기회</b>(빈 채널)로 반영</li>
      <li><b>미확인</b> = 아직 안 봄 → 성숙도 계산에서 <b>제외</b>(기본값)</li>
      <li><b>리뷰수</b> = 네이버 플레이스 리뷰 개수(선택)</li>
    </ul>
    💡 1차 병원 주변은 경쟁사 상당수가 ‘없음’일 수 있고, 그건 곧 <b>저비용 선점 기회</b>입니다.
  </div>
  {_rival_marketing_rows(prefill)}
  <details style="margin:4px 0 0"><summary class="hint" style="cursor:pointer">4곳 이상 직접 입력(고급)</summary>
    <p class="hint">한 줄에 하나: 병원명, 홈페이지, 블로그, 인스타[, 리뷰수] — 각 칸 운영/없음/미확인. (위 3칸이 비어 있을 때만 사용)</p>
    <textarea name="rival_marketing" placeholder="행복동물병원, 없음, 없음, 없음, 22&#10;튼튼동물병원, 운영, 운영, 없음, 210">{_pv(prefill,'rival_marketing')}</textarea>
  </details>
</fieldset>

<fieldset><legend>③-A 마케팅 링크 자동수집 <span class="hint">(URL만 넣으면 AI가 채널 진단 초안 생성)</span></legend>
  {ai_hint}
  {link_html}
  <p class="hint">홈피·T맵은 자동수집, 카카오맵·인스타는 공개 메타만. 네이버·카카오톡은 아래 ③-B 캡처로.</p>
</fieldset>
<fieldset><legend>③-B 마케팅 캡처 업로드 <span class="hint">(네이버·카카오톡·AEO — Claude 비전이 판독)</span></legend>
  <p class="hint">📸 별점·리뷰수가 또렷하게 보이게 캡처하세요(너무 크면 자동 축소).</p>
  {cap_html}
</fieldset>
<fieldset><legend>④ 리뷰 <span class="hint">(네이버·구글 리뷰 — 캡처 또는 원문)</span></legend>
  <label>리뷰 캡처 이미지 <span class="hint">(여러 장 가능 · Claude가 별점·리뷰 판독)</span></label>
  <input type="file" name="cap_reviews" accept="image/*" multiple>
  <label>리뷰 원문 <span class="hint">(캡처에 없는 채널은 여기 붙여넣기 — 예: 구글 리뷰. 캡처와 <b>함께</b> 넣으면 채널별로 분석)</span></label>
  <textarea name="raw_reviews" style="min-height:90px" placeholder="네이버: ★5 &quot;야간 응급에 CT까지…&quot; / 구글: ★2 &quot;대기 길었어요&quot; …"></textarea>
</fieldset>
<fieldset><legend>⑤ 진료데이터(EMR) <span class="hint">(선택 · 넣으면 07 진료데이터분석 리포트 추가 생성)</span></legend>
  <label>🗂️ 진료 백업 파일 업로드 <span class="hint">(.csv · .xlsx — 우리엔·이프렌즈·오케이차트 등 내보내기)</span></label>
  {'<div class="info" style="margin-bottom:6px">✅ 이미 진료데이터가 등록돼 있습니다 — <b>그대로 유지</b>됩니다. 아래에 <b>새 파일을 올리면 교체</b>됩니다.</div>' if prefill.get("_has_emr") else ""}
  <input type="file" name="emr_file" accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet">
  <div class="info" style="margin-top:8px"><b>🔒 개인정보는 안전합니다.</b> 업로드 즉시 <b>보호자명·전화·주소는 삭제</b>되고 환자는 가명(해시)으로만 처리됩니다.
  원본 개인정보는 <b>저장하지 않고</b> 집계 지표(재진율·휴면·객단가·질환)만 리포트에 담깁니다.
  {emr_hint}</div>
  <p class="hint">최소 <b>진료일 + 금액</b> 컬럼만 있으면 됩니다. 컬럼명이 달라도(수납액·내원일 등) 자동 인식합니다.</p>
</fieldset>
<details style="margin:6px 0 14px"><summary class="hint" style="cursor:pointer">고급: ③④ JSON 직접 입력/편집</summary>
  <label>marketing (JSON) <span class="hint">AI 초안 대신 직접 넣으려면</span></label>
  <textarea name="marketing_json" placeholder='{{"channels":[{{"type":"homepage","score":74,"note":"…"}}]}}'>{_pv(prefill,'marketing_json')}</textarea>
  <label>review (JSON)</label>
  <textarea name="review_json" placeholder='{{"channels":[{{"name":"네이버 플레이스","review_count":120,"rating":4.8,"sentiment":{{"pos":88,"neu":8,"neg":4}}}}]}}'>{_pv(prefill,'review_json')}</textarea>
</details>

<button class="btn" type="submit">{'💾 저장하고 다시 생성 →' if edit_slug else '6개 리포트 생성 →'}</button>
&nbsp;<a class="btn sec" href="/">취소</a>
</form>"""
    return shell("병원 수정·보완" if edit_slug else "새 병원 진단", body, sub)


def ai_form_page():
    """원재료 → AI 초안 흐름의 입력 폼 (③ 마케팅·④ 리뷰 원재료)."""
    avail = ai_draft.available()
    status = ai_draft.status_text()
    banner = (f'<div class="info"><b>AI 초안 사용 가능.</b> {esc(status)} · 아래 원재료를 넣으면 '
              'Claude가 채널·리뷰 진단 초안(JSON)을 만들어 검수 화면에 채워줍니다.</div>'
              if avail else
              f'<div class="note"><b>AI 미연결 — 예시(목업) 초안으로 흐름만 시연됩니다.</b> {esc(status)}. '
              '<br>실제로 켜려면 → <a href="/settings"><b>🔑 API 키 설정</b></a> 화면에서 키를 붙여넣으세요. '
              '(모델 claude-opus-4-8 · 채널당 1회 호출)</div>')
    # §9 채널 매트릭스: link(자동수집) vs capture(약관상 캡처요약)
    CH_META = [
        ("homepage", "홈페이지", "link", "https://병원홈페이지.com"),
        ("tmap", "T맵", "link", "T맵 장소 URL"),
        ("map", "카카오맵", "link", "카카오맵 장소 URL (공개 메타만)"),
        ("instagram", "인스타그램", "link", "https://instagram.com/계정 (공개 메타만)"),
        ("naverplace", "네이버 플레이스", "capture", "★4.9 리뷰 210, 정보 충실, 소식 뜸함…"),
        ("blog", "네이버 블로그", "capture", "이웃 1200, 월 1~2회 발행, 수술 케이스 위주…"),
        ("kakao", "카카오톡 채널", "capture", "친구 300, 상담창구 없음, 소식 거의 없음…"),
        ("aeo_geo", "AEO·GEO", "capture", "구조화데이터 일부, FAQ 없음, 브랜드 검색 상위…"),
    ]
    link_html, cap_html = [], []
    for ct, lab, mode, ph in CH_META:
        if mode == "link":
            note = ' <span class="hint">(공개 메타만·약관 준수)</span>' if ct in ("map", "instagram") else ""
            link_html.append(
                f'<label>{esc(lab)} URL{note}</label>'
                f'<input type="text" name="url_{ct}" placeholder="{esc(ph)}">'
                f'<textarea name="raw_{ct}" placeholder="(선택) 자동수집 보완 메모 — 예: 예약버튼 없음, 후기 OFF…" style="min-height:52px"></textarea>')
        else:
            cap_html.append(
                f'<label>{esc(lab)} 캡처 이미지 <span class="hint">(여러 장 가능 · Claude가 판독)</span></label>'
                f'<input type="file" name="cap_{ct}" accept="image/*" multiple>'
                f'<textarea name="raw_{ct}" placeholder="(선택) 캡처요약 메모 — {esc(ph)}" style="min-height:48px"></textarea>')
    body = f"""
{banner}
<form method="POST" action="/ai_draft" enctype="multipart/form-data">
<fieldset><legend>기본 정보</legend>
  <label>병원명 *</label><input type="text" name="name" required placeholder="예: 송도스카이동물메디컬센터">
  <div class="grid2">
    <div><label>주소</label><input type="text" name="address" placeholder="인천 연수구 …"></div>
    <div><label>병원 종류(tier)</label><select name="tier"><option value="2">2차</option><option value="1">1차</option></select></div>
  </div>
</fieldset>
<fieldset><legend>③-A 링크 자동수집 <span class="hint">(URL만 넣으면 title·meta·전화·구조화데이터·SPA를 자동 추출)</span></legend>
  {''.join(link_html)}
  <p class="hint">홈피·T맵은 자동수집, 카카오맵·인스타는 공개 메타만 조회합니다. 네이버·카카오톡은 약관상 자동수집하지 않아 아래 ③-B 캡처 업로드로 넣으세요(Claude 비전이 판독).</p>
</fieldset>
<fieldset><legend>③-B 캡처 업로드 <span class="hint">(네이버·카카오톡·AEO — 약관상 캡처만, Claude 비전이 판독)</span></legend>
  <p class="hint">📸 팁: 별점·리뷰수 등 <b>값이 또렷하게 보이게</b> 캡처하세요. 전체 페이지를 아주 길게 찍기보다 <b>화면 단위로 여러 장</b>이 판독이 정확합니다. (너무 큰 이미지는 자동 축소됩니다)</p>
  {''.join(cap_html)}
</fieldset>
<fieldset><legend>④ 리뷰 <span class="hint">(네이버·구글 리뷰 — 캡처 업로드 또는 원문 붙여넣기)</span></legend>
  <label>리뷰 캡처 이미지 <span class="hint">(여러 장 가능 · Claude가 별점·리뷰 판독)</span></label>
  <input type="file" name="cap_reviews" accept="image/*" multiple>
  <label>리뷰 원문 <span class="hint">(캡처에 없는 채널은 여기 붙여넣기 — 예: 구글 리뷰. 캡처와 <b>함께</b> 넣으면 채널별로 분석)</span></label>
  <textarea name="raw_reviews" style="min-height:110px" placeholder="네이버: ★5 &quot;야간 응급에 CT까지 빠르게…&quot; / 구글: ★2 &quot;예약해도 대기 길었어요&quot; …"></textarea>
</fieldset>
<button class="btn" type="submit">AI 초안 생성 → 검수</button>
&nbsp;<a class="btn sec" href="/">취소</a>
</form>"""
    return shell("AI 초안으로 시작", body,
                 "원재료(링크·캡처요약·리뷰 원문)를 넣으면 AI가 ③마케팅·④리뷰 초안을 만들어 검수 화면에 채웁니다.")


def settings_page(msg=""):
    """웹에서 ANTHROPIC_API_KEY를 넣는 화면 (터미널 export 불필요)."""
    cur = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if cur:
        masked = (cur[:7] + "…" + cur[-4:]) if len(cur) > 14 else "설정됨"
        state = (f'<div class="callout g" style="margin-bottom:14px">✅ <b>AI 초안 사용 가능</b> · '
                 f'현재 키 <b>{esc(masked)}</b> · {esc(ai_draft.status_text())}</div>')
    else:
        state = (f'<div class="note" style="margin-bottom:14px">🔑 <b>아직 키가 없습니다.</b> '
                 f'{esc(ai_draft.status_text())} — 아래에 붙여넣고 저장하세요.</div>')
    saved = f'<div class="callout g" style="margin-bottom:14px">{esc(msg)}</div>' if msg else ""
    disk = ('<div class="info" style="margin-bottom:14px">💾 이 맥에 <b>저장된 키가 있습니다</b> — 웹앱을 재시작해도 자동 로드됩니다. '
            '<form method="POST" action="/forget_key" style="display:inline;margin:0">'
            '<button class="btn sec" type="submit">저장된 키 삭제</button></form></div>'
            if ai_draft.has_saved_key() else "")
    body = f"""
{saved}{state}{disk}
<div class="info" style="margin-bottom:16px">
  1) <b>https://platform.claude.com</b> 접속 → 로그인 → <b>API Keys</b> → <b>Create Key</b><br>
  2) <code>sk-ant-…</code> 로 시작하는 키를 복사해서 아래에 붙여넣고 <b>저장</b><br>
  <span class="hint">저장하면 이 웹앱이 실행 중인 동안 바로 적용됩니다(터미널 재시작 불필요).</span>
</div>
<form method="POST" action="/save_key">
<fieldset><legend>ANTHROPIC API 키</legend>
  <label>키 붙여넣기 <span class="hint">(화면에 가려져 보입니다 · 저장 후 뒤 4자리만 표시)</span></label>
  <input type="password" name="api_key" autocomplete="off" placeholder="sk-ant-..." style="font-family:monospace">
  <label class="chk" style="margin-top:10px"><input type="checkbox" name="remember" value="1" checked> 이 맥에 저장 (재시작해도 자동 로드)</label>
  <div style="margin-top:14px"><button class="btn" type="submit">키 저장 →</button>
  &nbsp;<a class="btn sec" href="/">홈으로</a></div>
</fieldset>
</form>
<div class="note" style="margin-top:16px">
  <b>저장 위치</b> — 체크 시 <code>~/.config/petamos/api_key</code> 에 소유자만 읽기(0600)로 저장됩니다(프로젝트 폴더 밖이라 폴더 공유해도 안 딸려감).
  체크 해제하면 이번 실행 동안만(메모리) 유지됩니다.
  <br>키가 노출되면 콘솔에서 즉시 <b>Revoke</b> 후 재발급하고, 위 <b>저장된 키 삭제</b>를 누르세요.
</div>

<hr style="margin:34px 0 22px;border:none;border-top:1px solid var(--line)">
{_kakao_section()}
<hr style="margin:34px 0 22px;border:none;border-top:1px solid var(--line)">
{_sgis_section()}
<hr style="margin:34px 0 22px;border:none;border-top:1px solid var(--line)">
{_google_section()}
<hr style="margin:34px 0 22px;border:none;border-top:1px solid var(--line)">
{_perplexity_section()}
<hr style="margin:34px 0 22px;border:none;border-top:1px solid var(--line)">
{_admin_pw_section()}"""
    return shell("API 키 설정", body, "터미널 없이 웹에서 키를 넣어 AI 초안·경쟁·인구 연동을 켭니다.")


def _google_section():
    """구글 리뷰(Google Places API) 키 입력 섹션."""
    if google_places.available():
        state = ('<div class="callout g" style="margin-bottom:14px">✅ <b>구글 리뷰 연동 사용 가능</b> · '
                 '리뷰 축에 구글 평점·리뷰수·샘플 리뷰가 추가됩니다.</div>')
    else:
        state = ('<div class="note" style="margin-bottom:14px">🔎 <b>구글 리뷰 미연동.</b> '
                 '네이버 플레이스만 수집 중 — 키를 넣으면 구글 리뷰도 자동 수집합니다.</div>')
    forget = ('<form method="POST" action="/forget_google" style="display:inline;margin:0">'
              '<button class="btn sec" type="submit">저장된 키 삭제</button></form>'
              if google_places.has_saved_key() else "")
    return f"""{state}
<div class="info" style="margin-bottom:14px">
  1) <b>console.cloud.google.com</b> → 프로젝트 → <b>API 및 서비스 → 라이브러리</b>에서 <b>Places API</b> 사용 설정<br>
  2) <b>사용자 인증 정보 → API 키 만들기</b> → 키 복사 후 아래에 붙여넣기<br>
  <span class="hint">월 $200 무료 크레딧 내에서 우리 사용량은 사실상 무료입니다.</span>
</div>
<form method="POST" action="/save_google">
<fieldset><legend>Google Places API 키 (구글 리뷰)</legend>
  <label>키 붙여넣기 <span class="hint">(저장 후 재시작해도 자동 로드)</span></label>
  <input type="password" name="google_key" autocomplete="off" placeholder="AIza..." style="font-family:monospace">
  <div style="margin-top:14px"><button class="btn" type="submit">키 저장 →</button>
  &nbsp;{forget}
  &nbsp;<a class="btn sec" href="/">홈으로</a></div>
</fieldset>
</form>
<div class="note" style="margin-top:12px">저장 위치 <code>~/.config/petamos/google_key</code>(0600). 배포 시엔 환경변수 <code>GOOGLE_PLACES_KEY</code> 권장.</div>"""


def _admin_pw_section():
    """상담 신청 관리자(/admin) 접근 비밀번호 설정."""
    has = bool(load_admin_pw())
    env = bool((os.environ.get("PETAMOS_ADMIN_PW") or "").strip())
    if has:
        via = "환경변수(PETAMOS_ADMIN_PW)" if env else "이 맥에 저장됨"
        state = (f'<div class="callout g" style="margin-bottom:14px">🔐 <b>관리자 페이지가 보호됩니다</b> · '
                 f'비밀번호 설정됨({esc(via)}) — /admin 접근 시 로그인 필요</div>')
    else:
        state = ('<div class="note" style="margin-bottom:14px">🔓 <b>관리자 페이지가 개방 상태입니다.</b> '
                 '상담 신청함에는 접수자 연락처(개인정보)가 있으니 비밀번호를 지정하세요.</div>')
    forget = ('<form method="POST" action="/forget_admin_pw" style="display:inline;margin:0">'
              '<button class="btn sec" type="submit">비밀번호 삭제(개방)</button></form>'
              if has and not env else "")
    envnote = ('<div class="note" style="margin-top:12px">환경변수 <code>PETAMOS_ADMIN_PW</code> 가 설정되어 있어 '
               '그 값이 우선합니다(배포용). 바꾸려면 환경변수를 수정하세요.</div>' if env else "")
    return f"""{state}
<form method="POST" action="/save_admin_pw">
<fieldset><legend>관리자 페이지 비밀번호</legend>
  <label>비밀번호 {'변경' if has else '설정'} <span class="hint">(상담 신청 관리자 /admin 로그인용 · 나와 담당자만 공유)</span></label>
  <input type="password" name="admin_pw" autocomplete="new-password" placeholder="비밀번호 입력">
  <div style="margin-top:14px"><button class="btn" type="submit">비밀번호 저장 →</button>
  &nbsp;{forget}
  &nbsp;<a class="btn sec" href="/admin">관리자 페이지</a></div>
</fieldset>
</form>{envnote}
<div class="note" style="margin-top:12px">저장 위치 <code>~/.config/petamos/admin_pw</code>(0600). 클라우드 배포 시엔 환경변수 <code>PETAMOS_ADMIN_PW</code> 사용을 권장합니다.</div>"""


def _sgis_section():
    """통계청 SGIS(인구·가구) 키 입력 섹션."""
    if sgis.available():
        state = (f'<div class="callout g" style="margin-bottom:14px">✅ <b>SGIS 인구·가구 연동 사용 가능</b> · '
                 f'{esc(sgis.status_text())}</div>')
    else:
        state = ('<div class="note" style="margin-bottom:14px">📊 <b>SGIS 키가 없습니다.</b> '
                 '넣으면 상권분석 시 <b>시군구 가구수를 자동 조회</b>해 반려가구를 정석(가구수×0.28)으로 계산합니다. '
                 '없으면 등록수 기반 추정으로 대체됩니다.</div>')
    disk = ('<div class="info" style="margin-bottom:14px">💾 SGIS 키가 <b>이 맥에 저장</b>돼 있습니다. '
            '<form method="POST" action="/forget_sgis" style="display:inline;margin:0">'
            '<button class="btn sec" type="submit">저장된 SGIS 키 삭제</button></form></div>'
            if sgis.has_saved_key() else "")
    return f"""
<h2 style="font-size:19px;margin:0 0 10px">📊 통계청 SGIS 키 <span class="hint" style="font-weight:400">(인구·가구)</span></h2>
{state}{disk}
<div class="info" style="margin-bottom:16px">
  1) <b>https://sgis.kostat.go.kr/developer</b> → 회원가입/로그인 → <b>인증정보 신청(OpenAPI)</b><br>
  2) 발급된 <b>서비스 ID</b>와 <b>보안 Key</b> 2개를 아래에 넣고 저장하면, 주소만으로 가구수를 자동 조회합니다.
</div>
<form method="POST" action="/save_sgis">
<fieldset><legend>SGIS 서비스 ID · 보안 Key</legend>
  <label>서비스 ID (consumer_key)</label>
  <input type="text" name="sgis_key" autocomplete="off" placeholder="서비스 ID" style="font-family:monospace">
  <label>보안 Key (consumer_secret)</label>
  <input type="password" name="sgis_secret" autocomplete="off" placeholder="보안 Key" style="font-family:monospace">
  <label class="chk" style="margin-top:10px"><input type="checkbox" name="remember" value="1" checked> 이 맥에 저장 (재시작해도 자동 로드)</label>
  <div style="margin-top:14px"><button class="btn" type="submit">SGIS 키 저장 →</button></div>
</fieldset>
</form>"""


def _kakao_section():
    """경쟁 자동수집용 카카오 REST 키 입력 섹션."""
    if kakao.available():
        state = (f'<div class="callout g" style="margin-bottom:14px">✅ <b>카카오 자동수집 사용 가능</b> · '
                 f'{esc(kakao.status_text())}</div>')
    else:
        state = (f'<div class="note" style="margin-bottom:14px">🗺️ <b>카카오 키가 없습니다.</b> '
                 '경쟁분석을 "주소만 넣으면 반경 내 병원 자동수집"으로 쓰려면 아래에 넣으세요.</div>')
    disk = ('<div class="info" style="margin-bottom:14px">💾 카카오 키가 <b>이 맥에 저장</b>돼 있습니다. '
            '<form method="POST" action="/forget_kakao" style="display:inline;margin:0">'
            '<button class="btn sec" type="submit">저장된 카카오 키 삭제</button></form></div>'
            if kakao.has_saved_key() else "")
    return f"""
<h2 style="font-size:19px;margin:0 0 10px">🗺️ 카카오 자동수집 키 <span class="hint" style="font-weight:400">(경쟁분석)</span></h2>
{state}{disk}
<div class="info" style="margin-bottom:16px">
  1) <b>https://developers.kakao.com</b> → 로그인 → <b>내 애플리케이션</b> 생성/선택 → <b>앱 키 → REST API 키</b> 복사<br>
  2) 아래에 붙여넣고 저장하면 주소만으로 반경 내 동물병원을 자동 수집합니다.
</div>
<form method="POST" action="/save_kakao">
<fieldset><legend>카카오 REST API 키</legend>
  <label>키 붙여넣기 <span class="hint">(가려져 보임 · 저장 시 유효성 검증)</span></label>
  <input type="password" name="kakao_key" autocomplete="off" placeholder="카카오 REST API 키" style="font-family:monospace">
  <label class="chk" style="margin-top:10px"><input type="checkbox" name="remember" value="1" checked> 이 맥에 저장 (재시작해도 자동 로드)</label>
  <div style="margin-top:14px"><button class="btn" type="submit">카카오 키 저장 →</button></div>
</fieldset>
</form>"""


def _perplexity_section():
    """AI 검색 노출 검증(Perplexity Sonar) API 키 입력 섹션."""
    if ai_search.available():
        state = (f'<div class="callout g" style="margin-bottom:14px">✅ <b>AI 검색 검증 사용 가능</b> · '
                 f'{esc(ai_search.status_text())}</div>')
    else:
        state = (f'<div class="note" style="margin-bottom:14px">🤖 <b>Perplexity 키가 없습니다.</b> '
                 'AI(앤서엔진)에 "지역 동물병원 추천"을 실제로 질의해 우리 병원이 추천에 나오는지 '
                 '검증하려면 아래에 넣으세요.</div>')
    disk = ('<div class="info" style="margin-bottom:14px">💾 Perplexity 키가 <b>이 맥에 저장</b>돼 있습니다. '
            '<form method="POST" action="/forget_perplexity" style="display:inline;margin:0">'
            '<button class="btn sec" type="submit">저장된 Perplexity 키 삭제</button></form></div>'
            if ai_search.has_saved_key() else "")
    return f"""
<h2 style="font-size:19px;margin:0 0 10px">🤖 AI 검색 검증 키 <span class="hint" style="font-weight:400">(AEO·GEO)</span></h2>
{state}{disk}
<div class="info" style="margin-bottom:16px">
  1) <b>https://www.perplexity.ai/settings/api</b> → 로그인 → <b>API 키 생성</b> 복사<br>
  2) 붙여넣고 저장하면 "○○구 24시 동물병원 추천" 등을 AI에 직접 질의해 <b>노출·인용(귀속)</b>을 측정합니다.
</div>
<form method="POST" action="/save_perplexity">
<fieldset><legend>Perplexity API 키</legend>
  <label>키 붙여넣기 <span class="hint">(가려져 보임 · pplx-…)</span></label>
  <input type="password" name="perplexity_key" autocomplete="off" placeholder="pplx-..." style="font-family:monospace">
  <label class="chk" style="margin-top:10px"><input type="checkbox" name="remember" value="1" checked> 이 맥에 저장 (재시작해도 자동 로드)</label>
  <div style="margin-top:14px"><button class="btn" type="submit">Perplexity 키 저장 →</button></div>
</fieldset>
</form>
<div class="note" style="margin-top:12px">저장 위치 <code>~/.config/petamos/perplexity_key</code>(0600). 배포 시엔 환경변수 <code>PERPLEXITY_API_KEY</code> 권장.</div>"""


def _num(form, key):
    v = (form.get(key, [""])[0] or "").strip()
    if v == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _str(form, key):
    v = (form.get(key, [""])[0] or "").strip()
    return v or None


def parse_clinics(text):
    clinics = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.replace("\t", ",").split(",")]
        name = parts[0] if parts else ""
        cat = parts[1] if len(parts) > 1 and parts[1] else "동물병원"
        dist = None
        for p in reversed(parts):
            digits = "".join(ch for ch in p if ch.isdigit())
            if digits:
                dist = int(digits)
                break
        if name and dist is not None:
            clinics.append({"name": name, "category": cat, "distance_m": dist})
    return clinics


def parse_rival_marketing(text):
    """경쟁사 마케팅 현황 입력 파싱.

    한 줄에 하나: 병원명, 홈페이지, 블로그, 인스타[, 플레이스리뷰수]
    각 채널값: 운영/없음/미확인 (별칭 o·x·?·y·n 허용). 생략 시 미확인.
    """
    rows = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.replace("\t", ",").split(",")]
        name = parts[0] if parts else ""
        if not name:
            continue
        rec = {"name": name}
        for i, key in enumerate(("homepage", "blog", "instagram"), start=1):
            if len(parts) > i and parts[i]:
                rec[key] = parts[i]
        # 마지막에 숫자가 있으면 플레이스 리뷰수로 해석
        if len(parts) > 4:
            digits = "".join(ch for ch in parts[4] if ch.isdigit())
            if digits:
                rec["place_review"] = int(digits)
        rows.append(rec)
    return rows


def build_config(form):
    name = _str(form, "name")
    if not name:
        raise ValueError("병원명은 필수입니다.")
    clinic = {"name": name, "slug": name, "tier": _num(form, "tier") or 2}
    for k in ("address", "phone", "date"):
        v = _str(form, k)
        if v:
            clinic[k] = v

    ta = {}
    for k in ("households", "clinics_in_region", "registered_pets", "region_clinics",
              "population", "nearest_station_m", "monthly_sales_manwon", "daily_footfall"):
        v = _num(form, k)
        if v is not None:
            ta[k] = v
    rl = _str(form, "region_label")   # PDF에서 추출한 상권영역(숨김 필드로 유지)
    if rl:
        ta["region_label"] = rl
    st = _str(form, "nearest_station")
    if st:
        ta["nearest_station"] = st
    at = _str(form, "area_type")
    if at:
        ta["area_type"] = at
    if form.get("parking"):
        ta["parking"] = True
    if form.get("apartment_dense"):
        ta["apartment_dense"] = True

    comp = {"clinics": parse_clinics(_str(form, "clinics") or "")}
    # 경쟁사 마케팅 현황: 구조화 3행(드롭다운) 우선, 없으면 고급 textarea
    rm = []
    for i in (1, 2, 3):
        nm = _str(form, f"rm_name_{i}")
        if not nm:
            continue
        rec = {"name": nm,
               "homepage": _str(form, f"rm_home_{i}") or "미확인",
               "blog": _str(form, f"rm_blog_{i}") or "미확인",
               "instagram": _str(form, f"rm_insta_{i}") or "미확인"}
        rv = _num(form, f"rm_review_{i}")
        if rv is not None:
            rec["place_review"] = rv
        sp = _str(form, f"rm_spec_{i}")
        if sp:
            rec["specialty"] = [s.strip() for s in sp.replace("·", ",").split(",") if s.strip()]
        rm.append(rec)
    if not rm:
        rm = parse_rival_marketing(_str(form, "rival_marketing") or "")
    if rm:
        comp["rival_marketing"] = rm

    data = {"clinic": clinic, "trade_area": ta, "competition": comp}

    for key, field in (("marketing", "marketing_json"), ("review", "review_json")):
        raw = _str(form, field)
        if raw:
            try:
                data[key] = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"{field} JSON 파싱 오류: {e}")
    return data


def _backup_input(slug, keep=10):
    """덮어쓰기 직전, 기존 입력 JSON을 inputs/_backups/<slug>__<타임스탬프>.json 로 복사.
       병원(slug)별로 최근 keep개만 유지 → 여러 병원이 있어도 서로 간섭 없음.
       신규 병원(기존본 없음)이면 아무 것도 하지 않음."""
    if not slug or "/" in slug or ".." in slug:
        return
    src = os.path.join(INPUTS, f"{slug}.json")
    if not os.path.isfile(src):
        return
    try:
        import shutil, datetime
        os.makedirs(BACKUPS, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(src, os.path.join(BACKUPS, f"{slug}__{ts}.json"))
        # 이 병원 백업만 골라 최근 keep개 초과분 삭제(파일명 시각 = 사전순 = 시간순)
        mine = sorted(f for f in os.listdir(BACKUPS)
                      if f.startswith(f"{slug}__") and f.endswith(".json"))
        for old in mine[:-keep]:
            try:
                os.remove(os.path.join(BACKUPS, old))
            except Exception:
                pass
    except Exception:
        pass   # 백업 실패가 저장·생성을 막지 않게(안전장치는 부가 기능)


def save_and_generate(data):
    name = data["clinic"].get("slug") or data["clinic"]["name"]
    os.makedirs(INPUTS, exist_ok=True)
    _backup_input(name)   # ★ 덮어쓰기 전 직전 버전 백업(유실 시 되살리기용)
    with open(os.path.join(INPUTS, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    generate.run(os.path.join(INPUTS, f"{name}.json"))
    return name


def _cleanup_slug(slug):
    """이름 변경 시 옛 slug의 입력 JSON·출력 폴더 정리(경로 조작 차단)."""
    if not slug or "/" in slug or ".." in slug:
        return
    jf = os.path.join(INPUTS, f"{slug}.json")
    if os.path.isfile(jf):
        os.remove(jf)
    out = os.path.normpath(os.path.join(OUTPUTS, slug))
    if out.startswith(OUTPUTS) and os.path.isdir(out):
        import shutil
        shutil.rmtree(out)


def _apply_form_uploads(data, form, files):
    """폼의 업로드·자동수집(상권PDF·카카오·AI초안·EMR)을 data에 반영. /generate·/update 공용."""
    # ① 상권: 간단분석 PDF → trade_area 자동
    pdfs = files.get("sangkwon_pdf")
    if pdfs and pdfs[0][1]:
        ta_auto = ingest.build_trade_area(pdfs[0][1])
        tgt = data.setdefault("trade_area", {})
        for k in ("monthly_sales_manwon", "daily_footfall", "clinics_in_region",
                  "registered_pets", "region_label", "households", "population"):
            if ta_auto.get(k) is not None:
                tgt[k] = ta_auto[k]
    # ② 경쟁: 카카오 자동수집(주소 + tier 반경)
    if form.get("auto_competition") and kakao.available():
        addr = data["clinic"].get("address")
        if not addr:
            raise ValueError("카카오 자동수집엔 병원 주소가 필요합니다(기본정보에 주소 입력).")
        tier_n = int(data["clinic"].get("tier", 2))
        radius = policy.RADIUS_TIER1_M if tier_n == 1 else policy.RADIUS_TIER2_M
        res = kakao.collect_competition(addr, radius, self_name=data["clinic"].get("name", ""))
        if res.get("ok"):
            comp = data.setdefault("competition", {})
            comp["clinics"] = res["clinics"]
            comp["_collect"] = {"total": res["total"], "radius_m": res["radius_m"],
                                "capped": res["capped"]}
        elif not data.get("competition", {}).get("clinics"):
            raise ValueError(f"카카오 자동수집 실패: {res.get('error','주소 확인')}")
    # ③④ 마케팅·리뷰: 원재료(링크·캡처)가 있으면 AI 초안 자동
    #   ★ 기존 채널과 '병합'(같은 채널만 교체, 나머지 유지) — 이번에 일부 채널만 다시 넣어도
    #     기존 분석이 사라지지 않게. (수정·보완에서 인스타만 추가 시 홈피·블로그 등 보존)
    if _has_raw_material(form, files):
        mk, rv, _ = _draft_marketing_review(form, files, data["clinic"])
        if mk["channels"]:
            ex = data.get("marketing", {}).get("channels", [])
            data["marketing"] = {"channels": _merge_channels(ex, mk["channels"])}
        if rv.get("channels"):
            # 리뷰 누적 병합 — 네이버/구글을 나눠 넣어도 기존 분석에 더해진다(통째 교체 X).
            data["review"] = _merge_reviews(data.get("review", {}), rv)
        # 종합 패스: 병합된 '전체 채널'을 다시 읽어 채널 교차 공통 강점/과제로 종합
        mkch = data.get("marketing", {}).get("channels", [])
        if mkch:
            syn = ai_draft.synthesize_marketing(data["clinic"], mkch)
            if syn:
                data["marketing"]["synthesis"] = syn
            # 진료 특화 자동 추출 — 마케팅 콘텐츠에서 '내세우는 특화'와 누락·제안
            spec = ai_draft.extract_specialties(data["clinic"], mkch)
            if spec and spec.get("specialties"):
                data["marketing"]["specialty_analysis"] = spec
                # 05 강점의 '진료 역량' 축 재료로도 사용(수동 입력 없으면 자동 채움)
                if not data["clinic"].get("specialties"):
                    data["clinic"]["specialties"] = [
                        {"title": s["name"], "body": s.get("evidence", ""), "emphasis": s.get("emphasis", "")}
                        for s in spec["specialties"]]
        # 리뷰 종합 패스: 여러 리뷰 채널 → 고객이 말하는 공통 강점/개선점
        if data.get("review", {}).get("channels"):
            rsyn = ai_draft.synthesize_reviews(data["clinic"], data["review"])
            if rsyn:
                data["review"]["synthesis"] = rsyn
    # ⑤ 진료데이터(EMR): 업로드 즉시 익명화 → 집계만 저장(원본 행·PII 미저장)
    emr_files = files.get("emr_file")
    if emr_files and emr_files[0][1]:
        fname, fbytes = emr_files[0][0], emr_files[0][1]
        res = emr.run(fbytes, fname, data["clinic"]["name"])
        data["emr"] = {k: res[k] for k in
                       ("column_mapping", "mask_report", "analysis", "roadmap", "n_rows")}
    # ⑥ 경쟁사 실제 분석: TOP3 경쟁사 URL 자동수집 + 캡처 비전 판독 → rival_marketing 보강
    _analyze_rivals(form, files, data)
    return data


def _insta_num(s, suffix=""):
    """'686M'·'1,234'·'1.2만' → 정수."""
    s = (s or "").replace(",", "").strip()
    try:
        val = float(s)
    except ValueError:
        return None
    mult = {"m": 1_000_000, "k": 1_000, "만": 10_000, "천": 1_000}.get((suffix or "").lower(), 1)
    return int(val * mult)


def _parse_insta_meta(text):
    """인스타 자동수집 텍스트(OG 설명)에서 팔로워·게시물 수 추출. 로그인 벽이면 {}."""
    out = {}
    m = re.search(r"팔로워\s*([\d,.]+)\s*([MmKk만천]?)\s*명", text)
    if m:
        v = _insta_num(m.group(1), m.group(2))
        if v:
            out["insta_followers"] = v
    m = re.search(r"게시물\s*([\d,.]+)\s*([MmKk만천]?)\s*개", text)
    if m:
        v = _insta_num(m.group(1), m.group(2))
        if v:
            out["insta_posts"] = v
    return out


def _analyze_rivals(form, files, data):
    """TOP3 경쟁사 URL 자동수집 + 캡처 비전 판독 → rival_marketing 보강.
    수동 드롭다운이 '미확인'인 채널만 자동값으로 채움(수동 우선). 리뷰수·별점·키워드도 추출."""
    comp = data.setdefault("competition", {})
    rms = comp.get("rival_marketing") or []
    for i in (1, 2, 3):
        name = _str(form, f"rm_name_{i}")
        if not name:
            continue
        rec = next((r for r in rms if r.get("name") == name), None)
        if rec is None:
            rec = {"name": name}
            rms.append(rec)
        log = []   # 이 경쟁사에 실제로 실행된 자동 분석 내역(확인용)
        # ① 홈피·인스타 URL 자동수집(공개 메타) + 홈피 텍스트에서 특화 자동 추출
        for key, url_field, klab in (("homepage", f"rm_home_url_{i}", "홈페이지"),
                                     ("instagram", f"rm_insta_url_{i}", "인스타")):
            url = _str(form, url_field)
            if url:
                try:
                    r = collectors.collect(key, url)
                    if r and "실패" not in r:
                        if rec.get(key, "미확인") == "미확인":
                            rec[key] = "운영"
                        log.append(f"{klab} URL 수집 성공")
                        # 홈피 텍스트에서 진료 특화(치과·심장 등) 자동 감지
                        if key == "homepage" and not rec.get("specialty"):
                            specs = sorted(scoring._match_specs(r))
                            if specs:
                                rec["specialty"] = specs
                                rec["_spec_src"] = "홈피 판독"
                                log.append(f"홈피에서 특화 감지({', '.join(specs)})")
                        # 인스타 OG 메타에서 팔로워·게시물 수 추출(되는 계정만)
                        if key == "instagram":
                            im = _parse_insta_meta(r)
                            if im.get("insta_followers") and not rec.get("insta_followers"):
                                rec["insta_followers"] = im["insta_followers"]
                            if im.get("insta_posts") and not rec.get("insta_posts"):
                                rec["insta_posts"] = im["insta_posts"]
                            if im:
                                log.append(f"인스타 팔로워/게시물 추출({im})")
                    else:
                        log.append(f"{klab} URL 수집 실패")
                except Exception:
                    log.append(f"{klab} URL 수집 실패")
        # ② 캡처 비전 판독(블로그·리뷰·플레이스)
        caps = files.get(f"rm_cap_{i}", [])
        if caps:
            if not ai_draft.available():
                log.append(f"캡처 {len(caps)}장 — AI 키 없어 판독 못함")
            else:
                imgs = [(b, ai_draft.guess_media_type(fn, fct)) for fn, b, fct in caps]
                ext = ai_draft.extract_rival_from_images(name, imgs)
                if ext:
                    for ch in ("homepage", "blog", "instagram"):
                        v = ext.get(ch)
                        if v and v != "미확인" and rec.get(ch, "미확인") == "미확인":
                            rec[ch] = v
                    if ext.get("review_count") and not rec.get("place_review"):
                        rec["place_review"] = ext["review_count"]
                    if ext.get("rating") and not rec.get("place_rating"):
                        rec["place_rating"] = ext["rating"]
                    if ext.get("insta_followers") and not rec.get("insta_followers"):
                        rec["insta_followers"] = ext["insta_followers"]
                    if ext.get("insta_posts") and not rec.get("insta_posts"):
                        rec["insta_posts"] = ext["insta_posts"]
                    if ext.get("specialties") and not rec.get("specialty"):
                        rec["specialty"] = ext["specialties"]
                        rec["_spec_src"] = "캡처 판독"
                    if ext.get("praise"):
                        rec["praise"] = ext["praise"]
                    if ext.get("complaint"):
                        rec["complaint"] = ext["complaint"]
                    log.append(f"캡처 {len(caps)}장 비전 판독 성공")
                else:
                    log.append(f"캡처 {len(caps)}장 판독 실패")
        if log:
            rec["_analyzed"] = log
    if rms:
        comp["rival_marketing"] = rms
    return data


def _json_to_prefill(data):
    """저장된 입력 JSON → new_form_page 프리필(플랫 폼 필드). 수정·보완 모드용."""
    c = data.get("clinic", {})
    ta = data.get("trade_area", {})
    comp = data.get("competition", {})
    pf = {}
    for k in ("name", "address", "phone", "date"):
        if c.get(k) is not None:
            pf[k] = c[k]
    pf["tier"] = str(c.get("tier", 2))
    for k in ("households", "clinics_in_region", "registered_pets", "nearest_station",
              "nearest_station_m", "area_type", "monthly_sales_manwon", "daily_footfall"):
        if ta.get(k) is not None:
            pf[k] = ta[k]
    if ta.get("parking"):
        pf["parking"] = "1"
    if ta.get("apartment_dense"):
        pf["apartment_dense"] = "1"
    lines = []
    for cl in comp.get("clinics", []):
        if cl.get("name") and cl.get("distance_m") is not None:
            cat = (cl.get("category") or "동물병원").split(">")[-1].strip().replace(",", " ") or "동물병원"
            lines.append(f"{cl['name']}, {cat}, {cl['distance_m']}")
    if lines:
        pf["clinics"] = "\n".join(lines)
    for idx, r in enumerate(comp.get("rival_marketing", [])[:3], start=1):
        pf[f"rm_name_{idx}"] = r.get("name", "")
        pf[f"rm_home_{idx}"] = r.get("homepage", "미확인")
        pf[f"rm_blog_{idx}"] = r.get("blog", "미확인")
        pf[f"rm_insta_{idx}"] = r.get("instagram", "미확인")
        if r.get("place_review") is not None:
            pf[f"rm_review_{idx}"] = r["place_review"]
        sp = r.get("specialty")
        if sp:
            pf[f"rm_spec_{idx}"] = ", ".join(sp) if isinstance(sp, (list, tuple)) else str(sp)
    if data.get("marketing"):
        pf["marketing_json"] = json.dumps(data["marketing"], ensure_ascii=False, indent=2)
    if data.get("review"):
        pf["review_json"] = json.dumps(data["review"], ensure_ascii=False, indent=2)
    # EMR 있음 표시(폼엔 못 넣지만 유지됨을 배너로 안내)
    if data.get("emr"):
        pf["_has_emr"] = "1"
    return pf


def _mp_param(v):
    """get_param 결과 정규화 — RFC2231 인코딩(비ASCII 파일명)은 (charset,lang,val) 튜플로 옴."""
    if v is None:
        return None
    if isinstance(v, tuple):
        try:
            return email.utils.collapse_rfc2231_value(v)
        except Exception:
            return v[2] if len(v) == 3 else str(v)
    return str(v)


def _parse_multipart(ctype, body):
    """multipart/form-data 파싱(stdlib email). 반환: (fields{name:[str]}, files{name:[(filename,bytes,ctype)]})."""
    fields, files = {}, {}
    try:
        header = b"Content-Type: " + ctype.encode("utf-8") + b"\r\n\r\n"
        msg = email.message_from_bytes(header + body)
        if not msg.is_multipart():
            return fields, files
        for part in msg.get_payload():
            cd = str(part.get("Content-Disposition", "") or "")   # Header 객체 → str
            if "form-data" not in cd:
                continue
            name = _mp_param(part.get_param("name", header="content-disposition"))
            filename = _mp_param(part.get_param("filename", header="content-disposition"))
            payload = part.get_payload(decode=True) or b""
            if filename:
                if payload:  # 빈 파일 입력은 건너뜀
                    files.setdefault(str(name), []).append((str(filename), payload, part.get_content_type()))
            elif name is not None:
                fields.setdefault(str(name), []).append(payload.decode("utf-8", "replace"))
    except Exception as e:
        # 파싱 실패해도 서버가 죽지 않게(빈 응답 방지) — 상위에서 안내 처리
        print(f"[multipart parse error] {type(e).__name__}: {e}")
    return fields, files


def _load_saved(slug):
    """저장된 입력 JSON을 안전하게 로드(없으면 빈 dict)."""
    try:
        p = os.path.join(INPUTS, f"{slug}.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _existing_channels(form, field):
    """폼의 marketing_json/review_json 텍스트에서 기존 채널 목록을 안전 파싱."""
    try:
        obj = json.loads(_str(form, field) or "{}")
        return obj.get("channels", []) if isinstance(obj, dict) else []
    except Exception:
        return []


# 채널 표시/정렬 순서(병합 후 재정렬용)
_CH_ORDER = ["homepage", "blog", "instagram", "naverplace", "kakao", "map", "tmap", "aeo_geo",
             "naver", "google", "kakaomap"]


def _merge_channels(old, new):
    """기존(old) 채널에 새(new) 채널을 병합. 같은 채널은 새 것으로 교체, 없던 채널은 추가.
       채널 식별키는 type(마케팅) 우선, 없으면 name(리뷰 등)."""
    by_key = {}
    order = []
    for c in list(old) + list(new):     # new가 뒤 → 같은 키면 new가 최종
        k = c.get("type") or c.get("name")
        if k not in by_key:
            order.append(k)
        by_key[k] = c
    # 표준 순서 우선, 그 외(신규/비표준)는 등장 순서 유지
    ordered = [k for k in _CH_ORDER if k in by_key] + [k for k in order if k not in _CH_ORDER]
    return [by_key[k] for k in ordered]


def _merge_reviews(old, new):
    """리뷰 누적 병합 — 출처(네이버·구글 등)를 여러 번 나눠 넣어도 합쳐지게.
       채널은 이름 기준 교체/추가, 키워드·인용·발견·개선안은 중복 제거 후 합침."""
    old = old or {}
    new = new or {}
    if not old.get("channels"):
        return new
    if not new.get("channels"):
        return old

    def _uniq(seq, key):
        seen, out = set(), []
        for x in seq:
            k = key(x)
            if k and k not in seen:
                seen.add(k)
                out.append(x)
        return out

    merged = {"channels": _merge_channels(old.get("channels", []), new.get("channels", []))}
    for kk in ("praise_keywords", "complaint_keywords"):
        merged[kk] = _uniq(list(old.get(kk, [])) + list(new.get(kk, [])),
                           lambda k: (k.get("keyword") if isinstance(k, dict) else k))
    merged["quotes"] = _uniq(list(old.get("quotes", [])) + list(new.get("quotes", [])),
                             lambda q: (q.get("text", "") or "")[:40])
    for kk in ("findings", "actions"):
        merged[kk] = _uniq(list(old.get(kk, [])) + list(new.get(kk, [])),
                           lambda x: x.get("title", ""))
    return merged


def _draft_marketing_review(form, files, clinic):
    """폼의 원재료(링크·캡처·리뷰)로 ③마케팅·④리뷰 초안 생성. 반환 (marketing, review, collect_log)."""
    lab = ai_draft.CHANNEL_LABELS
    marketing_channels, collect_log = [], []
    for ct in lab:
        url = _str(form, f"url_{ct}")
        memo = _str(form, f"raw_{ct}") or ""
        caps = files.get(f"cap_{ct}", [])
        try:
            # ① URL 자동수집(링크 채널) — 텍스트 컨텍스트로 확보
            url_text = ""
            if url and ct in collectors.LINK_CHANNELS:
                url_text = collectors.collect(ct, url)
                collect_log.append((f"{lab.get(ct, ct)} URL", "실패" not in url_text))
            # ② 캡처가 있으면 비전 판독(+URL 수집 결과·메모를 컨텍스트로 결합 → 더 정확)
            ch = None
            if caps:
                imgs = [(b, ai_draft.guess_media_type(fn, fct)) for fn, b, fct in caps]
                extra = "\n".join(x for x in [
                    ("[URL 자동수집 결과]\n" + url_text) if url_text else "",
                    ("[담당자 메모] " + memo) if memo else ""] if x)
                ch = ai_draft.draft_channel_from_images(clinic, ct, imgs, extra_memo=extra)
                collect_log.append((f"{lab.get(ct, ct)} 캡처{len(caps)}장" + ("+URL" if url_text else ""), True))
            # ③ 캡처 없으면 URL·메모 텍스트만으로
            else:
                parts = []
                if url_text:
                    parts.append(url_text)
                if memo:
                    parts.append("[담당자 메모] " + memo)
                if parts:
                    ch = ai_draft.draft_channel(clinic, ct, "\n".join(parts))
            if ch is not None:
                if url:                 # 리포트에서 채널 제목 아래 링크로 노출
                    ch["url"] = url
                marketing_channels.append(ch)
        except Exception as e:
            # 한 채널 실패가 전체 생성을 막지 않게(다음 채널 계속)
            print(f"[channel draft error] {ct}: {type(e).__name__}: {e}")
            collect_log.append((f"{lab.get(ct, ct)} 분석 실패", False))
    marketing = {"channels": marketing_channels}
    rev_caps = files.get("cap_reviews", [])
    raw_reviews = _str(form, "raw_reviews") or ""
    if rev_caps:
        imgs = [(b, ai_draft.guess_media_type(fn, fct)) for fn, b, fct in rev_caps]
        review = ai_draft.draft_review_from_images(clinic, imgs, extra_memo=raw_reviews)
        collect_log.append((f"리뷰 캡처{len(rev_caps)}장", True))
    elif raw_reviews:
        review = ai_draft.draft_review(clinic, raw_reviews)
    else:
        review = {"channels": []}
    return marketing, review, collect_log


def _has_raw_material(form, files):
    """폼에 AI 초안용 원재료(URL·캡처·리뷰)가 있는지."""
    for ct in ai_draft.CHANNEL_LABELS:
        if _str(form, f"url_{ct}") or _str(form, f"raw_{ct}") or files.get(f"cap_{ct}"):
            return True
    return bool(_str(form, "raw_reviews") or files.get("cap_reviews"))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _redirect(self, loc):
        self.send_response(303)
        self.send_header("Location", loc)
        self.end_headers()

    def _cookie(self, name):
        for part in self.headers.get("Cookie", "").split(";"):
            part = part.strip()
            if part.startswith(name + "="):
                return part[len(name) + 1:]
        return ""

    def _admin_authed(self):
        pw = load_admin_pw()
        if not pw:
            return True  # 비밀번호 미설정 → 개방(어드민에 경고 배너 표시)
        return self._cookie("padmin") == admin_token(pw)

    def _cookie_redirect(self, loc, cookie):
        self.send_response(303)
        self.send_header("Location", loc)
        self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def log_message(self, *a):
        pass  # 조용히

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split("?")[0])
        if path == "/":
            return self._send(200, home_page())
        if path == "/review":
            return self._send(200, review_page())
        if path == "/entity":
            return self._send(200, entity_page())
        if path == "/entity_code":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(200, entity_code_page((qs.get("slug") or [""])[0]))
        if path == "/new":
            return self._send(200, new_form_page())
        if path == "/preview":
            return self._send(200, preview_page())
        if path == "/auto":
            return self._send(200, auto_form_page())
        if path == "/demo_progress":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            slug = (qs.get("slug") or [""])[0]
            name = (qs.get("name") or ["이 병원"])[0]
            addr = (qs.get("addr") or [""])[0]
            if not (slug and "/" not in slug and ".." not in slug):
                return self._send(404, shell("없음", '<p>잘못된 요청입니다. <a href="/landing">처음으로</a></p>'))
            return self._send(200, demo_progress_page(slug, name, addr))
        if path == "/demo_status":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            slug = (qs.get("slug") or [""])[0]
            if not (slug and "/" not in slug and ".." not in slug):
                return self._send(400, json.dumps({"status": "없음"}),
                                  "application/json; charset=utf-8")
            return self._send(200, json.dumps(demo_status(slug)),
                              "application/json; charset=utf-8")
        if path in ("/landing", "/home", "/site"):
            _lp = os.path.join(ROOT, "site", "index.html")
            if os.path.isfile(_lp):
                with open(_lp, "rb") as f:
                    return self._send(200, f.read())
            return self._send(404, shell("없음", "<p>랜딩 페이지 파일이 없습니다.</p>"))
        if path == "/edit":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            slug = (qs.get("slug") or [""])[0]
            p = os.path.join(INPUTS, f"{slug}.json")
            if not (slug and "/" not in slug and ".." not in slug and os.path.isfile(p)):
                return self._send(404, shell("없음", '<p>병원을 찾을 수 없습니다. <a href="/">홈으로</a></p>'))
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            return self._send(200, new_form_page(_json_to_prefill(d), edit_slug=slug))
        if path == "/ai":
            return self._send(200, ai_form_page())
        if path == "/settings":
            return self._send(200, settings_page())
        if path in ("/admin", "/inquiries"):
            if not self._admin_authed():
                return self._send(200, admin_login_page())
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(200, admin_page(q=(qs.get("q") or [""])[0],
                                              status_filter=(qs.get("status") or ["all"])[0]))
        if path == "/admin_view":
            if not self._admin_authed():
                return self._send(200, admin_login_page())
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(200, admin_detail_page((qs.get("ref") or [""])[0]))
        if path == "/admin_logout":
            return self._cookie_redirect("/admin", "padmin=; Path=/; Max-Age=0")
        if path == "/admin_export.csv":
            if not self._admin_authed():
                return self._send(200, admin_login_page())
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = (qs.get("q") or [""])[0]
            sf = (qs.get("status") or ["all"])[0]
            rows = [r for r in load_inquiries()
                    if (sf in ("all", "") or r.get("status", "신규") == sf) and _match(r, q)]
            data = inquiries_csv(rows)
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=inquiries.csv")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if path.startswith("/outputs/"):
            return self._serve_static(path[len("/outputs/"):])
        return self._send(404, shell("404", '<p>페이지를 찾을 수 없습니다. <a href="/">홈으로</a></p>'))

    def _serve_static(self, rel):
        rel = rel.lstrip("/")
        full = os.path.normpath(os.path.join(OUTPUTS, rel))
        if not full.startswith(OUTPUTS) or not os.path.isfile(full):
            return self._send(404, shell("404", '<p>리포트가 없습니다. <a href="/">홈으로</a></p>'))
        ctype = "text/html; charset=utf-8" if full.endswith(".html") else "application/octet-stream"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        files = {}
        if ctype.startswith("multipart/form-data"):
            form, files = _parse_multipart(ctype, raw)
        else:
            form = urllib.parse.parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
        path = self.path.split("?")[0]
        try:
            if path == "/auto_generate":
                name = _str(form, "name") or "무명 병원"
                address = _str(form, "address")
                if not address:
                    return self._send(200, auto_form_page("주소를 입력하세요."))
                try:
                    tier = int(_str(form, "tier") or "2")
                except ValueError:
                    tier = 2
                deep = _str(form, "deep") == "1"
                cfg = autopilot.build_config_auto(name, address, tier=tier, deep=deep,
                                                  date=time.strftime("%Y-%m-%d"))
                slug = cfg["clinic"]["slug"]
                _backup_input(slug)
                with open(os.path.join(INPUTS, f"{slug}.json"), "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                generate.run(os.path.join(INPUTS, f"{slug}.json"))
                return self._redirect(f"/outputs/{urllib.parse.quote(slug)}/index.html")
            if path == "/demo_run":
                # 시연: 주소 → 하이브리드 즉시 or 실시간 정밀 진단 시작. JSON 응답.
                try:
                    if ctype.startswith("application/json"):
                        p = json.loads(raw.decode("utf-8", "replace") or "{}")
                    else:
                        p = {k: (v[0] if v else "") for k, v in form.items()}
                    name = (p.get("name") or "이 병원").strip()
                    address = (p.get("address") or "").strip()
                    fresh = str(p.get("fresh", "")) in ("1", "true", "True")
                    try:
                        tier = int(str(p.get("tier") or "2"))
                    except ValueError:
                        tier = 2
                    if not address:
                        return self._send(400, json.dumps({"ok": False, "error": "주소를 입력하세요."}),
                                          "application/json; charset=utf-8")
                    slug, done = resolve_demo_slug(name, address, fresh=fresh)
                    if not done:
                        with _DEMO_LOCK:
                            running = _DEMO.get(slug, {}).get("status") == "진단중"
                        if not running:
                            threading.Thread(target=run_demo_bg, args=(slug, name, address, tier),
                                             daemon=True).start()
                    return self._send(200, json.dumps({"ok": True, "slug": slug, "done": done}),
                                      "application/json; charset=utf-8")
                except Exception as e:
                    return self._send(400, json.dumps({"ok": False, "error": str(e)}),
                                      "application/json; charset=utf-8")
            if path == "/inquiry":
                # 랜딩 상담 신청(fetch JSON 또는 폼 인코딩) → 접수함 저장 → JSON 응답
                try:
                    if ctype.startswith("application/json"):
                        payload = json.loads(raw.decode("utf-8", "replace") or "{}")
                    else:
                        payload = {k: (v[0] if v else "") for k, v in form.items()}
                    ref = save_inquiry(payload)
                    return self._send(200, json.dumps({"ok": True, "ref": ref}),
                                      "application/json; charset=utf-8")
                except Exception as e:
                    return self._send(400, json.dumps({"ok": False, "error": str(e)}),
                                      "application/json; charset=utf-8")
            if path == "/admin_login":
                pw = load_admin_pw()
                if pw and _str(form, "pw") == pw:
                    return self._cookie_redirect(
                        "/admin",
                        f"padmin={admin_token(pw)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000")
                return self._send(200, admin_login_page(
                    "비밀번호가 올바르지 않습니다." if pw
                    else "관리자 비밀번호가 설정되어 있지 않습니다. 설정에서 먼저 지정하세요."))
            if path == "/run_diagnosis":
                if not self._admin_authed():
                    return self._redirect("/admin")
                ref = _str(form, "ref")
                if load_inquiry(ref):
                    threading.Thread(target=run_diagnosis_bg, args=(ref,), daemon=True).start()
                return self._redirect(f"/admin_view?ref={urllib.parse.quote(ref)}")
            if path in ("/inquiry_status", "/inquiry_note", "/inquiry_delete"):
                if not self._admin_authed():
                    return self._redirect("/admin")
                ref = _str(form, "ref")
                if path == "/inquiry_status":
                    set_inquiry_status(ref, _str(form, "status") or "신규")
                    if _str(form, "back") == "view":
                        return self._redirect(f"/admin_view?ref={urllib.parse.quote(ref)}")
                    qs = urllib.parse.urlencode({k: v for k, v in
                                                 (("status", _str(form, "sf")), ("q", _str(form, "q")))
                                                 if v and v != "all"})
                    return self._redirect("/admin" + (("?" + qs) if qs else ""))
                if path == "/inquiry_note":
                    set_inquiry_memo(ref, _str(form, "memo"))
                    return self._redirect(f"/admin_view?ref={urllib.parse.quote(ref)}")
                delete_inquiry(ref)   # /inquiry_delete
                return self._redirect("/admin")
            if path == "/save_google":
                gk = _str(form, "google_key").strip()
                if gk:
                    google_places.save_key_to_disk(gk)
                    return self._send(200, settings_page("구글 리뷰 키를 저장했습니다."))
                return self._send(200, settings_page("키를 입력하세요."))
            if path == "/forget_google":
                google_places.forget_saved_key()
                return self._send(200, settings_page("구글 리뷰 키를 삭제했습니다."))
            if path == "/save_admin_pw":
                pw = _str(form, "admin_pw").strip()
                if pw:
                    save_admin_pw(pw)
                    return self._send(200, settings_page("관리자 비밀번호를 저장했습니다."))
                return self._send(200, settings_page("비밀번호를 입력하세요."))
            if path == "/forget_admin_pw":
                forget_admin_pw()
                return self._send(200, settings_page("관리자 비밀번호를 삭제했습니다 — 다시 개방 상태입니다."))
            if path == "/generate":
                data = build_config(form)
                _apply_form_uploads(data, form, files)
                name = save_and_generate(data)
                return self._redirect(f"/outputs/{urllib.parse.quote(name)}/index.html")
            if path == "/update":
                # 수정·보완: 폼으로 다시 만들되, 폼에 없는 기존 데이터(EMR 등)는 유지
                slug = _str(form, "slug")
                p = os.path.join(INPUTS, f"{slug}.json")
                if not (slug and "/" not in slug and ".." not in slug and os.path.isfile(p)):
                    raise ValueError("수정할 병원을 찾을 수 없습니다.")
                with open(p, encoding="utf-8") as f:
                    old = json.load(f)
                data = build_config(form)
                _apply_form_uploads(data, form, files)
                # 새 EMR 파일을 올리지 않았으면 기존 진료데이터(집계) 유지
                if old.get("emr") and "emr" not in data:
                    data["emr"] = old["emr"]
                # 이름을 바꾼 경우: 옛 slug의 입력/출력은 정리(중복 방지)
                new_name = data["clinic"].get("slug") or data["clinic"]["name"]
                name = save_and_generate(data)
                if new_name != slug:
                    _cleanup_slug(slug)
                return self._redirect(f"/outputs/{urllib.parse.quote(name)}/index.html")
            if path == "/collect_competition":
                # 카카오 수집 → 경쟁/의뢰처 분류 → 같은 폼에 프리필해 되돌림(검수 단계)
                if not kakao.available():
                    return self._send(200, settings_page("카카오 키가 없습니다 — 먼저 카카오 키를 설정하세요."))
                name = _str(form, "name") or "무명 병원"
                address = _str(form, "address")
                if not address:
                    return self._send(400, shell("주소 필요",
                        '<div class="note">카카오 수집엔 <b>병원 주소</b>가 필요합니다. 기본정보에 주소를 넣고 다시 시도하세요.</div>'
                        '<a class="btn sec" href="/new">← 입력으로</a>'))
                subject_tier = int(_num(form, "tier") or 2)
                radius = policy.RADIUS_TIER1_M if subject_tier == 1 else policy.RADIUS_TIER2_M
                res = kakao.collect_competition(address, radius, self_name=name)
                if not res.get("ok"):
                    return self._send(400, shell("수집 실패",
                        f'<div class="note">카카오 수집 실패: {esc(res.get("error","주소 확인"))}</div>'
                        '<a class="btn sec" href="/new">← 입력으로</a>'))
                self_core = scoring._norm_name(name)
                rivals, referrals, lines = [], [], []
                for c in res["clinics"]:
                    nm = (c.get("name") or "").strip()
                    # 자기 병원 제외(근거리·상호포함·핵심상호 일치 — 표기만 다른 같은 병원)
                    if not nm or scoring._is_self(nm, c.get("distance_m"), name, self_core):
                        continue
                    dist = c.get("distance_m", 0)
                    cat = ((c.get("category") or "동물병원").split(">")[-1].strip().replace(",", " ")
                           or "동물병원")
                    lines.append(f"{nm}, {cat}, {dist}")
                    ntier = 2 if scoring._is_tier2(nm, c.get("category", "")) else 1
                    (rivals if ntier == subject_tier else referrals).append(nm)
                # 검수 폼 프리필: 사용자가 이미 입력한 값 유지 + 수집 결과 채움
                prefill = {k: (v[0] if v else "") for k, v in form.items()}
                prefill["clinics"] = "\n".join(lines)
                # ★ 첨부한 간단분석 PDF도 지금 처리해 값을 폼에 심는다(왕복에서 PDF 유실 방지)
                pdf_note = ""
                pdfs = files.get("sangkwon_pdf")
                if pdfs and pdfs[0][1]:
                    try:
                        ta_auto = ingest.build_trade_area(pdfs[0][1])
                        for tk in ("monthly_sales_manwon", "daily_footfall", "clinics_in_region",
                                   "registered_pets", "region_label", "region_clinics",
                                   "households", "population"):
                            if ta_auto.get(tk) is not None:
                                prefill[tk] = ta_auto[tk]
                        pdf_note = f" 📄 간단분석 PDF도 처리했습니다({esc(ta_auto.get('region_label',''))}) — 다시 첨부 안 해도 됩니다."
                    except Exception:
                        pdf_note = " ⚠️ PDF 처리 실패 — 생성 화면에서 다시 첨부해 주세요."
                # 경쟁사 마케팅 현황: 가장 가까운 동급 경쟁 TOP 3 이름을 구조화 행에 프리필
                for idx, nm in enumerate(rivals[:3], start=1):
                    prefill[f"rm_name_{idx}"] = nm
                prefill["auto_competition"] = ""   # 검수했으니 재수집 off
                cap = " · 45곳 초과라 가까운 45곳만 수집" if res.get("capped") else ""
                top3 = "·".join(rivals[:3]) if rivals else "없음"
                prefill["_collect_result"] = (
                    f"반경 {res['radius_m']:,}m 내 {res['total']}곳 수집 · "
                    f"동급(경쟁) {len(rivals)}곳 · 의뢰처 {len(referrals)}곳{cap}. "
                    f"아래 ‘② 경쟁’ 목록에서 경쟁이 아닌 병원은 지우고, "
                    f"‘경쟁사 마케팅 현황’에 가장 가까운 경쟁 3곳({esc(top3)})을 프리필했으니 "
                    f"각 채널 운영 여부만 골라 주세요.{pdf_note}")
                return self._send(200, new_form_page(prefill))
            if path == "/regenerate":
                slug = _str(form, "slug")
                p = os.path.join(INPUTS, f"{slug}.json")
                if not os.path.isfile(p):
                    raise ValueError("입력 파일을 찾을 수 없습니다.")
                generate.run(p)
                return self._redirect(f"/outputs/{urllib.parse.quote(slug)}/index.html")
            if path == "/ai_draft":
                clinic = {"name": _str(form, "name") or "무명 병원",
                          "tier": _num(form, "tier") or 2,
                          "address": _str(form, "address") or ""}
                marketing, review, collect_log = _draft_marketing_review(form, files, clinic)
                # 기존 채널(수정·보완 프리필/이전 초안)과 병합 — 같은 채널만 새 것으로 교체, 나머지 유지
                #   (이번에 인스타만 넣어도 기존 홈피·블로그 등 7채널이 사라지지 않게)
                ex_mk = _existing_channels(form, "marketing_json")
                ex_rv = _existing_channels(form, "review_json")
                # hidden이 비어도 수정모드면 저장본에서 기존 채널 복원(유실 방지 이중 안전장치)
                if (not ex_mk) and _str(form, "slug"):
                    saved = _load_saved(_str(form, "slug"))
                    ex_mk = saved.get("marketing", {}).get("channels", [])
                    if not ex_rv:
                        ex_rv = saved.get("review", {}).get("channels", [])
                marketing = {"channels": _merge_channels(ex_mk, marketing["channels"])}
                review = {"channels": _merge_channels(ex_rv, review.get("channels", []))}
                name = clinic["name"]
                collect_note = ""
                if collect_log:
                    collect_note = "자동수집: " + " · ".join(
                        f"{name} {'✅' if ok else '⚠️실패'}" for name, ok in collect_log)
                prefill = {
                    "name": clinic["name"], "address": clinic["address"],
                    "tier": str(clinic["tier"]),
                    "marketing_json": json.dumps(marketing, ensure_ascii=False, indent=2) if marketing["channels"] else "",
                    "review_json": json.dumps(review, ensure_ascii=False, indent=2) if review.get("channels") else "",
                    "_ai_note": ai_draft.status_text(),
                    "_collect_note": collect_note,
                }
                return self._send(200, new_form_page(prefill))
            if path == "/save_key":
                key = _str(form, "api_key")
                if not key:
                    return self._send(200, settings_page("키가 비어 있습니다. 다시 붙여넣어 주세요."))
                os.environ["ANTHROPIC_API_KEY"] = key
                ok, vmsg = ai_draft.validate_key()
                if not ok:
                    os.environ.pop("ANTHROPIC_API_KEY", None)  # 무효 키는 저장하지 않음
                    return self._send(200, settings_page(f"⚠️ 저장 취소 — {vmsg}"))
                if form.get("remember"):
                    ai_draft.save_key_to_disk(key)
                    return self._send(200, settings_page(f"저장됐습니다(이 맥에 보관). {vmsg} ✅"))
                return self._send(200, settings_page(f"저장됐습니다(이번 실행만). {vmsg} ✅"))
            if path == "/forget_key":
                ai_draft.forget_saved_key()
                return self._send(200, settings_page("저장된 키를 삭제했습니다."))
            if path == "/save_kakao":
                kkey = _str(form, "kakao_key")
                if not kkey:
                    return self._send(200, settings_page("카카오 키가 비어 있습니다."))
                os.environ["KAKAO_REST_KEY"] = kkey
                ok, vmsg = kakao.validate_key()
                if not ok:
                    os.environ.pop("KAKAO_REST_KEY", None)
                    return self._send(200, settings_page(f"⚠️ 카카오 저장 취소 — {vmsg}"))
                if form.get("remember"):
                    kakao.save_key_to_disk(kkey)
                    return self._send(200, settings_page(f"카카오 키 저장(이 맥에 보관). {vmsg} ✅"))
                return self._send(200, settings_page(f"카카오 키 저장(이번 실행만). {vmsg} ✅"))
            if path == "/forget_kakao":
                kakao.forget_saved_key()
                return self._send(200, settings_page("저장된 카카오 키를 삭제했습니다."))
            if path == "/save_perplexity":
                pkey = _str(form, "perplexity_key").strip()
                if not pkey:
                    return self._send(200, settings_page("Perplexity 키가 비어 있습니다."))
                if form.get("remember"):
                    ai_search.save_key_to_disk(pkey)
                    return self._send(200, settings_page("Perplexity 키 저장(이 맥에 보관). ✅"))
                os.environ["PERPLEXITY_API_KEY"] = pkey
                return self._send(200, settings_page("Perplexity 키 저장(이번 실행만). ✅"))
            if path == "/forget_perplexity":
                ai_search.forget_saved_key()
                return self._send(200, settings_page("저장된 Perplexity 키를 삭제했습니다."))
            if path == "/entity_subscribe":
                name = _str(form, "name").strip()
                address = _str(form, "address").strip()
                if not name:
                    return self._send(200, entity_page("병원명을 입력하세요."))
                slug = _str(form, "slug").strip() or ("ent_" + re.sub(r"[^0-9A-Za-z가-힣]", "", name)[:20])
                clinic = {"name": name, "slug": slug, "address": address}
                try:
                    disc = autopilot.discover(name, address)
                    known = autopilot.discover_own_urls(name, address, disc) or {}
                except Exception:
                    known = {}
                measure = _str(form, "measure") == "1"
                try:
                    entity_pipeline.start_subscription(slug, clinic, known_urls=known,
                                                       measure_baseline=measure)
                except Exception as e:
                    return self._send(200, entity_page(f"⚠️ 구독 시작 실패 — {type(e).__name__}: {e}"))
                return self._send(200, entity_page(f"'{name}' 구독 시작 — 코드 생성 완료"
                                                   + (" · 기준선 측정 완료" if measure else "")))
            if path == "/entity_refresh":
                slug = _str(form, "slug").strip()
                r = entity_pipeline.refresh(slug)
                if r.get("error"):
                    return self._send(200, entity_page(f"⚠️ {r['error']}"))
                msg = ("코드 변경 감지 — 재심기 필요" if r.get("changed") else "변경 없음(최신 상태)")
                return self._send(200, entity_page(f"최신화 완료: {msg}"))
            if path == "/entity_install":
                slug = _str(form, "slug").strip()
                r = entity_pipeline.mark_installed(slug)
                if isinstance(r, dict) and r.get("error"):
                    return self._send(200, entity_page(f"⚠️ {r['error']}"))
                return self._send(200, entity_page("심기 완료로 표시했습니다."))
            if path == "/entity_verify":
                slug = _str(form, "slug").strip()
                try:
                    r = entity_pipeline.verify(slug)
                except Exception as e:
                    return self._send(200, entity_page(f"⚠️ 사후검증 실패 — {type(e).__name__}: {e}"))
                if isinstance(r, dict) and r.get("error"):
                    return self._send(200, entity_page(f"⚠️ {r['error']}"))
                return self._send(200, entity_page("사후검증 완료 — 심기 전/후 비교가 갱신됐습니다."))
            if path == "/save_sgis":
                ck = _str(form, "sgis_key"); cs = _str(form, "sgis_secret")
                if not (ck and cs):
                    return self._send(200, settings_page("SGIS 서비스ID·보안Key를 모두 넣어 주세요."))
                os.environ["SGIS_KEY"] = ck; os.environ["SGIS_SECRET"] = cs
                ok, vmsg = sgis.validate_key()
                if not ok:
                    os.environ.pop("SGIS_KEY", None); os.environ.pop("SGIS_SECRET", None)
                    return self._send(200, settings_page(f"⚠️ SGIS 저장 취소 — {vmsg}"))
                if form.get("remember"):
                    sgis.save_key_to_disk(ck, cs)
                    return self._send(200, settings_page(f"SGIS 키 저장(이 맥에 보관). {vmsg} ✅"))
                return self._send(200, settings_page(f"SGIS 키 저장(이번 실행만). {vmsg} ✅"))
            if path == "/forget_sgis":
                sgis.forget_saved_key()
                return self._send(200, settings_page("저장된 SGIS 키를 삭제했습니다."))
            if path == "/delete":
                slug = _str(form, "slug") or ""
                # 안전: 파일명만 허용(경로 조작 차단)
                if slug and "/" not in slug and ".." not in slug:
                    jf = os.path.join(INPUTS, f"{slug}.json")
                    if os.path.isfile(jf):
                        os.remove(jf)
                    out = os.path.normpath(os.path.join(OUTPUTS, slug))
                    if out.startswith(OUTPUTS) and os.path.isdir(out):
                        import shutil
                        shutil.rmtree(out)
                return self._redirect("/")

            if path == "/delete_bulk":
                # 여러 병원 일괄 삭제(어드민 테스트 정리용)
                import shutil
                slugs = form.get("slugs") or []
                if isinstance(slugs, str):
                    slugs = [slugs]
                for slug in slugs:
                    slug = (slug or "").strip()
                    if not slug or "/" in slug or ".." in slug:
                        continue
                    jf = os.path.join(INPUTS, f"{slug}.json")
                    if os.path.isfile(jf):
                        os.remove(jf)
                    out = os.path.normpath(os.path.join(OUTPUTS, slug))
                    if out.startswith(OUTPUTS) and os.path.isdir(out):
                        shutil.rmtree(out)
                return self._redirect("/")
        except Exception as e:
            return self._send(400, shell("오류", f'<div class="note">생성 중 오류: {esc(str(e))}</div>'
                                          f'<a class="btn sec" href="/new">← 다시 입력</a>'))
        return self._send(404, shell("404", '<a href="/">홈</a>'))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8600
    os.makedirs(INPUTS, exist_ok=True)
    os.makedirs(OUTPUTS, exist_ok=True)
    if ai_draft.load_saved_key():   # 저장된 키가 있으면 자동 로드(재시작해도 유지)
        print("  저장된 Anthropic 키 로드됨 (AI 초안 활성화)")
    if kakao.load_saved_key():
        print("  저장된 카카오 키 로드됨 (경쟁 자동수집 활성화)")
    if sgis.load_saved_key():
        print("  저장된 SGIS 키 로드됨 (인구·가구 연동 활성화)")
    if google_places.load_saved_key():
        print("  저장된 Google Places 키 로드됨 (구글 리뷰 연동 활성화)")
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"■ 병원 마케팅 리포트 생성기 웹앱")
    print(f"  → http://localhost:{port}")
    print(f"  (종료: Ctrl+C)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")


if __name__ == "__main__":
    main()
