# -*- coding: utf-8 -*-
"""
§9 링크 자동수집 — 공개 URL에서 채널 진단 원재료를 추출 (stdlib만 사용).

  근거: PRD_marketing_audit.md §9 채널별 수집 매트릭스, §12 컴플라이언스.

수집 방침(약관 준수)
  - 홈페이지·T맵: 링크 자동수집(안전 — 자사 사이트/지도 핀).
  - 카카오맵·인스타그램: '공개 메타'만 단발 GET(로그인·크롤 없음). 차단/JS렌더면 '확인 필요' 표시 후 캡처 보완 권장.
  - 네이버 블로그·플레이스·카카오톡: 자동 수집하지 않음(약관·차단) → 캡처 업로드(2단계 비전).
  - 자동 스크래핑·다중 페이지 크롤 금지. 사용자가 직접 넣은 URL 1개만 단발 fetch.

추출 신호(§9): title·meta·og·H1·tel·img alt·구조화데이터(JSON-LD)·SPA 여부.
"""
import html
import html.parser
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; PetamosAudit/1.0; +local-tool)"
TIMEOUT = 10
MAX_BYTES = 900_000

# 자동수집 허용(링크) 채널 vs 캡처 전용(약관)
LINK_CHANNELS = ["homepage", "tmap", "map", "instagram"]
CAPTURE_ONLY = ["blog", "naverplace", "kakao"]  # 네이버·카카오톡 = 캡처만
# 카카오맵·인스타는 '공개 메타만' — 주의 문구를 붙인다
META_ONLY_NOTE = {"map": "카카오맵", "instagram": "인스타그램"}

# 전화: 구분자(-, ., 공백)를 요구해 무구분 숫자열 오탐을 방지
_TEL_RE = re.compile(r"0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4}")


class _Extract(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.metas = {}          # name/property -> content
        self.h1 = []
        self.tel = set()
        self.img_total = 0
        self.img_alt = 0
        self.alts = []           # 이미지 alt 텍스트(진료과목 단서)
        self.script_count = 0
        self.jsonld_types = []
        self._has_root_div = False
        self._cap = None         # 현재 캡처 중인 태그('title'|'h1'|'ld')
        self._buf = []
        self._text_len = 0
        self._words = []         # 본문 가시 텍스트(특화 감지용, 상한 있음)
        self._noise = 0          # style/script/noscript 내부 깊이(본문서 제외)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._cap, self._buf = "title", []
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key and a.get("content"):
                self.metas[key] = a["content"][:400]
        elif tag == "h1":
            self._cap, self._buf = "h1", []
        elif tag == "a":
            href = a.get("href", "")
            if href.lower().startswith("tel:"):
                self.tel.add(href[4:].strip())
        elif tag == "img":
            self.img_total += 1
            alt = (a.get("alt") or "").strip()
            if alt:
                self.img_alt += 1
                if len(self.alts) < 80:
                    self.alts.append(alt[:80])
        elif tag == "script":
            self.script_count += 1
            if (a.get("type") or "").lower() == "application/ld+json":
                self._cap, self._buf = "ld", []
            else:
                self._noise += 1
        elif tag in ("style", "noscript"):
            self._noise += 1
        elif tag == "div":
            did = (a.get("id") or "").lower()
            if did in ("root", "app", "__next", "___gatsby"):
                self._has_root_div = True

    def handle_endtag(self, tag):
        if self._cap == "title" and tag == "title":
            self.title = "".join(self._buf).strip()[:300]
            self._cap = None
        elif self._cap == "h1" and tag == "h1":
            t = "".join(self._buf).strip()
            if t:
                self.h1.append(t[:200])
            self._cap = None
        elif self._cap == "ld" and tag == "script":
            self._parse_ld("".join(self._buf))
            self._cap = None
        elif tag in ("style", "noscript", "script") and self._noise:
            self._noise -= 1

    def handle_data(self, data):
        if self._cap:
            self._buf.append(data)
            return
        if self._noise:                          # style/script 내부는 본문서 제외
            return
        s = data.strip()
        if s:
            self._text_len += len(s)
            if len(self._words) < 1500:          # 본문 가시 텍스트 수집(상한)
                self._words.append(s)
            for m in _TEL_RE.findall(s):
                self.tel.add(m)

    def _parse_ld(self, raw):
        try:
            obj = json.loads(raw)
        except Exception:
            self.jsonld_types.append("(파싱불가)")
            return
        for node in (obj if isinstance(obj, list) else [obj]):
            if isinstance(node, dict):
                t = node.get("@type")
                if isinstance(t, list):
                    self.jsonld_types.extend(str(x) for x in t)
                elif t:
                    self.jsonld_types.append(str(t))


def _is_safe_host(host):
    """SSRF 가드 — 로컬호스트/사설/링크로컬 IP 차단(추후 다중사용자 대비)."""
    if not host:
        return False
    if host.lower() in ("localhost",):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True  # 해석 실패는 fetch 단계에서 에러로 처리
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False
    return True


def fetch_url(url):
    """공개 URL 단발 GET → 추출 신호 dict. 실패 시 {'error': ...}."""
    url = (url or "").strip()
    if not url:
        return {"error": "URL 없음"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"error": "http/https URL만 허용"}
    host = parsed.hostname
    if not host:
        return {"error": "호스트 없음"}
    # 한글 등 비ASCII 도메인 → punycode(IDNA)
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except Exception:
        ascii_host = host
    if not _is_safe_host(ascii_host):
        return {"error": "차단된 호스트(사설/로컬)"}
    netloc = ascii_host + (f":{parsed.port}" if parsed.port else "")
    url = urllib.parse.urlunparse(parsed._replace(netloc=netloc))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko,en"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype and ctype:
                return {"error": f"HTML 아님({ctype.split(';')[0]})", "final_url": resp.geturl()}
            charset = "utf-8"
            m = re.search(r"charset=([\w-]+)", ctype)
            if m:
                charset = m.group(1)
            data = resp.read(MAX_BYTES)
            final_url = resp.geturl()
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}"}

    try:
        text = data.decode(charset, errors="replace")
    except LookupError:
        text = data.decode("utf-8", errors="replace")

    ex = _Extract()
    try:
        ex.feed(text)
    except Exception:
        pass

    og = {k: v for k, v in ex.metas.items() if k.startswith("og:")}
    spa_likely = ex._text_len < 250 and (ex.script_count >= 3 or ex._has_root_div)
    return {
        "final_url": final_url,
        "title": ex.title,
        "meta_desc": ex.metas.get("description", "") or og.get("og:description", ""),
        "og_title": og.get("og:title", ""),
        "og_image": bool(og.get("og:image")),
        "h1": ex.h1[:5],
        "tel": sorted(ex.tel)[:3],
        "img_total": ex.img_total,
        "img_alt": ex.img_alt,
        "jsonld": sorted(set(ex.jsonld_types)),
        "spa_likely": spa_likely,
        "text_len": ex._text_len,
        "alts": ex.alts[:60],
        "text_excerpt": " ".join(ex._words)[:3000],   # 본문 발췌(특화 감지·AI 근거용)
    }


