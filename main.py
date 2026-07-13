# -*- coding: utf-8 -*-
"""
YARI İLETKEN BÜLTENİ — ANA PIPELINE
====================================
Akış:
  1. Durum (state) yükle  → Render diski geçici olduğu için CANLI SİTEDEN çekilir
  2. Exa ile tara         → 12 sorgu × ek sorgular
  3. Normalize + dedup    → URL temizliği, görülmüş olayları ele
  4. Aşama 1: Haiku       → olay kümeleme, eleme, puanlama
  5. Aşama 2: Sonnet      → Türkçe bülten yazımı
  6. Doğrula + inşa et    → dist/ (latest.json, arşiv, index, feed.xml)
  7. Deploy + e-posta raporu

Çalıştırma:  python main.py
Test (deploysuz):  python main.py --dry-run
"""

import os
import re
import sys
import json
import time
import hashlib
import smtplib
import argparse
import unicodedata
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests

from config import (
    AYARLAR, KATEGORILER, SORGULAR, FIYAT,
    KAYNAK_TIER1, KAYNAK_TIER2, KAYNAK_AKADEMIK, KAYNAK_TURKIYE, KAYNAK_DISLA,
)
import prompts

# ============================================================
# ORTAM DEĞİŞKENLERİ
# ============================================================
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
RAPOR_ALICI = os.environ.get("RAPOR_ALICI", "")

# Sesli bülten (ElevenLabs) — anahtar yoksa sessizce atlanır
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")

# Deploy: docs/ klasörü GitHub'a push edilir
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")      # ör. orcan/yari-iletken-bulteni
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")    # Personal Access Token (Contents: RW)
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

EXA_URL = "https://api.exa.ai/search"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

OUT = AYARLAR["cikti_dizini"]
SITE_URL = AYARLAR["site_url"].rstrip("/")

LOG = []
YASAKLI_DOMAINLER = set()   # Exa'nın lisans nedeniyle reddettiği alan adları

# Token muhasebesi — model bazında birikir, çalışma raporuna yazılır
KULLANIM = {}


def kullanim_ekle(model, u):
    k = KULLANIM.setdefault(model, {"in": 0, "out": 0, "cache_w": 0, "cache_r": 0,
                                    "cagri": 0})
    k["in"] += u.get("input_tokens", 0)
    k["out"] += u.get("output_tokens", 0)
    k["cache_w"] += u.get("cache_creation_input_tokens", 0)
    k["cache_r"] += u.get("cache_read_input_tokens", 0)
    k["cagri"] += 1


def maliyet_raporu():
    satirlar, toplam = [], 0.0
    for model, k in KULLANIM.items():
        f = FIYAT.get(model)
        if not f:
            satirlar.append(f"  {model}: fiyat bilinmiyor")
            continue
        m = (k["in"] * f["in"] + k["out"] * f["out"]
             + k["cache_w"] * f["cache_w"] + k["cache_r"] * f["cache_r"]) / 1_000_000
        toplam += m
        satirlar.append(
            f"  {model}  ({k['cagri']} çağrı)\n"
            f"    girdi {k['in']:,} · çıktı {k['out']:,} · "
            f"cache yaz {k['cache_w']:,} · cache oku {k['cache_r']:,}\n"
            f"    ≈ ${m:.3f}"
        )
    satirlar.append(f"  ── TOPLAM ≈ ${toplam:.3f}")
    return "\n".join(satirlar), toplam


def log(msg):
    satir = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
    print(satir, flush=True)
    LOG.append(satir)


# ============================================================
# YARDIMCILAR
# ============================================================
IZLEME_PARAMLARI = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
    "__twitter_impression", "amp", "s", "spm",
}


def url_normalize(url: str) -> str:
    """UTM/AMP/mobil varyantları temizle → deduplikasyonun temeli."""
    try:
        p = urlparse(url.strip())
        netloc = p.netloc.lower()
        for on_ek in ("www.", "m.", "amp."):
            if netloc.startswith(on_ek):
                netloc = netloc[len(on_ek):]
        path = re.sub(r"/amp/?$", "", p.path).rstrip("/") or "/"
        q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in IZLEME_PARAMLARI]
        return urlunparse(("https", netloc, path, "", urlencode(q), ""))
    except Exception:
        return url


def domain_of(url: str) -> str:
    try:
        d = urlparse(url).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = s.replace("ı", "i").replace("İ", "i").replace("ğ", "g").replace("ş", "s")
    s = s.replace("ö", "o").replace("ü", "u").replace("ç", "c")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:70] or "olay"


