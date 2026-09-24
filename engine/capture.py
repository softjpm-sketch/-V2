# -*- coding: utf-8 -*-
"""
채널 자동 캡처 — 헤드리스 브라우저(Playwright) 기반 스크린샷.

핵심 개념(로드맵 3단계):
  로그인 벽은 '고객'이 아니라 '우리'가 뚫는다.
  - 인스타·네이버는 우리 회사 계정으로 1회 로그인 → 세션(storage_state)을 파일로 저장.
  - 이후엔 그 세션으로 헤드리스 브라우저가 공개 프로필을 열어 자동 캡처.
  - 고객(원장)은 끝까지 주소만 준다. 남의 비공개 계정을 여는 게 아니라,
    공개 콘텐츠 앞의 '로그인하고 보세요' 문턱만 우리 계정으로 넘는 것.

선택 애드온: playwright (pip install --user playwright && python3 -m playwright install chromium)
설치 안 돼 있으면 available()==False 로 조용히 비활성(순수 stdlib 원칙 유지).

세션 파일: ~/.config/petamos/sessions/<site>.json  (0600)
캡처 결과:  <프로젝트>/captures/<slug>/<site>-<n>.png
"""
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPTURE_DIR = os.path.join(ROOT, "captures")
SESSION_DIR = os.path.expanduser("~/.config/petamos/sessions")

# 사이트별 로그인 페이지(세션 저장용) + 로그인 성공 판정에 쓸 URL
SITES = {
    "instagram": {"login": "https://www.instagram.com/accounts/login/", "label": "인스타그램"},
    "naver": {"login": "https://nid.naver.com/nidlogin.login", "label": "네이버(블로그·플레이스)"},
}

# 봇 탐지 완화용 유저에이전트(일반 데스크톱 크롬처럼)
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def available():
    """playwright 패키지 + 크롬 바이너리가 준비됐는지."""
    try:
        from playwright.sync_api import sync_playwright  # noqa
    except Exception:
        return False
    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
            return bool(path) and os.path.exists(path)
    except Exception:
        return False


def status_text():
    if not _pkg_ok():
        return "playwright 미설치 — pip install --user playwright"
    if not available():
        return "크롬 바이너리 없음 — python3 -m playwright install chromium"
    sites = [s for s in SITES if has_session(s)]
    return "캡처 가능 · 로그인 세션: " + (", ".join(sites) if sites else "없음(공개 페이지만)")


def _pkg_ok():
    try:
        import playwright  # noqa
        return True
    except Exception:
        return False


def session_path(site):
    return os.path.join(SESSION_DIR, f"{site}.json")


def has_session(site):
    return os.path.isfile(session_path(site))


def forget_session(site):
    try:
        os.remove(session_path(site))
        return True
    except Exception:
        return False


def save_login_session(site):
    """[운영자가 1회 실행] 브라우저를 띄워 사람이 직접 로그인 → 세션 저장.

    비밀번호는 코드/채팅에 넣지 않는다. 화면에 뜬 브라우저에서 직접 로그인(2FA·캡차 포함)한 뒤
    터미널에서 Enter 를 누르면 그 로그인 상태가 파일로 저장된다.
    헤드리스가 아니라 '보이는' 브라우저라 로컬(맥)에서 실행해야 한다.
    """
    if site not in SITES:
        raise ValueError(f"지원하지 않는 사이트: {site} (가능: {', '.join(SITES)})")
    from playwright.sync_api import sync_playwright
    os.makedirs(SESSION_DIR, exist_ok=True)
    info = SITES[site]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 사람이 로그인해야 하므로 창을 띄움
        ctx = browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(info["login"], wait_until="domcontentloaded")
        print(f"\n[{info['label']}] 브라우저 창에서 직접 로그인하세요(2FA·캡차 포함).")
        print("로그인이 끝나 평소 화면이 보이면, 이 터미널로 돌아와 Enter 를 누르세요.")
        try:
            input("   로그인 완료 후 Enter ▶ ")
        except EOFError:
            time.sleep(60)  # 비대화형이면 60초 대기
        sp = session_path(site)
        ctx.storage_state(path=sp)
        try:
            os.chmod(sp, 0o600)
        except Exception:
            pass
        browser.close()
    print(f"세션 저장 완료 → {sp}")
    return session_path(site)


