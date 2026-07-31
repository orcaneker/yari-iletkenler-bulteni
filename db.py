# -*- coding: utf-8 -*-
"""
BİYOEKONOMİ BÜLTENİ — VERİTABANI (Neon Postgres)
====================================================
Taslak/onay durumu burada yaşar. Render diski geçici olduğu için
inceleme süreci boyunca tek kalıcı hafıza Neon'dur.

Şema:
  issues     : sayı taslakları ve durumları (review → approved → published)
  reviewers  : hakemler + kalıcı magic-link token'ları
  events_log : denetim izi (kim ne zaman ne yaptı)

Kurulum:
  python db.py --init                          # tabloları oluştur
  python db.py --seed "Ad Soyad" mail@x.com    # hakem ekle (token üretir)
  python db.py --reviewers                     # hakemleri listele
"""

import os
import sys
import json
import secrets
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def baglan():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL tanımlı değil (Neon bağlantı dizesi)")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


SEMA = """
CREATE TABLE IF NOT EXISTS issues (
    id            SERIAL PRIMARY KEY,
    hafta         TEXT UNIQUE NOT NULL,          -- '2026-H31' (H = Hafta)
    sayi_no       INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'review',-- review | approved | published
    draft_json    JSONB NOT NULL,                -- pipeline çıktısı (secim alanlı)
    final_json    JSONB,                         -- yayın anında kurulan nihai bülten
    rapor         JSONB,                         -- çalışma istatistikleri
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by   TEXT,
    approved_at   TIMESTAMPTZ,
    published_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reviewers (
    id       SERIAL PRIMARY KEY,
    ad       TEXT NOT NULL,
    email    TEXT UNIQUE NOT NULL,
    token    TEXT UNIQUE NOT NULL,
    aktif    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS events_log (
    id        SERIAL PRIMARY KEY,
    issue_id  INTEGER REFERENCES issues(id),
    reviewer  TEXT,
    eylem     TEXT NOT NULL,   -- goruntuledi | takas | radar_cikar | onay | yayin | hatirlatma
    detay     JSONB,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init():
    with baglan() as conn:
        conn.execute(SEMA)
    print("Tablolar hazır.")


# ============================================================
# ISSUES
# ============================================================
def taslak_kaydet(hafta, sayi_no, draft, rapor=None):
    """Pipeline taslağı kaydeder. Aynı hafta tekrar çalışırsa üzerine yazar
    (test tekrarları için) — ama yayınlanmış sayıya dokunmaz."""
    with baglan() as conn:
        mevcut = conn.execute(
            "SELECT id, status FROM issues WHERE hafta = %s", (hafta,)).fetchone()
        if mevcut and mevcut["status"] == "published":
            raise RuntimeError(f"{hafta} zaten yayınlanmış — üzerine yazılmaz")
        if mevcut:
            conn.execute(
                "UPDATE issues SET sayi_no=%s, draft_json=%s, rapor=%s, "
                "status='review', approved_by=NULL, approved_at=NULL, created_at=now() "
                "WHERE id=%s",
                (sayi_no, json.dumps(draft, ensure_ascii=False),
                 json.dumps(rapor or {}, ensure_ascii=False), mevcut["id"]))
            return mevcut["id"]
        r = conn.execute(
            "INSERT INTO issues (hafta, sayi_no, draft_json, rapor) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (hafta, sayi_no, json.dumps(draft, ensure_ascii=False),
             json.dumps(rapor or {}, ensure_ascii=False))).fetchone()
        return r["id"]


def issue_getir(issue_id=None, hafta=None, status=None):
    """Tek sayı getir. status verilirse o durumdaki EN YENİ sayı."""
    with baglan() as conn:
        if issue_id:
            return conn.execute("SELECT * FROM issues WHERE id=%s", (issue_id,)).fetchone()
        if hafta:
            return conn.execute("SELECT * FROM issues WHERE hafta=%s", (hafta,)).fetchone()
        if status:
            return conn.execute(
                "SELECT * FROM issues WHERE status=%s ORDER BY created_at DESC LIMIT 1",
                (status,)).fetchone()
    return None


def taslak_guncelle(issue_id, draft):
    """Hakem takası/çıkarması sonrası taslağı günceller."""
    with baglan() as conn:
        conn.execute("UPDATE issues SET draft_json=%s WHERE id=%s AND status='review'",
                     (json.dumps(draft, ensure_ascii=False), issue_id))


def govde_guncelle(issue_id, alan, veri):
    """draft_json veya final_json gövdesini günceller (metin düzeltmesi).

    taslak_guncelle'den farkı: durum kısıtı YOKTUR — yayınlanmış sayıda da
    yazım/çeviri hatası düzeltilebilmeli. Hangi gövdenin güncelleneceğini
    çağıran belirler; alan adı beyaz listeyle sınırlıdır (SQL'e doğrudan
    girdiği için serbest bırakılamaz).
    """
    if alan not in ("draft_json", "final_json"):
        raise ValueError(f"Geçersiz gövde alanı: {alan}")
    with baglan() as conn:
        conn.execute(f"UPDATE issues SET {alan}=%s WHERE id=%s",
                     (json.dumps(veri, ensure_ascii=False), issue_id))


def onayla(issue_id, hakem_ad):
    """TEK onay yeterli → status=approved. Zaten onaylıysa dokunmaz."""
    with baglan() as conn:
        r = conn.execute(
            "UPDATE issues SET status='approved', approved_by=%s, approved_at=now() "
            "WHERE id=%s AND status='review' RETURNING id",
            (hakem_ad, issue_id)).fetchone()
        return bool(r)


def yayinlandi(issue_id, final):
    with baglan() as conn:
        conn.execute(
            "UPDATE issues SET status='published', final_json=%s, published_at=now() "
            "WHERE id=%s",
            (json.dumps(final, ensure_ascii=False), issue_id))


# ============================================================
# REVIEWERS
# ============================================================
def hakem_ekle(ad, email):
    token = secrets.token_urlsafe(24)
    with baglan() as conn:
        conn.execute(
            "INSERT INTO reviewers (ad, email, token) VALUES (%s, %s, %s) "
            "ON CONFLICT (email) DO UPDATE SET ad = EXCLUDED.ad, aktif = TRUE",
            (ad, email, token))
    return token


def hakemler():
    with baglan() as conn:
        return conn.execute(
            "SELECT ad, email, token FROM reviewers WHERE aktif ORDER BY id").fetchall()


def hakem_token_ile(token):
    with baglan() as conn:
        return conn.execute(
            "SELECT ad, email FROM reviewers WHERE token=%s AND aktif",
            (token,)).fetchone()


# ============================================================
# EVENTS LOG
# ============================================================
def logla(issue_id, reviewer, eylem, detay=None):
    try:
        with baglan() as conn:
            conn.execute(
                "INSERT INTO events_log (issue_id, reviewer, eylem, detay) "
                "VALUES (%s, %s, %s, %s)",
                (issue_id, reviewer, eylem,
                 json.dumps(detay or {}, ensure_ascii=False)))
    except Exception:
        pass   # denetim izi hatası akışı durdurmasın


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--help":
        print(__doc__)
    elif args[0] == "--init":
        init()
    elif args[0] == "--seed":
        if len(args) < 3:
            sys.exit('Kullanım: python db.py --seed "Ad Soyad" mail@ornek.com')
        t = hakem_ekle(args[1], args[2])
        print(f"Hakem eklendi: {args[1]} <{args[2]}>")
        print(f"İnceleme linki: {{REVIEW_BASE_URL}}/r/{t}")
    elif args[0] == "--reviewers":
        for h in hakemler():
            print(f"  {h['ad']} <{h['email']}>  /r/{h['token']}")
    elif args[0] == "--durum":
        # Bakım: bir sayının durumunu elle değiştir.
        # Örn. yayın push'u başarısız olduysa geri onaylıya al:
        #   python db.py --durum 2026-H31 approved
        if len(args) < 3 or args[2] not in ("review", "approved"):
            sys.exit("Kullanım: python db.py --durum <hafta> <review|approved>")
        with baglan() as conn:
            r = conn.execute(
                "UPDATE issues SET status=%s WHERE hafta=%s RETURNING id, sayi_no",
                (args[2], args[1])).fetchone()
        if r:
            print(f"Sayı {r['sayi_no']} ({args[1]}) → durum '{args[2]}' yapıldı")
        else:
            sys.exit(f"Sayı bulunamadı: {args[1]}")
    else:
        sys.exit(f"Bilinmeyen komut: {args[0]}")