def temizle(metin):
    """Kontrol karakterlerini ayıkla — JSON parse hatalarının başlıca sebebi."""
    if not isinstance(metin, str):
        return metin
    metin = metin.replace("\u00a0", " ").replace("\u200b", "")
    return "".join(c for c in metin if c == "\n" or c == "\t" or ord(c) >= 32)


def kaynak_tier(domain: str) -> int:
    if any(domain.endswith(d) for d in KAYNAK_TIER1):
        return 1
    if any(domain.endswith(d) for d in KAYNAK_TIER2 + KAYNAK_TURKIYE):
        return 2
    if any(domain.endswith(d) for d in KAYNAK_AKADEMIK):
        return 2
    return 3


def iso_hafta(d: datetime):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# ============================================================
# 1) DURUM (STATE) — Render diski geçici, state canlı siteden çekilir
# ============================================================
def state_yukle():
    yol = f"{SITE_URL}/data/state/seen_events.json"
    try:
        r = requests.get(yol, timeout=20)
        if r.status_code == 200:
            s = r.json()
            log(f"State yüklendi: {len(s.get('events', []))} olay, "
                f"{len(s.get('urls', []))} URL")
            return s
    except Exception as e:
        log(f"State çekilemedi ({e}) — sıfırdan başlıyor")
    return {"issue_no": 0, "events": [], "urls": []}


def state_guncelle(state, yeni_olaylar, yeni_urller):
    """Son 8 haftalık hafızayı tut — dosya şişmesin."""
    state["events"] = (state.get("events", []) + yeni_olaylar)[-400:]
    state["urls"] = list(dict.fromkeys((state.get("urls", []) + yeni_urller)))[-3000:]
    return state


# ============================================================
# 2) EXA TARAMA
# ============================================================
def domain_listesi(setler):
    m = {"tier1": KAYNAK_TIER1, "tier2": KAYNAK_TIER2,
         "akademik": KAYNAK_AKADEMIK, "turkiye": KAYNAK_TURKIYE}
    out = []
    for s in setler:
        out += m.get(s, [])
    out = [d for d in dict.fromkeys(out) if d not in YASAKLI_DOMAINLER]
    return out


def exa_ara(sorgu, dom_dahil, bas_tarih, bit_tarih, sonuc, konum=None):
    payload = {
        "query": sorgu,
        "type": AYARLAR["exa_tip"],
        "category": "news",
        "numResults": sonuc,
        "startPublishedDate": bas_tarih,
        "endPublishedDate": bit_tarih,
        "excludeDomains": KAYNAK_DISLA,
        "contents": {
            "text": {"maxCharacters": AYARLAR["exa_metin_karakter"]},
            "highlights": {"maxCharacters": 1000, "query": sorgu},
        },
    }
    if dom_dahil:
        payload["includeDomains"] = dom_dahil
    if konum:
        payload["userLocation"] = konum

    for deneme in range(3):
        try:
            r = requests.post(
                EXA_URL,
                headers={"x-api-key": EXA_API_KEY, "Content-Type": "application/json"},
                json=payload, timeout=60,
            )
            if r.status_code == 200:
                return r.json().get("results", [])

            # 403 "domains are not available" → Exa bazı alan adlarını lisans
            # nedeniyle filtrede kabul etmiyor (ör. reuters.com, bloomberg.com).
            # Bunları ayıkla ve aynı sorguyu tekrar dene. Kendini onarma.
            if r.status_code == 403 and "not available" in r.text:
                yasakli = re.findall(r"([a-z0-9.-]+\.[a-z]{2,})", r.text.split("not available:")[-1])
                yeni = [d for d in payload.get("includeDomains", []) if d not in yasakli]
                if yasakli and yeni != payload.get("includeDomains"):
                    for d in yasakli:
                        YASAKLI_DOMAINLER.add(d)
                    payload["includeDomains"] = yeni
                    log(f"  Exa yasaklı alan adı ayıklandı: {', '.join(yasakli)}")
                    continue

            log(f"  Exa {r.status_code}: {r.text[:160]}")
        except Exception as e:
            log(f"  Exa hata ({deneme+1}/3): {e}")
        time.sleep(3 * (deneme + 1))
    return []


