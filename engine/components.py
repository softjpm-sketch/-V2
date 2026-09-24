# -*- coding: utf-8 -*-
"""
공용 HTML 컴포넌트 빌더 — 작업명세 §2.2 컴포넌트를 함수로 제공.
리포트 생성기(r01~r06)는 이 함수들만 조합해 본문을 만든다.
"""
import re
from .design import esc
from . import scoring


# ── 전문 용어 → 쉬운 말 자동 치환 ──────────────────────────────
# 병원 담당자가 모를 수 있는 마케팅·기술 약어를 누구나 아는 표현으로.
# (의료 용어 MRI·CT·IRIS·PPDH 등은 건드리지 않음)
_JARGON_PARENS = ["OG", "SPA", "NAP", "CTA", "AEO", "GEO", "H1", "DM",
                  "JSON-LD", "SEO", "alt", "tel", "lang", "JS"]
# ASCII 약어는 한글 조사가 바로 붙어도(AEO에서·alt가·lang이) 잡히도록 lookaround 사용.
# 단, LATIN 단어 속(LOGO의 OG 등)은 건드리지 않게 앞뒤 영숫자만 배제. (의료어 MRI·CT는 목록에 없음)
def _acr(a):
    return r"(?<![A-Za-z0-9])" + a + r"(?![A-Za-z0-9])"
_JARGON_RULES = [
    (r"OG\s*이미지", "공유 미리보기 이미지"),
    (_acr("OG"), "공유 미리보기 이미지"),
    (r"원터치\s*tel:?\s*링크", "전화 바로걸기(번호를 눌러 바로 통화)"),
    (r"tel:?\s*링크", "전화 바로걸기 링크"),
    (r"tel:?\s*태그", "전화 바로걸기 설정"),
    (_acr("tel"), "전화 바로걸기"),
    (r"(?<![A-Za-z])sticky(?![A-Za-z])", "고정"),
    (r"meta\s*description", "검색결과 설명문"),
    (r"JSON[-\s]?LD", "검색엔진이 읽는 정보 코드"),
    (r"구조화\s*데이터", "검색엔진이 읽는 정보 코드"),
    (r"대체\s*텍스트", "이미지 설명 텍스트"),
    (r"이미지\s*alt\s*텍스트", "이미지 설명 텍스트"),  # '이미지 alt 텍스트' 통째(중복 방지)
    (r"이미지\s*alt", "이미지 설명 텍스트"),
    (r"alt\s*텍스트", "이미지 설명 텍스트"),
    (_acr("alt"), "이미지 설명 텍스트"),
    (_acr("NAP"), "상호·주소·전화 표기"),
    (_acr("CTA"), "예약·전화 유도 버튼"),
    (_acr("AEO"), "AI 검색 답변"),
    (_acr("GEO"), "생성형 AI 검색"),
    (r"SPA\s*·\s*JS\s*렌더", "화면을 자바스크립트로 그리는 방식"),  # 'SPA·JS 렌더' 통째
    (_acr("SPA"), "화면을 자바스크립트로 그리는 방식"),
    (r"JS\s*렌더", "자바스크립트 렌더"),
    (_acr("H1"), "대표 제목"),
    (_acr("DM"), "다이렉트 메시지"),
    (_acr("lang"), "페이지 언어 설정"),
    (_acr("SEO"), "검색 노출"),
    (_acr("FAQ"), "자주 묻는 질문"),
    (_acr("CRM"), "고객 관리"),
    (r"SSR\s*/\s*프리렌더(?:링)?|SSR", "서버에서 미리 그려 보내기"),
    (r"프리렌더(?:링)?", "미리 그려두기"),
]
_PAREN_RE = re.compile(r"\s*\((?:" + "|".join(re.escape(t) for t in _JARGON_PARENS) + r")\)")
_RULE_RE = [(re.compile(p), r) for p, r in _JARGON_RULES]
# 치환 후 다듬기(조사·중복)
_POST_RE = [(re.compile(p), r) for p, r in [
    (r"방식로", "방식으로"),
    (r"(이미지 설명 텍스트)\s+\1", r"\1"),
    (r"노출\s+노출", "노출"),
]]


