# -*- coding: utf-8 -*-
"""
구글 리뷰 자동 수집 — Google Places API(레거시). 평점·리뷰수·샘플 리뷰(별점 포함).

네이버 플레이스(별점 폐지)와 달리 구글은 평점(1~5)과 리뷰수, 최근 리뷰 텍스트를 준다.
리뷰 축에 '구글' 채널을 더한다. 감정은 샘플 리뷰의 별점 분포로 산출(AI 불필요).

키: Google Cloud → 'Places API' 사용 설정 → API 키. 월 $200 무료 크레딧 내 사실상 무료.
저장: ~/.config/petamos/google_key (0600) 또는 환경변수 GOOGLE_PLACES_KEY.
"""
import json
import os
import urllib.parse
import urllib.request

KEY_FILE = os.path.expanduser("~/.config/petamos/google_key")
_BASE = "https://maps.googleapis.com/maps/api/place"


def _key():
    return (os.environ.get("GOOGLE_PLACES_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def has_saved_key():
    return os.path.isfile(KEY_FILE)


def load_saved_key():
    if _key():
        return _key()
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            k = f.read().strip()
        if k:
            os.environ["GOOGLE_PLACES_KEY"] = k
        return k
    except Exception:
        return ""


def save_key_to_disk(k):
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write((k or "").strip())
    try:
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass
    if (k or "").strip():
        os.environ["GOOGLE_PLACES_KEY"] = k.strip()


def forget_saved_key():
    try:
        os.remove(KEY_FILE)
    except Exception:
        pass
    os.environ.pop("GOOGLE_PLACES_KEY", None)


def available():
    return bool(_key())


def status_text():
    return "구글 리뷰 연동 사용 가능" if available() else "Google Places 키 미설정"


def _get(path, params):
    params = dict(params, key=_key(), language="ko")
    url = f"{_BASE}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def find(query, lat=None, lng=None):
    """텍스트로 장소 검색 → {place_id, name, rating, total}. 실패 None."""
    if not available():
        return None
    params = {"input": query, "inputtype": "textquery",
              "fields": "place_id,name,rating,user_ratings_total"}
    if lat and lng:
        params["locationbias"] = f"point:{lat},{lng}"
    try:
        r = _get("findplacefromtext/json", params)
        cands = r.get("candidates", [])
        if cands:
            c = cands[0]
            return {"place_id": c.get("place_id"), "name": c.get("name"),
                    "rating": c.get("rating"), "total": c.get("user_ratings_total") or 0}
    except Exception:
        pass
    return None


def details(place_id):
    """place_id → {rating, total, reviews:[{rating,text,time}]}. 실패 None."""
    if not available() or not place_id:
        return None
    try:
        r = _get("details/json", {"place_id": place_id,
                                  "fields": "name,rating,user_ratings_total,reviews"})
        res = r.get("result", {})
        return {"rating": res.get("rating"), "total": res.get("user_ratings_total") or 0,
                "reviews": [{"rating": rv.get("rating"), "text": rv.get("text", ""),
                             "time": rv.get("relative_time_description", "")}
                            for rv in res.get("reviews", [])]}
    except Exception:
        return None


def review_channel(query, lat=None, lng=None):
    """구글 리뷰 채널 dict {source,type,review_count,rating,sentiment,quotes} 또는 None.
       감정은 샘플 리뷰 별점 분포(≥4 긍정 / 3 중립 / ≤2 부정)로 산출."""
    f = find(query, lat, lng)
    if not f or not f.get("place_id"):
        return None
    d = details(f["place_id"]) or {}
    reviews = d.get("reviews", [])
    total = d.get("total") or f.get("total") or 0
    rating = d.get("rating") or f.get("rating")
    if reviews:
        pos = sum(1 for r in reviews if (r.get("rating") or 0) >= 4)
        neg = sum(1 for r in reviews if 0 < (r.get("rating") or 0) <= 2)
        n = len(reviews)
        sentiment = {"pos": round(pos / n * 100), "neg": round(neg / n * 100),
                     "neu": round((n - pos - neg) / n * 100)}
    elif rating:
        p = max(0, min(100, round((rating - 1) / 4 * 100)))   # 평점→긍정률 근사
        sentiment = {"pos": p, "neu": 100 - p, "neg": 0}
    else:
        sentiment = {}
    quotes = [{"text": r["text"][:200], "sentiment": ("pos" if (r.get("rating") or 0) >= 4
                                                      else "neg" if (r.get("rating") or 0) <= 2 else "neu")}
              for r in reviews[:4] if r.get("text")]
    return {"source": "구글", "name": "구글 리뷰", "type": "google", "review_count": total,
            "rating": rating, "sentiment": sentiment, "quotes": quotes}