def tara(pencere_gun):
    """Tüm sorguları çalıştır, ham adayları topla."""
    bugun = datetime.now(timezone.utc)
    bit = bugun.strftime("%Y-%m-%dT23:59:59Z")

    adaylar, hatali_sorgu = [], []
    gorulmus = set()

    for s in SORGULAR:
        gun = s.get("pencere_gun", pencere_gun)
        bas = (bugun - timedelta(days=gun)).strftime("%Y-%m-%dT00:00:00Z")
        doms = domain_listesi(s["domain_seti"])
        tum_sorgular = [s["sorgu"]] + s.get("ek_sorgular", [])

        bulunan = 0
        for q in tum_sorgular:
            sonuclar = exa_ara(
                q, doms, bas, bit,
                s.get("sonuc", AYARLAR["exa_sonuc_sayisi"]),
                s.get("kullanici_konumu"),
            )
            if not sonuclar:
                hatali_sorgu.append(f"{s['id']} :: {q[:40]}")
            for r in sonuclar:
                url = url_normalize(r.get("url", ""))
                if not url or url in gorulmus:
                    continue
                gorulmus.add(url)
                tam = temizle(r.get("text") or "")
                one = " … ".join(r.get("highlights") or [])
                adaylar.append({
                    "id": f"c{len(adaylar):04d}",
                    "title": temizle(r.get("title") or "")[:220],
                    "url": url,
                    "domain": domain_of(url),
                    "published_date": (r.get("publishedDate") or "")[:10] or None,
                    "author": r.get("author"),
                    "image": r.get("image"),
                    # triyaj için kısa parça (ucuz) — yazım için TAM metin (detay buradan gelir)
                    "snippet": (temizle(one) or tam)[:AYARLAR["exa_triyaj_karakter"]],
                    "text": tam[:AYARLAR["exa_metin_karakter"]],
                    "sorgu_id": s["id"],
                    "kategori_ipucu": s["kategori"],
                })
                bulunan += 1
        log(f"  {s['id']:<10} → {bulunan} sonuç")

    return adaylar, hatali_sorgu


# ============================================================
# 3) DETERMİNİSTİK ELEME
# ============================================================
def on_eleme(adaylar, state):
    gorulmus_url = set(state.get("urls", []))
    kalan, elenen = [], 0
    baslik_hash = set()

    for a in adaylar:
        if a["url"] in gorulmus_url:
            elenen += 1
            continue
        h = hashlib.md5(slugify(a["title"])[:50].encode()).hexdigest()
        if h in baslik_hash:
            elenen += 1
            continue
        baslik_hash.add(h)
        a["tier"] = kaynak_tier(a["domain"])
        kalan.append(a)

    log(f"Deterministik eleme: {elenen} elendi, {len(kalan)} kaldı")
    return kalan, elenen


# ============================================================
# 4-5) LLM ÇAĞRILARI
# ============================================================
def claude(model, sistem, kullanici, max_tokens, stream=False):
    """Claude API çağrısı.

    stream=True → token'lar akarak gelir. UZUN çıktılarda ZORUNLU:
    akışsız istekte bağlantı 300 sn'de zaman aşımına uğrayıp ölüyor
    (Read timed out). Bülten yazımı 5 dakikadan uzun sürebiliyor.

    temperature BİLEREK gönderilmiyor — model uyumsuzluk sorunu.
    """
    # Sistem promptunu cache'le — aynı prompt tekrar tekrar gönderiliyor
    # (Haiku triyajı 8 partide çağrılıyor). Cache okuma ~%90 daha ucuz.
    if AYARLAR.get("prompt_cache"):
        sistem_blok = [{"type": "text", "text": sistem,
                        "cache_control": {"type": "ephemeral"}}]
    else:
        sistem_blok = sistem

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": sistem_blok,
        "messages": [{"role": "user", "content": kullanici}],
    }
    if stream:
        body["stream"] = True

    basliklar = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    for deneme in range(4):
        try:
            if not stream:
                r = requests.post(ANTHROPIC_URL, headers=basliklar, json=body, timeout=300)
                if r.status_code == 200:
                    d = r.json()
                    kullanim_ekle(model, d.get("usage", {}))
                    return "".join(b.get("text", "") for b in d.get("content", [])
                                   if b.get("type") == "text")
                log(f"  Claude {r.status_code}: {r.text[:200]}")
                if r.status_code in (429, 529, 500, 502, 503):
                    time.sleep(15 * (deneme + 1))
                    continue
                break

            # ── STREAMING ──
            parcalar = []
            u = {}
            with requests.post(ANTHROPIC_URL, headers=basliklar, json=body,
                               stream=True, timeout=(30, 120)) as r:
                if r.status_code != 200:
                    log(f"  Claude {r.status_code}: {r.text[:200]}")
                    if r.status_code in (429, 529, 500, 502, 503):
                        time.sleep(15 * (deneme + 1))
                        continue
                    break

                for satir in r.iter_lines(decode_unicode=True):
                    if not satir or not satir.startswith("data: "):
                        continue
                    veri = satir[6:]
                    if veri.strip() == "[DONE]":
                        break
                    try:
                        olay = json.loads(veri)
                    except Exception:
                        continue
                    tip = olay.get("type")
                    if tip == "content_block_delta":
                        d = olay.get("delta", {})
                        if d.get("type") == "text_delta":
                            parcalar.append(d.get("text", ""))
                    elif tip == "message_start":
                        u.update(olay.get("message", {}).get("usage", {}) or {})
                    elif tip == "message_delta":
                        u.update(olay.get("usage", {}) or {})
                    elif tip == "error":
                        raise RuntimeError(olay.get("error", {}).get("message", "stream hatası"))

            if parcalar:
                kullanim_ekle(model, u)
                log(f"  Stream tamam — {sum(len(p) for p in parcalar)} karakter · "
                    f"girdi {u.get('input_tokens', 0):,} / çıktı {u.get('output_tokens', 0):,}")
                return "".join(parcalar)
            log("  Stream boş döndü")

        except Exception as e:
            log(f"  Claude hata ({deneme+1}/4): {e}")
            time.sleep(10 * (deneme + 1))

    raise RuntimeError("Claude API başarısız")