def signals_to_raw(sig, ctype):
    """추출 신호 → AI 초안용 원재료 텍스트."""
    label = {"homepage": "홈페이지", "tmap": "T맵", "map": "카카오맵",
             "instagram": "인스타그램"}.get(ctype, ctype)
    if sig.get("error"):
        return f"[{label} 자동수집 실패: {sig['error']}] — 캡처요약으로 보완 필요(확인 필요)."
    lines = [f"[{label} 자동수집 결과]", f"- 최종 URL: {sig.get('final_url','')}"]
    if sig.get("title"):
        lines.append(f"- 제목: {sig['title']}")
    if sig.get("og_title") and sig["og_title"] != sig.get("title"):
        lines.append(f"- OG 제목: {sig['og_title']}")
    if sig.get("meta_desc"):
        lines.append(f"- 메타/OG 설명: {sig['meta_desc']}")
    if sig.get("h1"):
        lines.append(f"- H1: {' | '.join(sig['h1'])}")
    lines.append(f"- 전화(tel): {', '.join(sig['tel']) if sig.get('tel') else '없음/확인 필요'}")
    lines.append(f"- 이미지 alt: {sig.get('img_alt',0)}/{sig.get('img_total',0)} (alt 있음/전체)")
    lines.append(f"- OG 이미지: {'있음' if sig.get('og_image') else '없음'}")
    lines.append(f"- 구조화데이터(JSON-LD): {', '.join(sig['jsonld']) if sig.get('jsonld') else '없음'}")
    if sig.get("spa_likely"):
        lines.append("- SPA 추정: 예(콘텐츠가 JS로 렌더 — 본문 텍스트 미노출). 상세는 캡처 보완 권장(확인 필요).")
    else:
        lines.append("- SPA 추정: 아니오(서버 렌더 콘텐츠 확인됨)")
    if sig.get("alts"):
        lines.append(f"- 이미지 alt 텍스트: {' | '.join(sig['alts'][:20])}")
    if sig.get("text_excerpt"):
        lines.append(f"- 본문 발췌: {sig['text_excerpt']}")
    if ctype in META_ONLY_NOTE:
        lines.append(f"※ {META_ONLY_NOTE[ctype]}는 공개 메타만 단발 조회(약관상 상세 자동수집 안 함). 팔로워/후기 등 상세는 캡처로 보완.")
    return "\n".join(lines)


def collect(ctype, url):
    """URL → 원재료 텍스트 (한 번에)."""
    return signals_to_raw(fetch_url(url), ctype)


# CLI: python3 -m engine.collectors <url>
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(signals_to_raw(fetch_url(sys.argv[1]), "homepage"))
    else:
        print("사용법: python3 -m engine.collectors <url>")