def plainify(text):
    """전문 약어를 쉬운 말로 치환. 이미 '(OG)'처럼 괄호로 붙은 약어는 먼저 제거해 중복 방지."""
    if not text:
        return text
    text = _PAREN_RE.sub("", text)          # "주소(NAP)" → "주소"
    for rx, rep in _RULE_RE:
        text = rx.sub(rep, text)
    for rx, rep in _POST_RE:                # 조사·중복 다듬기
        text = rx.sub(rep, text)
    return text


def sechead(num, title, subtitle=None):
    sub = f'<span class="subt">{esc(subtitle)}</span>' if subtitle else ""
    return f'<div class="sechead"><div class="num">{esc(num)}</div><h2>{esc(title)}{sub}</h2></div>'


def section(num, title, inner, subtitle=None):
    return f"<section>{sechead(num, title, subtitle)}{inner}</section>"


def divider(title, subtitle=""):
    """본 리포트(참조 양식)와 '심화 분석'(부가)을 구분하는 구분선."""
    sub = f'<p>{esc(subtitle)}</p>' if subtitle else ""
    return f'<div class="secdiv"><span class="lab">＋ {esc(title)}</span>{sub}</div>'


def snap(items):
    """items: [(수치, 라벨), ...] 4개 권장."""
    ks = "".join(f'<div class="k"><b>{esc(v)}</b><span>{esc(l)}</span></div>' for v, l in items)
    return f'<div class="snap">{ks}</div>'


def callout(text, good=False):
    cls = "callout g" if good else "callout"
    return f'<div class="{cls}">{text}</div>'


def note(text):
    return f'<div class="note">{text}</div>'


def info(text):
    return f'<div class="info">{text}</div>'


def scoregrid(metrics):
    """metrics: [{name, score(0~100), note, weight?}, ...]"""
    rows = []
    for m in metrics:
        sc = m.get("score")
        if sc is None:
            rows.append(
                f'<div class="score"><div class="lab">{esc(m["name"])}</div>'
                f'<div class="track"></div><div class="val">–</div>'
                f'<div class="note">{esc(plainify(m.get("note","")))} · 미측정</div></div>')
            continue
        bar = scoring.bar_class(sc)
        rows.append(
            f'<div class="score"><div class="lab">{esc(m["name"])}</div>'
            f'<div class="track"><div class="bar {bar}" style="width:{min(100,sc)}%"></div></div>'
            f'<div class="val">{sc}</div>'
            f'<div class="note">{esc(plainify(m.get("note","")))}</div></div>')
    return f'<div class="scoregrid">{"".join(rows)}</div>'


def toc(items):
    """채널 이동 목차(클릭 카드). items: [(anchor, title, subtitle), ...]"""
    a = "".join(
        f'<a href="#{esc(anc)}">{title}<span>{esc(sub)}</span></a>'
        for anc, title, sub in items)
    return f'<div class="toc">{a}</div>'


def chan_head(idx, title, url=None, subtitle=None):
    """채널 헤더: 번호 배지 + 제목 + (URL 링크 또는 부제)."""
    if url:
        sub = f'<div class="chan-url"><a href="{esc(url)}" target="_blank" rel="noopener">{esc(url)}</a></div>'
    elif subtitle:
        sub = f'<div class="chan-url" style="color:var(--muted)">{esc(subtitle)}</div>'
    else:
        sub = ""
    return (f'<div class="chan-head"><span class="chan-idx">{esc(idx)}</span>'
            f'<div><h2>{esc(title)}</h2>{sub}</div></div>')


# 세부 진단 카드에서 등급 → (막대클래스, 채움%)
_LEVEL_BAR = {
    "우수": ("s-hi", 88), "매우 우수": ("s-hi", 94), "양호": ("s-hi", 76),
    "보통": ("s-mid", 62), "개선 필요": ("s-lo", 45), "미흡": ("s-lo", 38),
    "확인 필요": ("s-mid", 58), "정체": ("s-lo", 42),
}
_LEVEL_COLOR = {"우수": "good", "매우 우수": "good", "양호": "good",
                "보통": "warn", "확인 필요": "warn",
                "개선 필요": "bad", "미흡": "bad", "정체": "bad"}