def screenshot(url, site=None, out_path=None, full_page=True, wait_ms=3500, timeout_ms=30000):
    """URL을 헤드리스로 열어 스크린샷을 out_path 에 저장하고 경로를 반환.

    site 를 주면 그 사이트의 로그인 세션(있으면)을 실어 로그인 벽을 넘는다.
    실패하면 예외를 던진다(호출부에서 수동 캡처로 폴백).
    """
    from playwright.sync_api import sync_playwright
    if not out_path:
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        safe = "".join(c for c in url if c.isalnum())[-24:] or "page"
        out_path = os.path.join(CAPTURE_DIR, f"{site or 'web'}-{safe}.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    state = session_path(site) if (site and has_session(site)) else None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 1600},
                                  locale="ko-KR", storage_state=state)
        page = ctx.new_page()
        # SPA는 networkidle가 안 끝나므로 domcontentloaded로 진입 후 렌더를 기다린다.
        # 로드가 느려도(타임아웃) 일단 그린 화면을 캡처한다(빈손보단 부분 캡처).
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)  # 지연 로딩 대기
        if full_page:
            # 스크롤 애니메이션(숫자 카운트업·페이드인)·지연로딩·플로팅 버튼을 모두 발동시킨다.
            # 한 장 캡처는 스크롤 전이라 카운터가 0으로, 페이드인 요소가 빈 채로 찍히는 문제 해결.
            try:
                h = page.evaluate("() => document.body.scrollHeight")
                y = 0
                while y < h and y < 60000:            # 안전 상한
                    page.evaluate("(y)=>window.scrollTo(0,y)", y)
                    page.wait_for_timeout(220)
                    y += 700
                    h = page.evaluate("() => document.body.scrollHeight")  # 지연로딩으로 늘 수 있음
                page.evaluate("()=>window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1400)            # 카운트업 애니메이션 마무리 대기
                page.evaluate("()=>window.scrollTo(0,0)")
                page.wait_for_timeout(600)
            except Exception:
                pass
        try:
            page.keyboard.press("Escape")  # 열린 팝업·메뉴 오버레이 닫기(1차)
            page.wait_for_timeout(200)
            # 헤드리스에서 기본 열려버리는 전체화면 메뉴·팝업의 '닫기' 버튼 클릭(2차)
            page.evaluate("""() => {
              const sels=['.close_icon','.menu_close','.gnb_close','.btn_close',
                          '.layer_close','.pop_close','.modal-close','.close'];
              for(const s of sels){
                document.querySelectorAll(s).forEach(el=>{ try{el.click();}catch(e){} });
              }
              // 여전히 화면을 덮는 큰 fixed 오버레이는 숨김(플로팅 버튼 등 작은 건 유지)
              document.querySelectorAll('body *').forEach(el=>{
                const s=getComputedStyle(el), r=el.getBoundingClientRect();
                if(s.position==='fixed' && r.width>500 && r.height>window.innerHeight*0.7
                   && s.display!=='none' && parseFloat(s.opacity)>0.5){ el.style.display='none'; }
              });
            }""")
            page.wait_for_timeout(400)
        except Exception:
            pass
        page.screenshot(path=out_path, full_page=full_page)
        browser.close()
    return out_path


def get_links(url, site=None, wait_ms=3000, timeout_ms=30000):
    """URL을 열어 페이지 안의 모든 <a> 링크 [{href,text}] 를 반환(발견용)."""
    from playwright.sync_api import sync_playwright
    state = session_path(site) if (site and has_session(site)) else None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 1600},
                                  locale="ko-KR", storage_state=state)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)
        links = page.eval_on_selector_all(
            "a", "els => els.map(e => ({href: e.href, text: (e.innerText||'').trim().slice(0,60)}))")
        browser.close()
    return links or []