def json_ayikla(metin):
    """Model ```json bloğu veya önsöz eklerse kurtar."""
    metin = temizle(metin).strip()
    metin = re.sub(r"^```(?:json)?\s*", "", metin)
    metin = re.sub(r"\s*```$", "", metin)
    bas, son = metin.find("{"), metin.rfind("}")
    if bas == -1 or son == -1:
        raise ValueError("JSON bulunamadı")
    return json.loads(metin[bas:son + 1])


def triyaj(adaylar, bas, bit, state):
    """Aşama 1 — Haiku ile olay kümeleme."""
    onceki = [e.get("baslik_ozet", "") for e in state.get("events", [])]
    olaylar, reject = [], []
    B = AYARLAR["triyaj_batch"]

    for i in range(0, len(adaylar), B):
        parti = adaylar[i:i + B]
        log(f"  Triyaj partisi {i//B + 1} ({len(parti)} aday)")
        try:
            cikti = claude(
                AYARLAR["model_triyaj"], prompts.TRIYAJ_PROMPT,
                prompts.triyaj_kullanici_mesaji(parti, bas, bit, onceki),
                AYARLAR["max_tokens_triyaj"],
            )
            d = json_ayikla(cikti)
            olaylar += d.get("events", [])
            reject += d.get("reject", [])
        except Exception as e:
            log(f"  ! Triyaj partisi başarısız: {e}")

    # Aynı event_key birden fazla partide çıkabilir → birleştir
    birlesik = {}
    for o in olaylar:
        k = o.get("event_key") or slugify(o.get("baslik_ozet", ""))
        if k in birlesik:
            birlesik[k]["supporting_ids"] = list(dict.fromkeys(
                birlesik[k].get("supporting_ids", []) + o.get("supporting_ids", [])
            ))
            birlesik[k]["puan"] = max(birlesik[k].get("puan", 0), o.get("puan", 0))
        else:
            o["event_key"] = k
            birlesik[k] = o

    sonuc = sorted(birlesik.values(), key=lambda x: x.get("puan", 0), reverse=True)
    log(f"Triyaj: {len(sonuc)} olay, {len(reject)} reddedildi")
    return sonuc, reject


def olaylari_zenginlestir(olaylar, adaylar):
    """Olaylara kaynak metinlerini bağla (Sonnet'in göreceği içerik)."""
    idx = {a["id"]: a for a in adaylar}
    zengin = []
    for o in olaylar:
        pid = o.get("primary_id")
        ids = ([pid] if pid else []) + (o.get("supporting_ids") or [])
        kaynaklar = []
        for i, aid in enumerate(dict.fromkeys(ids)):
            a = idx.get(aid)
            if not a:
                continue
            kaynaklar.append({
                "name": a["domain"],
                "domain": a["domain"],
                "url": a["url"],
                "published_date": a["published_date"],
                "text": a.get("text") or a["snippet"],
                "image": a.get("image"),
                "tier": a["tier"],
                "primary": i == 0,
            })
        if not kaynaklar:
            continue
        o["kaynaklar"] = kaynaklar
        zengin.append(o)
    return zengin


def yaz(derin, radar_havuz, sayi_no, bas, bit, pencere):
    """Aşama 2 — Sonnet ile bülten yazımı."""
    cikti = claude(
        AYARLAR["model_yazim"], prompts.YAZIM_PROMPT,
        prompts.yazim_kullanici_mesaji(derin, radar_havuz, sayi_no, bas, bit, pencere),
        AYARLAR["max_tokens_yazim"],
        stream=True,     # ← uzun çıktı: zaman aşımını önler
    )
    return json_ayikla(cikti)


