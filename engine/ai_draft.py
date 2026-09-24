# -*- coding: utf-8 -*-
"""
AI 초안층 — Claude API로 채널 진단(03)·리뷰 평판(04)의 입력 JSON을 초안 생성.

  근거: PRD_marketing_audit.md §8(AI 연동·스키마 강제·환각방지), §16(리뷰 평판).

설계
  - 코어 6리포트 엔진은 무의존성(stdlib)이지만, AI 초안은 공식 `anthropic` SDK가 필요하다.
    → 선택적 애드온: SDK+키가 있을 때만 실제 호출, 없으면 명확히 표시된 dry-run 목업.
  - 모델: claude-opus-4-8 (기본), 출력은 structured output(json_schema)로 강제 → 파싱 실패 제거.
  - 환각 방지: "원재료에 없는 수치는 지어내지 말 것, 불명은 확인 필요"를 시스템 프롬프트에 명시.
  - 최종은 담당자 검수(웹앱의 편집 폼)가 안전장치. 이 초안은 '초안'일 뿐이다.

사용
  from engine import ai_draft
  ai_draft.available()                      # (SDK 설치 & 키 존재) 여부
  ai_draft.draft_marketing(clinic, raw_by_channel)   # {"channels":[...]}
  ai_draft.draft_review(clinic, raw_reviews)         # {"channels":[...], ...}
  # dry_run=True 로 강제하면 키 없이 목업(예시) 반환
"""
import base64
import json
import os

MODEL = "claude-opus-4-8"
VISION_MEDIA_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")

# PRD §9 채널 라벨(초안 프롬프트에서 관점 주입용)
CHANNEL_LABELS = {
    "homepage": "홈페이지", "blog": "네이버 블로그", "instagram": "인스타그램",
    "naverplace": "네이버 플레이스", "kakao": "카카오톡 채널", "map": "카카오맵",
    "tmap": "T맵", "aeo_geo": "AEO·GEO(AI 검색 노출)",
}
# 채널별 평가 관점(criteria 요약) — PRD §8에서 criteria.json 관점 주입에 해당
CHANNEL_CRITERIA = {
    "homepage": "디자인·정보구조·전화(tel)/예약 전환 동선·모바일·SEO·구조화데이터",
    "blog": "발행 주기·정보성·검색 노출·이웃 수·전문성 콘텐츠",
    "instagram": "팔로워·게시 빈도·릴스/숏폼·브랜딩·프로필 완성도",
    "naverplace": "리뷰 수·정보 정확성(영업시간·전화·가격·진료과목)·소식·사진 수·예약/편의(네이버는 별점 폐지 — 평가 제외)",
    "kakao": "친구 수·상담 창구·소식·쿠폰·응대",
    "map": "정보 정확성(NAP)·후기 공개여부·사진·소식(별점/평점은 평가 제외; 페이지 하단 '주변 인기·맛집' 추천 위젯은 이 병원과 무관하니 근거로 쓰지 말 것)",
    "tmap": "이름·주소·전화·핀 정합성(NAP)",
    "aeo_geo": "구조화데이터·FAQ·엔티티(NAP) 일관성·생성엔진 노출",
}

_SYSTEM_CHANNEL = (
    "너는 동물병원 온라인 채널 진단가다. 주어진 [채널 유형]과 [평가 관점]에 따라 [원재료]를 분석해 "
    "지정된 JSON 스키마로만 출력한다. 점수(score)는 0~100. "
    "one_liner: 이 채널의 핵심을 한 줄로(예: '보여주는 힘은 뛰어난데 전화·예약으로 잇는 전환 기본기가 비어 있다'). "
    "subscores: 이 채널 종합점수를 구성하는 2~6개 하위축(label·level(우수/양호/보통/개선 필요)·note 한 줄). "
    "예) 홈페이지=디자인·브랜드/콘텐츠·신뢰/UX·전환/기술·SEO, 블로그=발행·운영/콘텐츠/제목·키워드/전환·참여, "
    "인스타=프로필/콘텐츠·협업/성장·도달/전환. "
    "criteria: 평가 항목표 — 관점(perspective)·확인 질문(question)·결과(result:우수/양호/보통/미흡/확인 필요). 채널에 맞는 4~7개. "
    "강점/약점은 근거 기반 1~2문장. 개선안은 effort/impact/cost를 각 1~3으로(우선순위·티어 계산은 엔진이 한다). "
    "약점 severity는 low/mid/high. "
    "중요: 원재료에 없는 수치는 지어내지 말 것. 확인 불가는 note/result에 '확인 필요'로, 점수는 보수적으로. 과장·환각 금지. "
    "이 병원의 등급(tier)은 사용자 메시지에 있는 사실이다. 자기 병원을 'N차병원급/N차 병원 수준'처럼 '급·수준'을 붙여 "
    "근접한 것처럼 쓰지 말고, 사실대로 'N차 병원' 또는 'N차 진료 전문'으로 단정해 표현하라. "
    "출력 문구(one_liner·subscores note·criteria·강점·약점·개선안)에는 '캡처/스크린샷/캡쳐' 같은 내부 수집 "
    "용어를 절대 쓰지 마라. '화면상/홈페이지/사이트/채널에서 확인'처럼 표현하라."
)
_SYSTEM_REVIEW = (
    "너는 동물병원 리뷰 평판 분석가다. 주어진 [리뷰 원문/캡처요약]을 분석해 지정된 JSON 스키마로만 출력한다. "
    "채널별 감성 분포(pos/neu/neg 합=100), 칭찬/불만 키워드, 대표 인용(짧게, 원문에 있는 것만), "
    "평판 진단(findings), 개선안(actions: effort/impact/cost 각 1~3)을 만든다. "
    "중요: 원문에 없는 리뷰·수치·인용을 지어내지 말 것. "
    "★review_count(리뷰 수)는 개별 리뷰 개수를 세지 말고, 프로필 상단·탭에 표시된 '총 리뷰 수'를 우선 사용하라 "
    "(예: '동물병원 · 리뷰 1,337', '방문자 리뷰 993', '블로그 리뷰 440'). 그 총 숫자가 보이면 반드시 그 값을 쓰고, "
    "총 숫자가 어디에도 없을 때만 null. 별점도 프로필에 표시된 평균 별점을 우선, 없으면 null. "
    "개인정보·진료정보는 최소화(익명 처리). 과장·환각 금지. "
    "출력 문구(findings·인용·개선안)에는 '캡처/스크린샷' 같은 내부 수집 용어를 쓰지 말고 "
    "'리뷰/화면/채널에서'처럼 표현하라."
)