def _trigger_and_declutter(page, wait_ms):
    """스크롤로 애니메이션(카운트업·페이드인)·지연로딩 발동 + 전체화면 메뉴/오버레이 정리."""
    page.wait_for_timeout(wait_ms)
    try:
        h = page.evaluate("() => document.body.scrollHeight")
        y = 0
        while y < h and y < 60000:
            page.evaluate("(y)=>window.scrollTo(0,y)", y)
            page.wait_for_timeout(200)
            y += 1400
            h = page.evaluate("() => document.body.scrollHeight")
        page.wait_for_timeout(1200)          # 카운트업 마무리
        page.evaluate("()=>window.scrollTo(0,0)")
        page.wait_for_timeout(400)
    except Exception:
        pass
    try:                                     # 헤드리스에서 열려버리는 메뉴/모달 닫기·숨김
        page.evaluate("""() => {
          ['.close_icon','.menu_close','.gnb_close','.btn_close','.layer_close',
           '.pop_close','.modal-close','.close'].forEach(s=>
            document.querySelectorAll(s).forEach(el=>{try{el.click();}catch(e){}}));
          document.querySelectorAll('body *').forEach(el=>{
            const s=getComputedStyle(el), r=el.getBoundingClientRect();
            if(s.position==='fixed' && r.width>500 && r.height>window.innerHeight*0.7
               && s.display!=='none' && parseFloat(s.opacity)>0.5){ el.style.display='none'; }
          });
        }""")
        page.wait_for_timeout(300)
    except Exception:
        pass


def screenshot_segments(url, site=None, out_dir=None, max_shots=4,
                        wait_ms=3500, timeout_ms=30000):
    """페이지를 뷰포트 단위로 위→아래 나눠 여러 장 캡처. 반환 [png경로,...].
       스크롤해야 뜨는 플로팅 버튼·카운트업·페이드인을 각 화면에서 실제 위치로 잡는다."""
    from playwright.sync_api import sync_playwright
    out_dir = out_dir or os.path.join(CAPTURE_DIR, "seg")
    os.makedirs(out_dir, exist_ok=True)
    state = session_path(site) if (site and has_session(site)) else None
    vh = 1600
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": vh},
                                  locale="ko-KR", storage_state=state)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        _trigger_and_declutter(page, wait_ms)
        total = page.evaluate("() => document.body.scrollHeight") or vh
        shots = min(max_shots, max(1, (total + vh - 1) // vh))
        for i in range(shots):
            page.evaluate("(y)=>window.scrollTo(0,y)", i * vh)
            page.wait_for_timeout(450)
            fp = os.path.join(out_dir, f"seg{i}.png")
            try:
                page.screenshot(path=fp, full_page=False)   # 뷰포트만(고정 버튼 포함)
                paths.append(fp)
            except Exception:
                pass
        browser.close()
    return paths


def get_text(url, site=None, wait_ms=2500, timeout_ms=25000, max_chars=20000):
    """URL을 열어 렌더링된 본문 텍스트(inner_text)를 반환. SPA(JS 렌더)도 잡힘.
       경쟁사 홈페이지 실제 판독(진료과목 키워드 매칭)용."""
    from playwright.sync_api import sync_playwright
    state = session_path(site) if (site and has_session(site)) else None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 1600},
                                  locale="ko-KR", storage_state=state)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        _trigger_and_declutter(page, wait_ms)   # 스크롤로 페이드인·지연 콘텐츠까지 렌더(#3)
        try:
            txt = page.eval_on_selector("body", "el => el.innerText || ''")
        except Exception:
            txt = ""
        browser.close()
    return (txt or "")[:max_chars]


# 전화/카카오 링크의 고정 플로팅 컨테이너 위치를 computed style로 찾는 JS
_CTA_PROBE_JS = """() => {
  const links = document.querySelectorAll('a[href^="tel:"], a[href*="pf.kakao.com"], a[href*="kakao"]');
  for (const a of links) {
    let el = a, depth = 0;
    while (el && depth < 7) {
      const s = getComputedStyle(el);
      if (s.position === 'fixed') {
        return {found:true, cls:(el.className||'').toString().slice(0,60),
                right:s.right, left:s.left, top:s.top, bottom:s.bottom,
                width:s.width, vw:window.innerWidth, vh:window.innerHeight};
      }
      el = el.parentElement; depth++;
    }
  }
  return {found:false};
}"""