# ============================================================
# 6) DOĞRULAMA
# ============================================================
def dogrula(b):
    """Şema doğrulama + Python tarafında slug/metrik/brief-bağ üretimi.

    Slug ve metrikler MODELDEN İSTENMİYOR: deterministik hesaplanır.
    Böylece uydurma rakam ve slug çakışması imkânsız hale gelir.
    """
    hatalar = []
    if not b.get("lead"):
        hatalar.append("lead yok")
    n = len(b.get("stories") or [])
    if n < 5:
        hatalar.append(f"stories az ({n})")
    if len(b.get("brief") or []) != 5:
        hatalar.append("brief 5 madde değil")

    tum = [x for x in [b.get("lead")] + (b.get("stories") or []) if x]

    # --- slug üretimi (benzersizleştirilmiş) ---
    gorulen = set()
    for st in tum:
        sl = slugify(st.get("title", ""))
        temel, i = sl, 2
        while sl in gorulen:
            sl = f"{temel}-{i}"
            i += 1
        gorulen.add(sl)
        st["slug"] = sl
        st["neden_onemli"] = None          # analiz katmanı şimdilik kapalı

    # --- şema kontrolü ---
    for st in tum:
        for alan in ("title", "excerpt", "detail", "category", "source"):
            if not st.get(alan):
                hatalar.append(f"'{(st.get('title') or '?')[:30]}' → {alan} eksik")
        if st.get("category") not in KATEGORILER:
            hatalar.append(f"geçersiz kategori: {st.get('category')}")

    # --- brief bağları: model 'ref' (story id) verir → slug'a çevir ---
    id2slug = {st.get("id"): st["slug"] for st in tum if st.get("id")}
    yeni_brief = []
    for m in (b.get("brief") or []):
        if isinstance(m, str):
            yeni_brief.append({"text": m, "slug": None})
        else:
            yeni_brief.append({
                "text": m.get("text", ""),
                "slug": id2slug.get(m.get("ref") or m.get("slug")),
            })
    b["brief"] = yeni_brief

    # --- METRİKLER: modelden değil, veriden hesaplanır ---
    yatirim = 0
    for st in tum:
        inv = st.get("investment") or {}
        v = inv.get("amount_usd_million")
        if isinstance(v, (int, float)):
            yatirim += v
    fab_kat = {"yatirim", "guc", "paketleme", "bellek"}
    fab_asama = {"announced", "funded", "construction",
                 "equipment_install", "mass_production"}
    ulkeler = {u for st in tum for u in (st.get("countries") or [])}
    b["metrics"] = {
        "aciklanan_yatirim_usd_milyon": round(yatirim) or None,
        "fab_proje_sayisi": sum(
            1 for st in tum
            if st.get("category") in fab_kat and st.get("maturity") in fab_asama
        ) or None,
        "politika_gelismesi": sum(
            1 for st in tum if st.get("category") == "politika"
        ) or None,
        "kapsanan_ulke": len(ulkeler) or None,
    }
    return hatalar


# ============================================================
# 7) İNŞA — dist/
# ============================================================
def yaz_json(yol, veri):
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)