# ── 출력 스키마(structured output) ─ 숫자 범위는 스키마로 강제 불가라 프롬프트로 지시 ──
_ACTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "effort": {"type": "integer", "enum": [1, 2, 3]},
        "impact": {"type": "integer", "enum": [1, 2, 3]},
        "cost": {"type": "integer", "enum": [1, 2, 3]},
    },
    "required": ["title", "effort", "impact", "cost"],
}
_CHANNEL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "score": {"type": "integer"},
        "note": {"type": "string"},
        "one_liner": {"type": "string",
                      "description": "이 채널의 핵심 한 줄 진단(참조체: '보여주는 힘은 뛰어난데 전환 기본기가 비어 있다' 식)."},
        "review_count": {"type": ["integer", "null"],
                         "description": "이 채널(네이버 플레이스·구글 등)의 리뷰 수가 캡처에 보이면 정수, 안 보이면 null."},
        "rating": {"type": ["number", "null"], "description": "별점이 보이면 숫자(예 4.8), 안 보이면 null."},
        "subscores": {"type": "array", "description": "채널 종합점수를 구성하는 2~6개 하위축.", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"label": {"type": "string"},
                           "level": {"type": "string", "enum": ["우수", "양호", "보통", "개선 필요"]},
                           "note": {"type": "string"}},
            "required": ["label", "level", "note"]}},
        "criteria": {"type": "array", "description": "평가 항목표: 관점·확인질문·결과.", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"perspective": {"type": "string"}, "question": {"type": "string"},
                           "result": {"type": "string", "enum": ["우수", "양호", "보통", "미흡", "확인 필요"]}},
            "required": ["perspective", "question", "result"]}},
        "strengths": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
            "required": ["title", "body"]}},
        "weaknesses": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"title": {"type": "string"}, "body": {"type": "string"},
                           "severity": {"type": "string", "enum": ["low", "mid", "high"]}},
            "required": ["title", "body", "severity"]}},
        "actions": {"type": "array", "items": _ACTION_SCHEMA},
    },
    "required": ["score", "note", "one_liner", "review_count", "rating",
                 "subscores", "criteria", "strengths", "weaknesses", "actions"],
}
_SENTI_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"pos": {"type": "integer"}, "neu": {"type": "integer"}, "neg": {"type": "integer"}},
    "required": ["pos", "neu", "neg"],
}
_REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "channels": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "name": {"type": "string"},
                "review_count": {"type": ["integer", "null"],
                                 "description": "프로필 상단·탭의 '총 리뷰 수'(예: 리뷰 1,337 / 방문자 리뷰 993). 개별 리뷰 개수를 세지 말 것. 없으면 null."},
                "rating": {"type": ["number", "null"]},
                "recency": {"type": "string"},
                "sentiment": _SENTI_SCHEMA,
            },
            "required": ["name", "review_count", "rating", "recency", "sentiment"]}},
        "praise_keywords": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}},
        "complaint_keywords": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}},
        "quotes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"text": {"type": "string"}, "channel": {"type": "string"},
                           "author": {"type": "string"},
                           "sentiment": {"type": "string", "enum": ["pos", "neu", "neg"]}},
            "required": ["text", "channel", "author", "sentiment"]}},
        "findings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"title": {"type": "string"}, "body": {"type": "string"},
                           "severity": {"type": "string", "enum": ["low", "mid", "high"]}},
            "required": ["title", "body", "severity"]}},
        "actions": {"type": "array", "items": _ACTION_SCHEMA},
    },
    "required": ["channels", "praise_keywords", "complaint_keywords", "quotes", "findings", "actions"],
}


# 키 영구 저장(선택) — 프로젝트 밖 개인 위치, 소유자만 읽기(0600)
KEY_FILE = os.path.expanduser("~/.config/petamos/api_key")


def has_saved_key():
    return os.path.isfile(KEY_FILE)