def get_dom(url, site=None, wait_ms=3000, timeout_ms=25000, max_chars=500000, with_cta=False):
    """URL을 열어 JS 렌더링 후의 실제 DOM(HTML)을 반환. 화면엔 안 보이는 tel:·카카오·
       메타·구조화데이터 링크까지 코드에서 검출하기 위함(하이브리드 분석).
       with_cta=True면 (html, cta위치dict) 튜플 반환 — 전화/카카오 고정 플로팅 위치."""
    from playwright.sync_api import sync_playwright
    state = session_path(site) if (site and has_session(site)) else None
    html = ""
    cta = {"found": False}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 900},
                                  locale="ko-KR", storage_state=state)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)
        try:
            html = page.content()
        except Exception:
            html = ""
        if with_cta:
            try:
                cta = page.evaluate(_CTA_PROBE_JS) or {"found": False}
            except Exception:
                cta = {"found": False}
        browser.close()
    html = (html or "")[:max_chars]
    return (html, cta) if with_cta else html


def blog_post_metrics(url, site=None, wait_ms=3500, timeout_ms=25000, max_chars=15000):
    """네이버 블로그 글 1개의 본문 텍스트 + 이미지 수 반환 (text, img_count).
       모바일(m.blog) URL 권장. 개별 글 콘텐츠 충실도 실측용."""
    from playwright.sync_api import sync_playwright
    state = session_path(site) if (site and has_session(site)) else None
    text, imgs = "", 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=_UA, viewport={"width": 500, "height": 1000},
                                  locale="ko-KR", storage_state=state)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)
        try:
            text = page.evaluate("()=>document.body.innerText||''")
        except Exception:
            text = ""
        try:
            imgs = page.evaluate("()=>document.querySelectorAll('.se-main-container img, "
                                 ".post_ct img, #viewTypeSelector img').length "
                                 "|| document.querySelectorAll('img').length")
        except Exception:
            imgs = 0
    return (text or "")[:max_chars], int(imgs or 0)


def capture_many(items, slug="capture"):
    """[(url, site), ...] 를 순서대로 캡처. 결과 [{url,site,path|error}] 반환.

    한 채널이 실패해도 나머지는 계속(부분 성공 → 실패분은 수동 폴백).
    사람처럼 채널 사이에 짧은 간격을 둔다(봇 탐지 완화).
    """
    out_dir = os.path.join(CAPTURE_DIR, slug)
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for i, (url, site) in enumerate(items, 1):
        if not url:
            continue
        path = os.path.join(out_dir, f"{site or 'web'}-{i}.png")
        try:
            screenshot(url, site=site, out_path=path)
            results.append({"url": url, "site": site, "path": path})
        except Exception as e:
            results.append({"url": url, "site": site, "error": str(e)})
        time.sleep(2.0)  # 사람 속도
    return results


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "login" and len(sys.argv) > 2:
        save_login_session(sys.argv[2])
    elif cmd == "forget" and len(sys.argv) > 2:
        ok = forget_session(sys.argv[2])
        print(f"세션 삭제 {'완료' if ok else '(없음)'}: {sys.argv[2]}")
    elif cmd == "shot" and len(sys.argv) > 2:
        site = sys.argv[3] if len(sys.argv) > 3 else None
        print(screenshot(sys.argv[2], site=site))
    elif cmd == "status":
        print(status_text())
    else:
        print("사용법:")
        print("  python3 -m engine.capture status")
        print("  python3 -m engine.capture login instagram   # 창 뜨면 직접 로그인 후 Enter (계정 교체도 이걸로)")
        print("  python3 -m engine.capture login naver")
        print("  python3 -m engine.capture forget instagram  # 로그아웃(세션 삭제)")
        print("  python3 -m engine.capture shot <URL> [instagram|naver]")
