# -*- coding: utf-8 -*-
"""전국 동물병원 채널 센서스 저장소 — SQLite(stdlib) 단일 파일.

hospitals : 명단(상호·주소·좌표·시도/구·상태) — 로스터에서 채움
channels  : 채널 센서스(리뷰수·홈피/블로그/인스타 유무·URL) — 수집기가 채움 (1:1)

namekey(정규화 상호+시군구)로 중복을 막는다. 수집은 hospitals에 있는데 channels가
아직 없는(또는 status='error') 행만 골라 이어서 돌린다(체크포인트).
"""
import os
import re
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "census.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hospitals (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  namekey   TEXT UNIQUE,
  name      TEXT,
  address   TEXT,
  sido      TEXT,
  sigungu   TEXT,
  lat       REAL,
  lng       REAL,
  phone     TEXT,
  status    TEXT,          -- 영업/폐업 등(로스터 원본)
  source    TEXT,          -- kakao / mois_csv / gg_api ...
  added_at  TEXT
);
CREATE TABLE IF NOT EXISTS channels (
  hospital_id     INTEGER PRIMARY KEY REFERENCES hospitals(id),
  place_id        TEXT,
  review_count    INTEGER,
  homepage        INTEGER,   -- 0/1
  blog            INTEGER,
  instagram       INTEGER,
  youtube         INTEGER,
  homepage_url    TEXT,
  blog_url        TEXT,
  instagram_url   TEXT,
  insta_via_search INTEGER,  -- 인스타를 플레이스 등록이 아닌 인스타검색으로 찾음
  collect_status  TEXT,      -- ok / not_found / error
  collect_error   TEXT,
  collected_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_hosp_region ON hospitals(sido, sigungu);
"""


def norm_key(name, sigungu=""):
    """상호+시군구 정규화 키(중복 방지). 지점·괄호·공백·특수문자 제거."""
    base = re.sub(r"[^0-9a-z가-힣]", "", (name or "").lower())
    reg = re.sub(r"[^0-9a-z가-힣]", "", (sigungu or "").lower())
    return f"{base}@{reg}" if reg else base


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def upsert_hospital(conn, rec):
    """명단 1건 추가(중복 namekey는 무시). 반환: 새로 추가됐으면 True."""
    key = norm_key(rec.get("name", ""), rec.get("sigungu", ""))
    if not key:
        return False
    cur = conn.execute(
        "INSERT OR IGNORE INTO hospitals"
        "(namekey,name,address,sido,sigungu,lat,lng,phone,status,source,added_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (key, rec.get("name"), rec.get("address"), rec.get("sido"), rec.get("sigungu"),
         rec.get("lat"), rec.get("lng"), rec.get("phone"), rec.get("status"),
         rec.get("source"), time.strftime("%Y-%m-%d %H:%M")))
    return cur.rowcount > 0


def pending_hospitals(conn, limit, sido=None, retry_errors=True):
    """채널 미수집(또는 에러) 병원 목록. 지역 필터 옵션."""
    where = ["(c.hospital_id IS NULL"]
    if retry_errors:
        where[0] += " OR c.collect_status='error'"
    where[0] += ")"
    params = []
    if sido:
        where.append("h.sido = ?")
        params.append(sido)
    sql = ("SELECT h.* FROM hospitals h LEFT JOIN channels c ON c.hospital_id=h.id"
           " WHERE " + " AND ".join(where) + " ORDER BY h.id LIMIT ?")
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def save_channels(conn, hospital_id, ch):
    """채널 센서스 결과 저장(upsert)."""
    conn.execute(
        "INSERT OR REPLACE INTO channels"
        "(hospital_id,place_id,review_count,homepage,blog,instagram,youtube,"
        " homepage_url,blog_url,instagram_url,insta_via_search,"
        " collect_status,collect_error,collected_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (hospital_id, ch.get("place_id"), ch.get("review_count"),
         int(bool(ch.get("homepage"))), int(bool(ch.get("blog"))),
         int(bool(ch.get("instagram"))), int(bool(ch.get("youtube"))),
         ch.get("homepage_url"), ch.get("blog_url"), ch.get("instagram_url"),
         int(bool(ch.get("insta_via_search"))),
         ch.get("collect_status", "ok"), ch.get("collect_error"),
         time.strftime("%Y-%m-%d %H:%M")))
    conn.commit()


def progress(conn):
    """수집 진행 현황."""
    tot = conn.execute("SELECT COUNT(*) FROM hospitals").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM channels WHERE collect_status='ok'").fetchone()[0]
    err = conn.execute("SELECT COUNT(*) FROM channels WHERE collect_status='error'").fetchone()[0]
    nf = conn.execute("SELECT COUNT(*) FROM channels WHERE collect_status='not_found'").fetchone()[0]
    return {"total": tot, "done": done, "not_found": nf, "error": err,
            "remaining": tot - done - nf - err}