def load_saved_key():
    """저장된 키가 있고 환경변수가 비어 있으면 메모리로 로드. 반환: 로드했는지."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return False
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
            return True
    except Exception:
        pass
    return False


def save_key_to_disk(key):
    """키를 개인 위치에 0600으로 저장."""
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write((key or "").strip())
    try:
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass


def forget_saved_key():
    """저장된 키 파일 삭제 + 현재 메모리 키 제거."""
    try:
        os.remove(KEY_FILE)
    except FileNotFoundError:
        pass
    os.environ.pop("ANTHROPIC_API_KEY", None)


def _has_key():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _sdk():
    try:
        import anthropic  # noqa: F401
        return anthropic
    except Exception:
        return None


def available():
    """실제 AI 호출 가능 여부 (SDK 설치 + 키 존재)."""
    return _sdk() is not None and _has_key()


def status_text():
    if _sdk() is None:
        return "anthropic SDK 미설치 (pip install anthropic)"
    if not _has_key():
        return "ANTHROPIC_API_KEY 미설정 (환경변수로 키 지정)"
    return "AI 초안 사용 가능"


def validate_key():
    """키 유효성을 무료 호출(models.list)로 확인. 반환: (ok: bool, msg: str)."""
    anthropic = _sdk()
    if anthropic is None:
        return (False, "anthropic SDK 미설치")
    if not _has_key():
        return (False, "키가 설정되지 않았습니다")
    try:
        client = anthropic.Anthropic()
        next(iter(client.models.list(limit=1)), None)  # 토큰 과금 없는 인증 확인
        return (True, "키 확인됨 — AI 초안 사용 가능")
    except Exception as e:
        name = type(e).__name__
        if "Authentication" in name:
            return (False, "키가 유효하지 않습니다(인증 실패). 키를 다시 확인하세요")
        if "Connection" in name or "APIConnection" in name:
            return (False, "네트워크 연결 실패 — 인터넷 연결을 확인하세요")
        return (False, f"키 검증 실패: {name}")


def _parse_json(resp):
    """응답을 dict로. 토큰 한도로 잘렸으면(불완전 JSON) 명확한 에러로 바꿔 던짐."""
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        if getattr(resp, "stop_reason", "") == "max_tokens":
            raise RuntimeError(
                "AI 응답이 토큰 한도로 잘렸습니다(max_tokens). 항목 수를 줄이거나 재시도하세요.") from e
        raise RuntimeError(f"AI 응답 JSON 파싱 실패: {e}") from e


def _call(system, user, schema, max_tokens=5000):
    anthropic = _sdk()
    if anthropic is None:
        raise RuntimeError("anthropic SDK 미설치")
    client = anthropic.Anthropic()  # 키는 환경변수에서 자동 로드
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    return _parse_json(resp)


def guess_media_type(filename, content_type=""):
    ct = (content_type or "").lower().split(";")[0].strip()
    if ct in VISION_MEDIA_TYPES:
        return ct
    fn = (filename or "").lower()
    if fn.endswith(".png"):
        return "image/png"
    if fn.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if fn.endswith(".webp"):
        return "image/webp"
    if fn.endswith(".gif"):
        return "image/gif"
    return "image/png"


def fit_image(data, media_type, max_edge=7500, max_bytes=7_000_000):
    """Claude 비전 한계에 맞게 축소.
    - 한 변 > max_edge(px)면 리사이즈
    - 파일 > max_bytes면 JPEG 재인코딩(품질·크기 단계 축소)로 용량↓
      (API는 base64 10MB 한도 — base64는 원본의 ~1.33배라 raw 7MB면 base64 ~9.3MB로 안전)
    필요 없으면 원본 그대로."""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if max(w, h) <= max_edge and len(data) <= max_bytes:
            return data, media_type
        img = img.convert("RGB")
        if max(w, h) > max_edge:                       # 큰 변부터 px 축소
            scale = max_edge / float(max(w, h))
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        # 품질을 낮춰가며 용량 목표 달성 시도
        for quality in (88, 78, 68, 58):
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality)
            if out.tell() <= max_bytes:
                return out.getvalue(), "image/jpeg"
        # 그래도 크면 한 변을 20%씩 더 줄이며 반복
        cur = img
        for _ in range(6):
            w2, h2 = cur.size
            cur = cur.resize((max(1, int(w2 * 0.8)), max(1, int(h2 * 0.8))), Image.LANCZOS)
            out = io.BytesIO()
            cur.save(out, format="JPEG", quality=70)
            if out.tell() <= max_bytes:
                return out.getvalue(), "image/jpeg"
        return out.getvalue(), "image/jpeg"            # 최선의 축소본
    except Exception:
        return data, media_type   # PIL 없거나 실패 → 원본(그럼 API가 거부할 수 있음)


def _call_vision(system, user, images, schema, max_tokens=5000):
    """images: [(bytes, media_type), ...] + 텍스트 프롬프트 → structured JSON."""
    anthropic = _sdk()
    if anthropic is None:
        raise RuntimeError("anthropic SDK 미설치")
    client = anthropic.Anthropic()
    content = []
    for data_bytes, media_type in images:
        data_bytes, media_type = fit_image(data_bytes, media_type)
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": media_type,
            "data": base64.standard_b64encode(data_bytes).decode("ascii")}})
    content.append({"type": "text", "text": user})
    resp = client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    return _parse_json(resp)


# ── 채널 진단 초안 ─────────────────────────────────────────────
def draft_channel(clinic, ctype, raw_material, dry_run=False):
    """채널 1개의 초안(dict: score/note/strengths/weaknesses/actions) + type."""
    label = CHANNEL_LABELS.get(ctype, ctype)
    if dry_run or not available():
        return _mock_channel(ctype, raw_material)
    user = (
        f"[병원] {clinic.get('name','')} (tier {clinic.get('tier',2)}차)\n"
        f"[채널 유형] {label} ({ctype})\n"
        f"[평가 관점] {CHANNEL_CRITERIA.get(ctype, '일반 채널 진단 관점')}\n"
        f"[원재료]\n{raw_material.strip() or '(원재료 없음 — 확인 필요로 처리)'}\n\n"
        "위 원재료만 근거로 이 채널의 진단 초안을 스키마대로 출력하라."
    )
    out = _call(_SYSTEM_CHANNEL, user, _CHANNEL_SCHEMA)
    out["type"] = ctype
    return out


def draft_channel_from_images(clinic, ctype, images, extra_memo="", dry_run=False):
    """캡처 이미지(§9)로 채널 진단 초안. images: [(bytes, media_type), ...]."""
    label = CHANNEL_LABELS.get(ctype, ctype)
    if dry_run or not available() or not images:
        ch = _mock_channel(ctype, "캡처")
        ch["note"] = "[예시 · AI 미연결] 캡처 비전 판독 미실행 — 키 연결 후 재생성"
        return ch
    system = _SYSTEM_CHANNEL + (
        " 첨부된 캡처 이미지를 읽어 화면에 실제로 보이는 값(별점·리뷰수·친구수·정보·소식·버튼 유무 등)만 근거로 하라. "
        "이미지에서 확인 안 되는 값은 지어내지 말고 note에 '확인 필요'로.")
    user = (
        f"[병원] {clinic.get('name','')} (tier {clinic.get('tier',2)}차)\n"
        f"[채널 유형] {label} ({ctype})\n"
        f"[평가 관점] {CHANNEL_CRITERIA.get(ctype, '일반 채널 진단 관점')}\n"
        f"[첨부] {label} 캡처 {len(images)}장"
        + (f"\n[담당자 메모] {extra_memo.strip()}" if extra_memo.strip() else "")
        + "\n위 캡처에 실제로 보이는 것만 근거로 이 채널의 진단 초안을 스키마대로 출력하라.")
    out = _call_vision(system, user, images, _CHANNEL_SCHEMA)
    out["type"] = ctype
    return out


# ── 채널 교차 종합(공통 강점·공통 과제) ─────────────────────────
_SYNTH_SCHEMA = {
    "type": "object",
    "properties": {
        "strengths": {
            "type": "array",
            "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "body": {"type": "string"},
            }, "required": ["title", "body"], "additionalProperties": False}},
        "challenges": {
            "type": "array",
            "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "body": {"type": "string"},
                "severity": {"type": "string", "enum": ["high", "mid"]},
            }, "required": ["title", "body", "severity"], "additionalProperties": False}},
    },
    "required": ["strengths", "challenges"], "additionalProperties": False,
}

_SYSTEM_SYNTH = (
    "너는 동물병원 온라인 마케팅 진단 종합가다. 아래 여러 채널의 개별 강점·약점 진단을 읽고, "
    "채널 하나씩 나열하지 말고 '채널을 가로지르는 공통 테마'로 다시 묶어 종합하라.\n"
    "· 각 항목은 여러 채널의 근거를 하나의 문단으로 엮어 풍부하게 서술한다. "
    "예) '전문성·신뢰 자산이 전 채널에 두텁다 — 의료진·장비·리뷰 N개·실사진·상담 창구까지 신뢰 근거가 채널마다 풍부합니다.'\n"
    "· 공통 강점 3개(2~4개), 공통 과제 5개(3~6개, severity: high 심각/‌mid 중간).\n"
    "· 반드시 입력에 실제로 있는 사실·숫자만 사용하고, 없는 값은 지어내지 마라.\n"
    "· 여러 채널에 걸친 같은 문제(예: '전화 전환 동선'과 '전화번호 확인 불가'는 동일 문제)는 하나로 합쳐라.\n"
    "· 문체는 '~합니다/~입니다'체로, 담당자가 바로 이해할 실무 톤으로 쓴다.\n"
    "· 전문 약어(OG·SPA·NAP·CTA·AEO·GEO·JSON-LD·meta description·alt·tel 링크·H1 등)는 쓰지 말고 "
    "누구나 아는 쉬운 말로 풀어 써라(예: OG 이미지→공유 미리보기 이미지, NAP→상호·주소·전화 표기, "
    "CTA→예약·전화 유도 버튼, tel 링크→전화 바로걸기). 의료 용어(MRI·CT 등)는 그대로 둔다.\n"
    "· 이 병원의 등급(tier)은 사실이다. 자기 병원을 'N차병원급/수준'처럼 '급·수준'을 붙여 근접 표현하지 말고 "
    "'N차 병원' 또는 'N차 진료 전문'으로 단정해 써라."
)


def synthesize_marketing(clinic, channels, dry_run=False):
    """여러 채널 진단을 읽어 채널 교차 '공통 강점/공통 과제'로 종합.
       반환 {"strengths":[{title,body}], "challenges":[{title,body,severity}]} 또는 None."""
    real = [c for c in channels if c.get("score") is not None]
    if dry_run or not available() or len(real) < 2:
        return None
    lines = []
    for c in channels:
        lab = CHANNEL_LABELS.get(c.get("type"), c.get("type"))
        parts = [f"[{lab}] 점수 {c.get('score')} · 한줄: {c.get('one_liner', '')}"]
        for s in c.get("strengths", []):
            parts.append(f"  +강점: {s.get('title', '')} — {s.get('body', '')}")
        for w in c.get("weaknesses", []):
            parts.append(f"  -약점: {w.get('title', '')} — {w.get('body', '')}")
        for sub in c.get("subscores", []):
            parts.append(f"  ·{sub.get('label', '')}({sub.get('level', '')}): {sub.get('note', '')}")
        lines.append("\n".join(parts))
    user = (f"[병원] {clinic.get('name', '')} (이미 {clinic.get('tier', 2)}차 병원 — '급/수준' 붙이지 말 것)\n"
            "[채널 진단 요약]\n" + "\n\n".join(lines) +
            "\n\n위를 종합해 채널 교차 공통 강점·공통 과제를 스키마대로 출력하라.")
    try:
        return _call(_SYSTEM_SYNTH, user, _SYNTH_SCHEMA, max_tokens=3500)
    except Exception as e:
        print(f"[synthesize error] {type(e).__name__}: {e}")
        return None


# ── 진료 특화 자동 추출(마케팅 채널 분석에서) ──────────────────
_SPECIALTY_SCHEMA = {
    "type": "object",
    "properties": {
        "specialties": {                 # 이 병원이 실제로 내세우는 진료 특화
            "type": "array",
            "items": {"type": "object", "properties": {
                "name": {"type": "string"},         # 예: '영상진단(CT·MRI)', '24시 응급', '치과', '심장'
                "evidence": {"type": "string"},     # 어느 채널에서 어떻게 노출되는지
                "emphasis": {"type": "string", "enum": ["강함", "보통", "약함"]},
            }, "required": ["name", "evidence", "emphasis"], "additionalProperties": False}},
        "groups": {                      # specialties를 진료 계열로 묶은 것(보기 편하게)
            "type": "array",
            "items": {"type": "object", "properties": {
                "category": {"type": "string"},   # 예: '외과·정형·신경(수술)', '영상진단·정밀검사', '24시 응급·중환자'
                "items": {"type": "array", "items": {"type": "string"}},  # 묶인 특화명
                "summary": {"type": "string"},    # 묶어서 한 문단으로 근거와 함께
                "emphasis": {"type": "string", "enum": ["강함", "보통", "약함"]},
            }, "required": ["category", "items", "summary", "emphasis"], "additionalProperties": False}},
        "suggestions": {                 # 누락·제안(역량은 보이나 덜 내세우거나, 내세울 만한데 안 하는)
            "type": "array",
            "items": {"type": "object", "properties": {
                "name": {"type": "string"},
                "note": {"type": "string"},
            }, "required": ["name", "note"], "additionalProperties": False}},
    },
    "required": ["specialties", "groups", "suggestions"], "additionalProperties": False,
}

_SYSTEM_SPECIALTY = (
    "너는 동물병원 진료 특화 분석가다. 여러 마케팅 채널(홈페이지·블로그·인스타·플레이스 등)의 진단·콘텐츠 요약을 읽고, "
    "이 병원이 '실제로 내세우는 진료 특화·전문 분야'를 추출하라. 스키마대로 출력한다.\n"
    "· specialties: 채널 콘텐츠에 근거가 있는 특화만(예: 영상진단(CT·MRI), 24시 응급, 중환자, 수술, 치과, 안과, 심장, 정형, 신경, 종양, 재활 등). "
    "각 특화가 마케팅에서 얼마나 강조되는지 emphasis(강함/보통/약함)로 평가하고, evidence에 어느 채널·어떤 콘텐츠로 노출되는지 근거를 밝힌다.\n"
    "· groups: 위 specialties를 '진료 계열'로 묶어 3~5개 그룹으로 정리하라(보기 편하게). "
    "예) 외과·정형·신경은 '외과·정형·신경(수술)' 한 그룹, 영상진단·초음파·검사는 '영상진단·정밀검사', "
    "24시·응급·중환자는 '24시 응급·중환자', 치과·안과·피부·재활 등은 '기타 전문 진료(치과·안과·재활 등)'처럼 병원에 맞게. "
    "각 그룹은 category(계열명)·items(묶인 특화명 배열)·summary(그 계열을 묶어서 한 문단으로, 근거 채널·콘텐츠 포함)·emphasis(그룹 종합).\n"
    "· suggestions: (1) 역량·언급은 보이지만 전면에 덜 내세워지는 특화(‘있는데 안 내세운다’), "
    "(2) 이 병원 성격상 내세우면 좋을 특화 제안. 각 note에 이유·실행 방향을 짧게.\n"
    "· 반드시 입력에 실제로 있는 근거만 사용하고 지어내지 마라. 근거가 약하면 emphasis를 낮추거나 suggestions로. "
    "전문 약어는 쉬운 말로, 의료 용어(CT·MRI 등)는 유지. 문체는 '~합니다/~입니다'체."
)


def extract_specialties(clinic, channels, dry_run=False):
    """마케팅 채널 분석에서 '내세우는 진료 특화'와 '누락·제안'을 추출.
       반환 {"specialties":[{name,evidence,emphasis}], "suggestions":[{name,note}]} 또는 None."""
    real = [c for c in channels if c.get("score") is not None]
    if dry_run or not available() or not real:
        return None
    lines = []
    for c in channels:
        lab = CHANNEL_LABELS.get(c.get("type"), c.get("type"))
        parts = [f"[{lab}] 한줄: {c.get('one_liner', '')}"]
        for s in c.get("strengths", []):
            parts.append(f"  +{s.get('title', '')}: {s.get('body', '')}")
        for sub in c.get("subscores", []):
            parts.append(f"  ·{sub.get('label', '')}: {sub.get('note', '')}")
        lines.append("\n".join(parts))
    user = (f"[병원] {clinic.get('name', '')} ({clinic.get('tier', 2)}차)\n[채널 콘텐츠 요약]\n"
            + "\n\n".join(lines) +
            "\n\n위에서 이 병원이 실제로 내세우는 진료 특화와 누락·제안을 스키마대로 추출하라.")
    try:
        return _call(_SYSTEM_SPECIALTY, user, _SPECIALTY_SCHEMA, max_tokens=2500)
    except Exception as e:
        print(f"[extract specialties error] {type(e).__name__}: {e}")
        return None


_SYNTH_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},        # 핵심 요약 한 줄(서술)
        "channel_note": {"type": "string"},    # 채널별 스냅샷 보충(네이버 vs 구글 시점 차이 등)
        "strengths": {
            "type": "array",
            "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "body": {"type": "string"},
            }, "required": ["title", "body"], "additionalProperties": False}},
        "challenges": {
            "type": "array",
            "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "body": {"type": "string"},
                "severity": {"type": "string", "enum": ["high", "mid"]},
            }, "required": ["title", "body", "severity"], "additionalProperties": False}},
        "ops_findings": {                      # 운영 관점 발견(채널관리 등 2~3개, 불만과 겹치지 않게)
            "type": "array",
            "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "body": {"type": "string"},
                "severity": {"type": "string", "enum": ["high", "mid", "low"]},
            }, "required": ["title", "body"], "additionalProperties": False}},
        "conclusion": {"type": "string"},      # 정리(핵심 만족요인은 강함, 발목잡는 N가지)
    },
    "required": ["summary", "strengths", "challenges", "conclusion"],
    "additionalProperties": False,
}

_SYSTEM_SYNTH_REVIEW = (
    "너는 동물병원 리뷰 평판 종합가다. 여러 리뷰 채널(네이버 플레이스·구글 등)의 감성·키워드·대표 후기·발견을 읽고, "
    "채널 하나씩 나열하지 말고 '고객이 반복해서 말하는 공통 테마'로 묶어 종합하라. 스키마대로 출력한다.\n"
    "· summary: 핵심 요약 한 줄(서술). 채널별 인상 차이(예: 네이버는 최근·긍정, 구글은 과거·양극 3.8)와 "
    "공통 강점·최대 리스크·반복 운영이슈를 2~3문장으로 압축. 예) '같은 병원인데 네이버는 최근·압도적 긍정, 구글은 과거·양극입니다. "
    "공통적으로 친절·자세한 설명·24시 안심은 확실한 강점, 비용 인식이 최대 리스크입니다.'\n"
    "· channel_note: 채널별 스냅샷 보충 한 줄. 왜 채널 인상이 갈리는지(네이버는 최근 리뷰가 쌓이는 반면 구글은 오래된 부정 리뷰가 "
    "답글 없이 상단에 남아 별점을 누른다 등). 데이터로 확인되는 범위에서만.\n"
    "· strengths(공통 강점) 3개(2~4개): 고객이 반복 칭찬하는 검증된 강점. 근거(대표 후기·비율·키워드) 엮어 한 문단.\n"
    "· challenges(공통 과제) 4개(2~5개, severity high/mid): 반복 불만·저평점 원인. body에 어느 채널에서 나오는지·대표 표현을 인용해 근거를 밝힌다.\n"
    "· ops_findings(운영 관점 발견) 2~3개: 불만 내용과 겹치지 말고 '채널 관리 관점'만 — 예: 특정 채널 프로필 방치로 별점이 눌린다, "
    "긍정 미담이 자산인데 활용 안 된다 등.\n"
    "· conclusion(정리): '실력·친절 등 핵심 만족요인은 이미 강하다. 발목 잡는 건 ①…②…③… 이것만 손보면 …' 형태로 1~2문장.\n"
    "· 반드시 입력에 실제로 있는 사실·표현만 사용하고, 없는 값은 지어내지 마라. 전문 약어는 쉬운 말로. 의료 용어(MRI·CT)는 유지. "
    "문체는 '~합니다/~입니다'체."
)


def synthesize_reviews(clinic, review, dry_run=False):
    """여러 리뷰 채널을 읽어 핵심요약·채널노트·공통 강점/과제·운영발견·정리로 종합.
       반환 dict(summary/channel_note/strengths/challenges/ops_findings/conclusion) 또는 None."""
    channels = review.get("channels", [])
    if dry_run or not available() or not channels:
        return None
    lines = []
    for c in channels:
        s = c.get("sentiment", {})
        lines.append(
            f"[{c.get('name', '리뷰채널')}] 리뷰 {c.get('review_count', '?')}개 · 별점 {c.get('rating', '?')} · "
            f"긍정 {s.get('pos', '?')}%/중립 {s.get('neu', '?')}%/부정 {s.get('neg', '?')}% · 최신성 {c.get('recency', '?')}")
    pk = [k.get("keyword") if isinstance(k, dict) else k for k in review.get("praise_keywords", [])]
    ck = [k.get("keyword") if isinstance(k, dict) else k for k in review.get("complaint_keywords", [])]
    quotes = [f"({q.get('channel', '')}·{q.get('sentiment', '')}) {q.get('text', '')}"
              for q in review.get("quotes", [])]
    finds = [f"{f.get('title', '')}: {f.get('body', '')}" for f in review.get("findings", [])]
    user = (
        f"[병원] {clinic.get('name', '')} (이미 {clinic.get('tier', 2)}차 병원 — '급/수준' 붙이지 말 것)\n"
        "[리뷰 채널 요약]\n" + "\n".join(lines) +
        (f"\n[반복 칭찬 키워드] {', '.join(pk)}" if pk else "") +
        (f"\n[반복 불만 키워드] {', '.join(ck)}" if ck else "") +
        (f"\n[대표 후기]\n" + "\n".join(quotes[:12]) if quotes else "") +
        (f"\n[운영 관점 발견]\n" + "\n".join(finds) if finds else "") +
        "\n\n위를 종합해 summary·channel_note·공통 강점/과제·ops_findings·conclusion을 스키마대로 출력하라.")
    try:
        return _call(_SYSTEM_SYNTH_REVIEW, user, _SYNTH_REVIEW_SCHEMA, max_tokens=4000)
    except Exception as e:
        print(f"[synthesize review error] {type(e).__name__}: {e}")
        return None


def draft_review_from_images(clinic, images, extra_memo="", dry_run=False):
    """리뷰 캡처 이미지(네이버·구글 등)로 리뷰 평판 초안."""
    if dry_run or not available() or not images:
        rv = _mock_review("캡처")
        rv["findings"] = [{"title": "[예시 · AI 미연결]",
                           "body": "캡처 비전 판독 미실행 — 키 연결 후 재생성", "severity": "mid"}]
        return rv
    system = _SYSTEM_REVIEW + (
        " 분석 대상은 두 가지다: (1) 첨부 리뷰 캡처 이미지, (2) 아래 [리뷰 텍스트](붙여넣은 리뷰 원문). "
        "캡처는 이미지에 실제로 보이는 값(문장·별점·수치)만 근거로 하고(안 보이면 null), "
        "[리뷰 텍스트]는 그 텍스트를 근거로 분석하라. "
        "출처(네이버 플레이스·네이버 블로그·구글 등)별로 반드시 '별도 채널'로 나눠라 — "
        "특히 [리뷰 텍스트]에 구글 등 캡처에 없는 채널의 리뷰가 있으면 그 채널을 빠뜨리지 말고 포함하라. "
        "★review_count는 캡처에 보이는 리뷰 '개수를 세지 말고', 프로필 상단·탭의 '총 리뷰 수'(예: '동물병원 · 리뷰 1,337', "
        "'방문자 리뷰 993', '블로그 리뷰 440')를 그대로 써라. 그 총 숫자가 캡처에 있으면 반드시 그 값을, 없을 때만 null. "
        "인용(quotes)은 캡처나 텍스트에 실제로 있는 문장만 쓰고 지어내지 마라.")
    has_text = bool(extra_memo.strip())
    user = (
        f"[병원] {clinic.get('name','')}\n"
        f"[첨부 캡처] 리뷰 캡처 {len(images)}장"
        + (f"\n[리뷰 텍스트]\n{extra_memo.strip()}" if has_text else "")
        + "\n캡처와 [리뷰 텍스트]를 모두 근거로, 출처별 채널로 나눠 리뷰 평판 초안을 스키마대로 출력하라.")
    return _call_vision(system, user, images, _REVIEW_SCHEMA)


_RIVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "review_count": {"type": ["integer", "null"]},
        "rating": {"type": ["number", "null"]},
        "homepage": {"type": "string", "enum": ["운영", "없음", "미확인"]},
        "blog": {"type": "string", "enum": ["운영", "없음", "미확인"]},
        "instagram": {"type": "string", "enum": ["운영", "없음", "미확인"]},
        "insta_followers": {"type": ["integer", "null"], "description": "인스타 캡처에 보이는 팔로워 수. 안 보이면 null."},
        "insta_posts": {"type": ["integer", "null"], "description": "인스타 캡처에 보이는 게시물 수. 안 보이면 null."},
        "specialties": {"type": "array", "items": {"type": "string"},
                        "description": "캡처에 보이는 진료 특화·전문 분야(치과·안과·심장·영상·정형·신경·종양·24시 등). 안 보이면 빈 배열."},
        "praise": {"type": "array", "items": {"type": "string"}},
        "complaint": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["review_count", "rating", "homepage", "blog", "instagram",
                 "insta_followers", "insta_posts", "specialties", "praise", "complaint"],
    "additionalProperties": False,
}


def extract_rival_from_images(name, images, memo=""):
    """경쟁 병원 캡처(네이버 플레이스·블로그·리뷰 등) → 보이는 값만 추출.

    반환: {review_count, rating, homepage/blog/instagram(운영/없음/미확인), praise[], complaint[]}.
    화면에 없으면 리뷰수·별점 null, 채널 '미확인'. 지어내지 않는다.
    """
    if not available() or not images:
        return {}
    system = ("너는 동물병원 경쟁사 분석가다. 업로드된 캡처(네이버 플레이스·블로그·리뷰 등)에서 "
              "화면에 실제로 보이는 값만 추출하라. 안 보이면 리뷰수·별점은 null, 채널은 '미확인'으로. 절대 지어내지 마라. "
              "★review_count는 개별 리뷰 개수를 세지 말고 프로필 상단·탭의 '총 리뷰 수'(예: '동물병원 · 리뷰 1,337', "
              "'방문자 리뷰 993 · 블로그 리뷰 440')를 그대로 써라 — 우리 병원과 같은 기준(총계)으로 공정 비교해야 하기 때문이다.")
    user = (f"[경쟁 병원] {name}\n[첨부] 캡처 {len(images)}장"
            + (f"\n[메모] {memo.strip()}" if memo.strip() else "")
            + "\n캡처에 보이는 리뷰수·별점·각 채널(홈피/블로그/인스타) 운영 여부·인스타 팔로워/게시물 수·"
            "진료 특화(과목)·대표 칭찬/불만 키워드를 스키마대로 출력하라.")
    try:
        return _call_vision(system, user, images, _RIVAL_SCHEMA)
    except Exception as e:
        print(f"[rival vision error] {type(e).__name__}: {e}")
        return {}


def draft_marketing(clinic, raw_by_channel, dry_run=False):
    """
    raw_by_channel: {channel_type: 원재료텍스트, ...}  (빈 값은 건너뜀)
    반환: {"channels": [ {type, score, note, strengths, weaknesses, actions}, ... ]}
    """
    channels = []
    for ctype, raw in raw_by_channel.items():
        if not (raw or "").strip():
            continue
        ch = draft_channel(clinic, ctype, raw, dry_run=dry_run)
        ch["type"] = ctype
        channels.append(ch)
    return {"channels": channels}


# ── 리뷰 평판 초안 ─────────────────────────────────────────────
def draft_review(clinic, raw_reviews, dry_run=False):
    if dry_run or not available():
        return _mock_review(raw_reviews)
    user = (
        f"[병원] {clinic.get('name','')}\n"
        f"[리뷰 원문/캡처요약]\n{(raw_reviews or '').strip() or '(리뷰 원문 없음)'}\n\n"
        "위 원문만 근거로 리뷰 평판 초안을 스키마대로 출력하라. 없는 내용은 지어내지 마라."
    )
    return _call(_SYSTEM_REVIEW, user, _REVIEW_SCHEMA, max_tokens=5000)


# ── dry-run 목업 (키 없이 흐름 시연용, '예시'임을 명확히) ──────────
def _mock_channel(ctype, raw_material):
    label = CHANNEL_LABELS.get(ctype, ctype)
    return {
        "type": ctype,
        "score": 60,
        "note": "[예시 초안 · AI 미연결] 실제 원재료 분석 아님 — 키 연결 후 재생성 필요",
        "one_liner": "[예시] AI 연결 후 채널 핵심 진단이 한 줄로 채워집니다.",
        "review_count": None, "rating": None,
        "subscores": [], "criteria": [],
        "strengths": [{"title": f"{label} 기본 정보 존재",
                       "body": "원재료에서 확인된 기본 항목입니다. (예시)"}],
        "weaknesses": [{"title": "정밀 진단 미실시",
                        "body": "AI 미연결 상태의 예시값입니다. 확인 필요.", "severity": "mid"}],
        "actions": [{"title": f"{label} 개선 검토", "effort": 2, "impact": 2, "cost": 1}],
    }


def _mock_review(raw_reviews):
    return {
        "channels": [{"name": "네이버 플레이스", "review_count": None, "rating": None,
                      "recency": "확인 필요", "sentiment": {"pos": 80, "neu": 12, "neg": 8}}],
        "praise_keywords": [{"keyword": "친절(예시)"}],
        "complaint_keywords": [{"keyword": "대기(예시)"}],
        "quotes": [{"text": "[예시] AI 미연결 상태의 목업 인용입니다.",
                    "channel": "예시", "author": "익명", "sentiment": "pos"}],
        "findings": [{"title": "[예시 초안 · AI 미연결]",
                      "body": "실제 리뷰 분석이 아닙니다. 키 연결 후 재생성하세요.", "severity": "mid"}],
        "actions": [{"title": "리뷰 응대 체계 점검(예시)", "effort": 1, "impact": 3, "cost": 1}],
    }


# CLI: python3 -m engine.ai_draft  (상태 확인)
if __name__ == "__main__":
    print("AI 초안 상태:", status_text())
    print("사용 가능:", available())