def metric_cards(cards):
    """세부 진단 카드(진행바형). cards: [(label, level, note), ...]
       level 등급으로 색·채움·판정문구 자동 결정."""
    out = []
    for label, level, note in cards:
        bar, pct = _LEVEL_BAR.get(level, ("s-mid", 60))
        color = _LEVEL_COLOR.get(level, "warn")
        out.append(
            f'<div class="mc"><div class="lab"><b>{esc(plainify(label))}</b>'
            f'<span class="v" style="color:var(--{color})">{esc(level)}</span></div>'
            f'<div class="mc-bar {bar}"><i style="width:{pct}%"></i></div>'
            f'<small>{esc(plainify(note))}</small></div>')
    return f'<div class="mcgrid">{"".join(out)}</div>'


def finding(title, body, kind="g", src=None, tag=""):
    """kind: g(강점)/w(주의)/b(약점). src: 근거 뱃지 텍스트. tag: 제목 뒤 안전 HTML(심각도 배지 등)."""
    cls = "finding" if kind == "g" else f"finding {kind}"
    s = f'<span class="src">{esc(src)}</span>' if src else ""
    # 전문 약어 → 쉬운 말(title은 esc 전, body는 이미 esc/HTML이라 그대로 치환)
    return f'<div class="{cls}"><h4>{esc(plainify(title))}{tag}</h4><p>{plainify(body)}</p>{s}</div>'


def pillars(cards, cols=None):
    """cards: [(축라벨, 제목, 한줄), ...]. cols=3이면 3열 1줄 고정(모바일은 1열)."""
    cs = "".join(
        f'<div class="pcard"><div class="n">{esc(n)}</div><h4>{esc(t)}</h4><p>{esc(p)}</p></div>'
        for n, t, p in cards)
    cls = "pillar cols3" if cols == 3 else "pillar"
    return f'<div class="{cls}">{cs}</div>'