def rss_uret(sayilar, son):
    def esc(s):
        return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))
    ogeler = []
    for s in [son.get("lead")] + (son.get("stories") or []):
        if not s:
            continue
        ogeler.append(f"""  <item>
    <title>{esc(s['title'])}</title>
    <link>{SITE_URL}/#/haber/{esc(s['slug'])}</link>
    <guid isPermaLink="false">{esc(s['slug'])}</guid>
    <pubDate>{esc(s.get('published_date'))}</pubDate>
    <category>{esc(KATEGORILER.get(s['category'], {}).get('ad'))}</category>
    <description>{esc(s['excerpt'])}</description>
  </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Yarı İletken Bülteni</title>
  <link>{SITE_URL}</link>
  <description>Haftalık yarı iletken sektörü ve politika izleme bülteni</description>
  <language>tr</language>
  <lastBuildDate>{datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>
{chr(10).join(ogeler)}
</channel></rss>"""


def insa_et(bulten, state, sayilar):
    os.makedirs(f"{OUT}/data/arsiv", exist_ok=True)
    os.makedirs(f"{OUT}/data/state", exist_ok=True)

    hafta = bulten["issue"]["hafta"]
    yaz_json(f"{OUT}/data/latest.json", bulten)
    yaz_json(f"{OUT}/data/arsiv/{hafta}.json", bulten)
    yaz_json(f"{OUT}/data/index.json", sayilar)
    yaz_json(f"{OUT}/data/state/seen_events.json", state)

    with open(f"{OUT}/feed.xml", "w", encoding="utf-8") as f:
        f.write(rss_uret(sayilar, bulten))

    # GitHub Pages'in Jekyll işlemesini kapat (yoksa bazı dosyalar yok sayılır)
    open(f"{OUT}/.nojekyll", "w").close()

    # Statik site dosyaları
    for dosya in ("index.html", "arsiv.html"):
        if os.path.exists(f"site/{dosya}"):
            with open(f"site/{dosya}", encoding="utf-8") as src, \
                 open(f"{OUT}/{dosya}", "w", encoding="utf-8") as dst:
                dst.write(src.read())

    # Görsel/ses varlıkları (hero videosu, sesli bülten — sonradan)
    if os.path.isdir("assets"):
        import shutil
        shutil.copytree("assets", f"{OUT}/assets", dirs_exist_ok=True)

    log(f"dist/ hazır — sayı {bulten['issue']['number']} ({hafta})")


def arsiv_indeksi(state, bulten):
    """Mevcut index.json'u canlı siteden çek, yeni sayıyı ekle."""
    try:
        r = requests.get(f"{SITE_URL}/data/index.json", timeout=20)
        sayilar = r.json() if r.status_code == 200 else []
    except Exception:
        sayilar = []
    i = bulten["issue"]
    sayilar = [s for s in sayilar if s["hafta"] != i["hafta"]]
    sayilar.append({
        "number": i["number"],
        "hafta": i["hafta"],
        "publication_date": i["publication_date"],
        "coverage_start": i["coverage_start"],
        "coverage_end": i["coverage_end"],
        "lead_title": bulten["lead"]["title"],
        "story_count": len(bulten.get("stories", [])),
        "radar_count": sum(len(k.get("maddeler", [])) for k in bulten.get("radar", [])),
        "file": f"data/arsiv/{i['hafta']}.json",
    })
    return sorted(sayilar, key=lambda s: s["number"], reverse=True)


# ============================================================
# 7.5) SESLİ BÜLTEN — "Bu Hafta 60 Saniyede" (ElevenLabs)
#      Sadece brief seslendirilir (~700 karakter/hafta).
#      Anahtar yoksa veya hata olursa bülten yine yayımlanır, audio null kalır.
# ============================================================
AY_TR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
         "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
SIRA = ["Bir", "İki", "Üç", "Dört", "Beş", "Altı", "Yedi"]


def ses_metni(bulten):
    """TTS için okunabilir metin. Parantez içi İngilizce terimler ayıklanır."""
    i = bulten["issue"]
    d = datetime.strptime(i["publication_date"], "%Y-%m-%d")
    satirlar = [
        f"Yarı İletken Bülteni. {d.day} {AY_TR[d.month - 1]} {d.year}, sayı {i['number']}.",
        "Bu hafta altmış saniyede.",
    ]
    for n, m in enumerate(bulten.get("brief", [])):
        t = m.get("text", "") if isinstance(m, dict) else str(m)
        t = re.sub(r"\s*\([^)]*\)", "", t).strip()   # "(advanced packaging)" → sil
        t = re.sub(r"\s{2,}", " ", t)
        if t:
            satirlar.append(f"{SIRA[n] if n < len(SIRA) else n + 1}. {t}")
    satirlar.append("Ayrıntılar bültende.")
    return "\n".join(satirlar)


def ses_uret(bulten):
    if not ELEVENLABS_API_KEY:
        log("Ses atlandı (ELEVENLABS_API_KEY yok)")
        return None

    metin = ses_metni(bulten)
    hafta = bulten["issue"]["hafta"]
    log(f"Ses üretiliyor — {len(metin)} karakter")

    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
            f"?output_format=mp3_44100_128",
            headers={"xi-api-key": ELEVENLABS_API_KEY,
                     "Content-Type": "application/json"},
            json={
                "text": metin,
                "model_id": ELEVENLABS_MODEL,
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.75,
                                   "style": 0.0, "use_speaker_boost": True},
            },
            timeout=180,
        )
        if r.status_code != 200:
            log(f"ElevenLabs {r.status_code}: {r.text[:200]}")
            return None

        os.makedirs(f"{OUT}/assets/audio", exist_ok=True)
        yol = f"{OUT}/assets/audio/{hafta}.mp3"
        with open(yol, "wb") as f:
            f.write(r.content)

        sure = round(len(r.content) / 16000)   # 128 kbps ≈ 16 KB/sn
        bulten["issue"]["audio"] = {
            "url": f"assets/audio/{hafta}.mp3",
            "duration_sec": sure,
            "voice": ELEVENLABS_VOICE_ID,
            "chars": len(metin),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        log(f"Ses hazır: {yol} (~{sure} sn, {len(r.content)//1024} KB)")
        return yol
    except Exception as e:
        log(f"Ses hatası: {e}")
        return None


# ============================================================
# 8) DEPLOY — docs/ klasörünü GitHub'a push et
#    Cloudflare Pages repo'yu izler, push'u görünce otomatik yayınlar.
# ============================================================
def deploy(sayi_no):
    if not (GITHUB_REPO and GITHUB_TOKEN):
        log("Deploy atlandı (GITHUB_REPO / GITHUB_TOKEN yok)")
        return None

    import shutil
    import tempfile
    import subprocess

    tmp = tempfile.mkdtemp()
    uzak = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"

    def git(*args, kontrol=True):
        r = subprocess.run(["git", "-C", tmp, *args],
                           capture_output=True, text=True)
        if kontrol and r.returncode != 0:
            raise RuntimeError(f"git {args[0]}: {r.stderr[:200]}")
        return r

    try:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "-b", GITHUB_BRANCH, uzak, tmp],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"clone: {r.stderr[:200]}")

        hedef = os.path.join(tmp, OUT)
        shutil.rmtree(hedef, ignore_errors=True)
        shutil.copytree(OUT, hedef)

        git("config", "user.email", "bulten-bot@users.noreply.github.com")
        git("config", "user.name", "Bulten Bot")
        git("add", "-A")

        c = git("commit", "-m", f"Sayı {sayi_no} — otomatik yayın", kontrol=False)
        if c.returncode != 0 and "nothing to commit" in (c.stdout + c.stderr):
            log("Değişiklik yok — push atlandı")
            return SITE_URL

        git("push", "origin", GITHUB_BRANCH)
        log(f"GitHub push başarılı → Cloudflare Pages derlemeye başlayacak")
        return SITE_URL
    except Exception as e:
        log(f"Deploy hatası: {e}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================
# 9) ÇALIŞMA RAPORU (e-posta)
# ============================================================
def rapor_gonder(rapor, bulten, hatalar):
    if not (SMTP_USER and SMTP_PASS and RAPOR_ALICI):
        log("E-posta atlandı (SMTP ayarı yok)")
        return
    top3 = "\n".join(
        f"  {i+1}. [{s.get('score','?')}] {s['title']}"
        for i, s in enumerate([bulten["lead"]] + bulten["stories"][:2])
    )
    maliyet_metni, toplam_maliyet = maliyet_raporu()
    govde = f"""Yarı İletken Bülteni — Sayı {bulten['issue']['number']} Çalışma Raporu
{'=' * 52}
Kapsam        : {bulten['issue']['coverage_start']} — {bulten['issue']['coverage_end']}
Pencere       : {bulten['issue']['window_days']} gün

Sorgu çalıştırıldı : {rapor['queries_run']}
Ham sonuç          : {rapor['results_found']}
Deterministik elenen: {rapor['dedup_removed']}
Olay oluşturuldu   : {rapor['events_created']}
LLM reddetti       : {rapor['llm_rejected']}
Yayımlanan (öne çıkan): {rapor['published']}
Radar maddesi      : {rapor['radar_items']}

Exa'nın reddettiği alan adları: {', '.join(sorted(YASAKLI_DOMAINLER)) or '(yok)'}

Başarısız sorgular : {len(rapor['failed_queries'])}
{chr(10).join('  - ' + q for q in rapor['failed_queries']) or '  (yok)'}

Sesli bülten       : {(bulten['issue'].get('audio') or {}).get('duration_sec', '—')} sn / {(bulten['issue'].get('audio') or {}).get('chars', '—')} karakter

TOKEN VE MALİYET
{maliyet_metni}

Şema hataları      : {len(hatalar)}
{chr(10).join('  ! ' + h for h in hatalar) or '  (yok)'}

En yüksek puanlı 3:
{top3}

Deploy: {rapor.get('deploy_url') or 'YAPILMADI'}
{'=' * 52}
LOG:
{chr(10).join(LOG[-40:])}
"""
    m = MIMEText(govde, "plain", "utf-8")
    m["Subject"] = f"Yarı İletken Bülteni — Sayı {bulten['issue']['number']} Raporu"
    m["From"], m["To"] = SMTP_USER, RAPOR_ALICI
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(m)
        log("Çalışma raporu gönderildi")
    except Exception as e:
        log(f"E-posta hatası: {e}")


# ============================================================
# ANA AKIŞ
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="deploy ve e-posta yok")
    args = ap.parse_args()

    if not EXA_API_KEY or not ANTHROPIC_API_KEY:
        sys.exit("HATA: EXA_API_KEY ve ANTHROPIC_API_KEY gerekli")

    t0 = time.time()
    bugun = datetime.now(timezone.utc)
    log("═" * 46)
    log(f"YARI İLETKEN BÜLTENİ — {bugun.strftime('%Y-%m-%d')}")

    state = state_yukle()
    sayi_no = state.get("issue_no", 0) + 1

    # --- Tarama (7 gün → yetersizse 14 gün) ---
    pencere = AYARLAR["pencere_gun"]
    log(f"Exa taraması ({pencere} gün)…")
    adaylar, hatali = tara(pencere)
    log(f"Ham sonuç: {len(adaylar)}")

    if len(adaylar) < 40:
        pencere = AYARLAR["pencere_genis_gun"]
        log(f"Yetersiz — pencere {pencere} güne genişletiliyor")
        adaylar, hatali = tara(pencere)
        log(f"Ham sonuç: {len(adaylar)}")

    ham_sayi = len(adaylar)
    adaylar, elenen = on_eleme(adaylar, state)
    if not adaylar:
        sys.exit("HATA: eleme sonrası aday kalmadı")

    kapsam_bas = (bugun - timedelta(days=pencere)).strftime("%Y-%m-%d")
    kapsam_bit = bugun.strftime("%Y-%m-%d")

    # --- Aşama 1: triyaj ---
    log("Aşama 1 — Haiku triyaj…")
    olaylar, reject = triyaj(adaylar, kapsam_bas, kapsam_bit, state)
    olaylar = olaylari_zenginlestir(olaylar, adaylar)

    # En yüksek puanlı N olay TAM METİNLE gider (manşet + öne çıkan havuzu),
    # kalanlar sadece başlık/link olarak radar adayı olur → token bütçesi korunur,
    # yazılacak haberler ise makalenin TAMAMINI görür.
    D = AYARLAR["derin_olay_sayisi"]
    T = AYARLAR["toplam_olay_sayisi"]
    derin, radar_havuz = olaylar[:D], olaylar[D:T]
    log(f"Sonnet'e giden: {len(derin)} derin (tam metin) + {len(radar_havuz)} radar adayı")

    # --- Aşama 2: yazım ---
    log("Aşama 2 — Sonnet yazım…")
    b = yaz(derin, radar_havuz, sayi_no, kapsam_bas, kapsam_bit, pencere)

    bulten = {
        "issue": {
            "number": sayi_no,
            "hafta": iso_hafta(bugun),
            "publication_date": bugun.strftime("%Y-%m-%d"),
            "coverage_start": kapsam_bas,
            "coverage_end": kapsam_bit,
            "window_days": pencere,
            "audio": None,   # ← sesli bülten (ElevenLabs) buraya gelecek
        },
        "brief": b.get("brief", []),
        "metrics": b.get("metrics", {}),
        "lead": b.get("lead"),
        "stories": b.get("stories", []),
        "radar": b.get("radar", []),
    }

    hatalar = dogrula(bulten)
    if hatalar:
        log(f"⚠ {len(hatalar)} şema uyarısı")
        for h in hatalar[:10]:
            log(f"  ! {h}")

    # --- State + arşiv ---
    yayimlanan = [bulten["lead"]] + bulten["stories"]
    yeni_urller = [s["source"]["url"] for s in yayimlanan if s.get("source")]
    for k in bulten.get("radar", []):
        yeni_urller += [m["url"] for m in k.get("maddeler", []) if m.get("url")]
    yeni_olaylar = [{"baslik_ozet": s["title"], "hafta": bulten["issue"]["hafta"]}
                    for s in yayimlanan]
    state = state_guncelle(state, yeni_olaylar, [url_normalize(u) for u in yeni_urller])
    state["issue_no"] = sayi_no

    if not args.dry_run:
        ses_uret(bulten)          # issue.audio alanını doldurur

    sayilar = arsiv_indeksi(state, bulten)
    insa_et(bulten, state, sayilar)

    rapor = {
        "queries_run": sum(1 + len(s.get("ek_sorgular", [])) for s in SORGULAR),
        "results_found": ham_sayi,
        "dedup_removed": elenen,
        "events_created": len(olaylar),
        "llm_rejected": len(reject),
        "published": len(bulten["stories"]) + 1,
        "radar_items": sum(len(k.get("maddeler", [])) for k in bulten.get("radar", [])),
        "failed_queries": hatali,
        "deploy_url": None,
    }

    if not args.dry_run:
        rapor["deploy_url"] = deploy(sayi_no)
        rapor_gonder(rapor, bulten, hatalar)
    else:
        log("DRY RUN — deploy ve e-posta atlandı")

    mm, mt = maliyet_raporu()
    log("TOKEN VE MALİYET")
    for satir in mm.split("\n"):
        log(satir)
    log(f"Tamamlandı — {time.time() - t0:.0f} sn · tahmini maliyet ${mt:.3f}")
    log("═" * 46)


if __name__ == "__main__":
    main()