def table(headers, rows, num_cols=None):
    """headers:[..], rows:[[..],..], num_cols: 우측정렬할 열 인덱스 set."""
    num_cols = num_cols or set()
    th = "".join(
        f'<th class="num">{esc(h)}</th>' if i in num_cols else f"<th>{esc(h)}</th>"
        for i, h in enumerate(headers))
    trs = []
    for r in rows:
        tds = "".join(
            f'<td class="num">{c}</td>' if i in num_cols else f"<td>{c}</td>"
            for i, c in enumerate(r))
        trs.append(f"<tr>{tds}</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"


def roadmap(steps):
    """steps: [(tier'now|mid|long', 제목, 설명, fx설명), ...]"""
    out = ['<div class="road">']
    for tier, title, desc, fx in steps:
        badge = scoring.TIER_BADGE[tier]
        lab = scoring.TIER_LABEL[tier]
        fxh = f'<div class="fx">{esc(fx)}</div>' if fx else ""
        if isinstance(desc, (list, tuple)):        # 여러 실행 항목 → 불릿
            desch = '<ul class="rdul">' + "".join(f"<li>{esc(x)}</li>" for x in desc) + "</ul>"
        elif desc:
            desch = f'<p>{esc(desc)}</p>'
        else:
            desch = ""
        out.append(
            f'<div class="step"><span class="badge {badge}">{lab}</span>'
            f'<div><h4>{esc(title)}</h4>{desch}{fxh}</div></div>')
    out.append("</div>")
    return "".join(out)


def actions_to_roadmap(actions):
    """
    actions: [{title, effort, impact, cost, desc?}] → score_action으로 정렬한 로드맵.
    반환: roadmap HTML.
    """
    scored = []
    for a in actions:
        r = scoring.score_action(a.get("effort"), a.get("impact"), a.get("cost"))
        scored.append((r, a))
    order = {"now": 0, "mid": 1, "long": 2}
    scored.sort(key=lambda x: (order[x[0]["tier"]], -x[0]["priority"]))
    steps = []
    for r, a in scored:
        fx = (f'효과 {a.get("impact","?")} · 노력 {a.get("effort","?")} · 비용 {a.get("cost","?")} '
              f'→ 우선순위 {r["priority"]} · 실행가능성 {scoring.FEAS_LABEL[r["feasibility"]]}')
        steps.append((r["tier"], plainify(a["title"]), plainify(a.get("desc", "")), fx))
    return roadmap(steps)


def quote(text, source):
    return f'<div class="quote">{esc(text)}<span class="s">{esc(source)}</span></div>'


def senti_bar(pos, neu, neg):
    return (f'<div class="senti"><div class="pos" style="width:{pos}%"></div>'
            f'<div class="neu" style="width:{neu}%"></div>'
            f'<div class="neg" style="width:{neg}%"></div></div>')


def keywords(items, neg=False):
    cls = "kw neg" if neg else "kw"
    return '<div class="kwrow">' + "".join(
        f'<span class="{cls}">{esc(k)}</span>' for k in items) + "</div>"


def method_cards(items):
    """items: [(제목, 설명), ...] → '어떻게 분석했나' 방법 카드 그리드."""
    ms = "".join(f'<div class="m"><b>{esc(t)}</b><p>{esc(d)}</p></div>' for t, d in items)
    return f'<div class="method">{ms}</div>'


def criteria_table(rows):
    """rows: [(지표, 확인한 질문, (결과라벨, tag클래스)), ...] → 기준 표."""
    trs = []
    for metric, q, res in rows:
        label, cls = res if isinstance(res, (tuple, list)) else (res, "t-good")
        trs.append(f'<tr><td style="font-weight:800;white-space:nowrap">{esc(plainify(metric))}</td>'
                   f'<td>{esc(plainify(q))}</td><td><span class="tag {cls}">{esc(label)}</span></td></tr>')
    return (f'<table><thead><tr><th style="width:24%">지표</th><th>확인한 질문(기준)</th>'
            f'<th style="width:16%">결과</th></tr></thead><tbody>{"".join(trs)}</tbody></table>')


def flow2(nodes):
    """1·2차 흐름도. nodes: [('box', text, on?) | ('arrow', text)]."""
    out = ['<div class="flow2">']
    for n in nodes:
        if n[0] == "arrow":
            out.append(f'<span class="a">{esc(n[1])}</span>')
        else:
            on = " on" if (len(n) > 2 and n[2]) else ""
            out.append(f'<span class="b{on}">{esc(n[1])}</span>')
    out.append("</div>")
    return "".join(out)


def review_channel_box(name, brand, kpis, sentiment):
    """리뷰 채널 비교 박스. brand: naver/google/etc, kpis: [(라벨,값)], sentiment: (pos,neu,neg)."""
    cls = {"naver": "cb-naver", "google": "cb-google"}.get(brand, "cb-etc")
    pos, neu, neg = sentiment
    krows = "".join(f'<div class="kpi"><span>{esc(l)}</span><b>{esc(v)}</b></div>' for l, v in kpis)
    return (f'<div class="chanbox"><div class="ctop"><span class="cbadge {cls}">{esc(name)}</span></div>'
            f'{krows}'
            f'<div class="sbar"><i class="p" style="width:{pos}%"></i>'
            f'<i class="u" style="width:{neu}%"></i><i class="g" style="width:{neg}%"></i></div>'
            f'<div class="sleg"><span class="lp">긍정 {pos}%</span>'
            f'<span class="lu">중립 {neu}%</span><span class="lg">부정 {neg}%</span></div></div>')


def gquarter(qcls, qlab, title, months_html, focus_rows):
    """그라디언트 분기 블록. focus_rows: [(라벨, 설명), ...]."""
    fr = "".join(f'<div class="frow"><span class="fl">{esc(l)}</span><p>{d}</p></div>'
                 for l, d in focus_rows)
    return (f'<div class="gquarter"><div class="gqhead {qcls}"><span class="qlab">{esc(qlab)}</span>'
            f'<h3>{esc(title)}</h3></div><div class="gqbody">{months_html}{fr}</div></div>')


def checklist(rows):
    """실행 체크리스트. rows: [(tier라벨, 실행항목, 담당placeholder, 기한placeholder), ...]."""
    trs = []
    for tier, item, owner, due in rows:
        trs.append(f'<tr><td><span class="box"></span></td>'
                   f'<td><span class="tag {tier[1]}">{esc(tier[0])}</span></td>'
                   f'<td>{esc(item)}</td><td class="owner">{esc(owner)}</td>'
                   f'<td class="owner">{esc(due)}</td></tr>')
    return (f'<table class="checklist"><thead><tr><th style="width:5%">✓</th><th style="width:12%">시기</th>'
            f'<th>실행 항목</th><th style="width:16%">담당</th><th style="width:14%">기한</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table>')


def two_col_lists(left, right):
    lh = "".join(f"<li>{esc(x)}</li>" for x in left)
    rh = "".join(f"<li>{esc(x)}</li>" for x in right)
    return f'<div class="two"><ul>{lh}</ul><ul>{rh}</ul></div>'
