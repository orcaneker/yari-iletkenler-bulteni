# -*- coding: utf-8 -*-
"""
YARI İLETKEN BÜLTENİ — İNCELEME SERVİSİ (Render Web Service)
===============================================================
Hakem, davet e-postasındaki kişisel linkle gelir:

    GET  /r/{token}                → inceleme arayüzü (HTML kabuk)
    GET  /api/{token}/draft        → taslak JSON + durum
    POST /api/{token}/swap         → {out_id, in_id} öne çıkan ↔ yedek takası
    POST /api/{token}/remove       → {id} haberi yedeğe indir (yerine koymadan)
    POST /api/{token}/lead         → {id} manşeti değiştir
    POST /api/{token}/radar-remove → {kume, url} radar maddesi çıkar
    POST /api/{token}/approve      → TEK onay yeterli → status=approved
                                     yayın saati geçtiyse ANINDA yayınla

Yerel çalıştırma:
    uvicorn review_app.main:app --reload --port 8000
"""

import os
import re
import sys
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

# repo kökünü import yoluna ekle (uvicorn review_app.main:app kökten çalışır)
KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import db                                      # noqa: E402
from config import AYARLAR, KATEGORILER        # noqa: E402

app = FastAPI(title="Yarı İletken Bülteni — İnceleme", docs_url=None, redoc_url=None)

SITE_URL = AYARLAR["site_url"].rstrip("/")

SABLON = (Path(__file__).parent / "templates" / "review.html").read_text(encoding="utf-8")


def _hakem(token):
    h = db.hakem_token_ile(token)
    if not h:
        raise HTTPException(404, "Geçersiz veya pasif inceleme linki")
    return h


def _aktif_sayi():
    """Ekranda gösterilecek sayı: review > approved > published.

    'published' de dahildir çünkü yayınlanmış bültende yazım/çeviri hatası
    düzeltilebilir (düzeltmeler final_json üzerinde yapılır, sonra
    'Düzeltmeleri yayınla' ile GitHub'a gönderilir).
    """
    sayi = (db.issue_getir(status="review")
            or db.issue_getir(status="approved")
            or db.issue_getir(status="published"))
    if not sayi:
        raise HTTPException(404, "İncelenecek taslak yok")
    for alan in ("draft_json", "final_json"):
        if isinstance(sayi.get(alan), str):
            sayi[alan] = json.loads(sayi[alan])
    return sayi


# ============================================================
# GÖVDE NORMALLEŞTİRME
# ------------------------------------------------------------
# draft_json ve final_json yapıları FARKLIDIR:
#   draft : {brief, lead_id, stories[<hepsi, secim alanlı>], radar}
#   final : {brief, lead{...}, stories[<sadece seçilenler>], radar, metrics}
# Arayüzün tek bir biçimle çalışabilmesi için yayınlanmış sayı taslak
# görünümüne çevrilir; düzenleme yapılırken ise asıl gövde üzerinde
# id ile bulunup güncellenir (aşağıdaki _haber_bul).
# ============================================================
def _govde(sayi):
    """Düzenlenecek asıl JSON: yayınlanmışsa final_json, değilse draft_json."""
    if sayi["status"] == "published" and sayi.get("final_json"):
        return sayi["final_json"], "final_json"
    return sayi["draft_json"], "draft_json"


def _gorunum(sayi):
    """Arayüze gönderilecek tek biçimli görünüm (her zaman taslak şeklinde)."""
    govde, tip = _govde(sayi)
    if tip == "draft_json":
        return govde
    lead = govde.get("lead") or {}
    haberler = ([dict(lead, secim="one_cikan")] if lead else []) + \
               [dict(s, secim="one_cikan") for s in (govde.get("stories") or [])]
    # Yayınlanmış gövdede brief maddeleri habere `slug` ile bağlıdır; arayüz
    # her iki durumda da haber id'siyle çalışsın diye `ref`e çevriliyor.
    slug2id = {s.get("slug"): s.get("id") for s in haberler if s.get("slug")}
    brief = [{"text": (m.get("text", "") if isinstance(m, dict) else str(m)),
              "ref": slug2id.get(m.get("slug")) if isinstance(m, dict) else None}
             for m in (govde.get("brief") or [])]
    return {
        "issue": govde.get("issue", {}),
        "brief": brief,
        "lead_id": lead.get("id"),
        "stories": haberler,
        "radar": govde.get("radar", []),
    }


def _haber_bul(govde, tip, hid):
    """id ile haber nesnesini asıl gövdede bulur (final'de lead ayrıdır)."""
    if tip == "draft_json":
        return next((s for s in govde.get("stories", []) if s.get("id") == hid), None)
    lead = govde.get("lead") or {}
    if lead.get("id") == hid:
        return lead
    return next((s for s in govde.get("stories", []) if s.get("id") == hid), None)


def yayin_esigi(created_at):
    """Taslağın yayın anı: oluşturulmasını izleyen Pazartesi 08:00 TSİ
    (= 05:00 UTC). Taslak Pazar günü üretilir → ertesi gün."""
    d = created_at.astimezone(timezone.utc)
    gunler_kalan = (7 - d.weekday()) % 7 or 7      # bir SONRAKİ pazartesi
    pazartesi = (d + timedelta(days=gunler_kalan)).replace(
        hour=5, minute=0, second=0, microsecond=0)
    return pazartesi


@app.get("/")
def saglik():
    return {"servis": "yari-iletken-bulten-inceleme", "durum": "ok"}


@app.get("/r/{token}", response_class=HTMLResponse)
def inceleme_sayfasi(token: str):
    _hakem(token)   # geçersiz token'a HTML bile verme
    return SABLON.replace("__TOKEN__", token)


@app.get("/api/{token}/draft")
def taslak_getir(token: str):
    h = _hakem(token)
    sayi = _aktif_sayi()
    db.logla(sayi["id"], h["ad"], "goruntuledi")
    esik = yayin_esigi(sayi["created_at"])
    return {
        "hakem": h["ad"],
        "status": sayi["status"],
        "sayi_no": sayi["sayi_no"],
        "hafta": sayi["hafta"],
        "approved_by": sayi.get("approved_by"),
        "yayin_aninda": datetime.now(timezone.utc) >= esik,
        "yayin_esigi_utc": esik.isoformat(),
        "kategoriler": {k: v["ad"] for k, v in KATEGORILER.items()},
        # Metin düzeltme her durumda açıktır (yazım/çeviri hatası her aşamada
        # düzeltilebilmeli); yapısal değişiklik yalnızca 'review'da.
        "yapisal_duzenleme": sayi["status"] == "review",
        "site_url": SITE_URL,
        "taslak": _gorunum(sayi),
    }


def _duzenlenebilir():
    """Yapısal değişiklik (takas, çıkarma, manşet, radar) — sadece taslakta."""
    sayi = _aktif_sayi()
    if sayi["status"] != "review":
        raise HTTPException(409, "Bu sayı onaylanmış — yapısal değişiklik yapılamaz "
                                 "(metin düzeltmesi yapılabilir)")
    return sayi


# ============================================================
# METİN DÜZELTME — her aşamada (taslak, onaylı, yayınlanmış)
# ------------------------------------------------------------
# Amaç: çeviri/yazım hatalarını düzeltmek (ör. "diyeze" → "dizel").
# Yayınlanmış sayıda yapılan düzeltme final_json'a yazılır; siteye
# gitmesi için ayrıca /republish çağrılır.
# ============================================================
DUZENLENEBILIR_ALANLAR = {"title", "excerpt", "detail"}


@app.post("/api/{token}/edit")
async def metin_duzelt(token: str, req: Request):
    h = _hakem(token)
    sayi = _aktif_sayi()
    veri = await req.json()
    tip = veri.get("tip", "haber")
    govde, govde_alani = _govde(sayi)

    if tip == "haber":
        hid, alan = veri.get("id"), veri.get("alan")
        deger = (veri.get("deger") or "").strip()
        if alan not in DUZENLENEBILIR_ALANLAR:
            raise HTTPException(400, f"Düzenlenemez alan: {alan}")
        if not deger:
            raise HTTPException(400, "Metin boş olamaz")
        st = _haber_bul(govde, govde_alani, hid)
        if not st:
            raise HTTPException(400, "Haber bulunamadı")
        eski = st.get(alan) or ""
        st[alan] = deger
        detay = {"id": hid, "alan": alan, "eski": eski[:300], "yeni": deger[:300]}

    elif tip == "brief":
        i = veri.get("index")
        deger = (veri.get("deger") or "").strip()
        maddeler = govde.get("brief") or []
        if not isinstance(i, int) or not (0 <= i < len(maddeler)):
            raise HTTPException(400, "Madde bulunamadı")
        if not deger:
            raise HTTPException(400, "Metin boş olamaz")
        eski = maddeler[i].get("text", "") if isinstance(maddeler[i], dict) else str(maddeler[i])
        if isinstance(maddeler[i], dict):
            maddeler[i]["text"] = deger
        else:
            maddeler[i] = {"text": deger, "ref": None}
        detay = {"brief_index": i, "eski": eski[:300], "yeni": deger[:300]}

    elif tip == "radar":
        kume, url = veri.get("kume"), veri.get("url")
        deger = (veri.get("deger") or "").strip()
        if not deger:
            raise HTTPException(400, "Metin boş olamaz")
        madde = next((m for k in (govde.get("radar") or []) if k.get("kume") == kume
                      for m in k.get("maddeler", []) if m.get("url") == url), None)
        if not madde:
            raise HTTPException(400, "Radar maddesi bulunamadı")
        eski = madde.get("title", "")
        madde["title"] = deger
        detay = {"kume": kume, "url": url, "eski": eski[:300], "yeni": deger[:300]}

    else:
        raise HTTPException(400, f"Bilinmeyen düzenleme tipi: {tip}")

    db.govde_guncelle(sayi["id"], govde_alani, govde)
    db.logla(sayi["id"], h["ad"], "metin_duzelt", detay)
    return {"ok": True, "yayinda": sayi["status"] == "published"}


# ============================================================
# GÖRSEL DEĞİŞTİR / KALDIR — her aşamada
# ------------------------------------------------------------
# Boru hattı görseli otomatik seçer ama seçim her zaman isabetli değil:
# birincil kaynağın sayfasında haber görseli yerine kurumun LOGOSU ya da
# genel amaçlı bir STOK görseli durabiliyor. Hakem ya olayın başka bir
# kaynağındaki görseli seçer, ya elle bir URL verir, ya da tamamen kaldırır.
# Metin düzeltmesi gibi yayınlanmış sayıda da çalışır (sonra /republish).
# ============================================================
GORSEL_UZANTILARI = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")


def _gorsel_dogrula(url):
    """URL gerçekten dışarıdan çekilebilen bir görsel mi?

    Hakemin yapıştırdığı adres makale sayfası ya da kırık bağlantı olabilir;
    o zaman haber sitede görselsiz çıkar ve kimse fark etmez. Burada peşinen
    denetlenir. Ağ hatasında KABUL edilir — geçici kesinti yüzünden geçerli
    bir görseli reddetmeyelim.
    """
    if not re.match(r"^https://[^\s]+$", url or ""):
        raise HTTPException(400, "Görsel adresi https:// ile başlamalı")
    try:
        r = requests.get(url, timeout=8, stream=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BultenBot/1.0)",
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        })
        tur = (r.headers.get("content-type") or "").lower()
        r.close()
        if r.status_code != 200:
            raise HTTPException(400, f"Görsel çekilemedi (HTTP {r.status_code})")
        if not tur.startswith("image/"):
            raise HTTPException(
                400, "Bu adres görsel değil (sayfa adresi vermiş olabilirsiniz). "
                     "Görsele sağ tıklayıp “Resim adresini kopyala” deyin.")
    except HTTPException:
        raise
    except Exception:
        if not url.lower().split("?")[0].endswith(GORSEL_UZANTILARI):
            raise HTTPException(400, "Görsel adresine ulaşılamadı")
    return True


@app.post("/api/{token}/image")
async def gorsel_ayarla(token: str, req: Request):
    h = _hakem(token)
    sayi = _aktif_sayi()
    veri = await req.json()
    govde, govde_alani = _govde(sayi)

    st = _haber_bul(govde, govde_alani, veri.get("id"))
    if not st:
        raise HTTPException(400, "Haber bulunamadı")

    eski = (st.get("image") or {}).get("url")
    url = (veri.get("url") or "").strip()

    if not url:                                   # kaldır
        st["image"] = {"url": None, "credit": None, "type": None}
    else:
        _gorsel_dogrula(url)
        st["image"] = {
            "url": url,
            "credit": (veri.get("credit") or "").strip()
            or urlparse(url).netloc.replace("www.", "") or None,
            "type": "hakem",                      # elle seçildi — izlenebilsin
        }

    db.govde_guncelle(sayi["id"], govde_alani, govde)
    db.logla(sayi["id"], h["ad"], "gorsel_degistir",
             {"id": veri.get("id"), "eski": eski, "yeni": url or None})
    return {"ok": True, "image": st["image"],
            "yayinda": sayi["status"] == "published"}


@app.post("/api/{token}/brief-link")
async def brief_baglanti(token: str, req: Request):
    """'60 Saniyede' maddesinin bağlandığı haberi değiştir (veya bağlantıyı kaldır).

    ⚠ İKİ FARKLI ALAN: taslakta madde habere `ref` (haber id'si) ile bağlanır,
    yayınlanmış sayıda ise `slug` ile. Hangi gövde üzerinde çalışıyorsak doğru
    alanı yazıyoruz; yanlışını yazmak bağlantıyı sessizce koparır.
    """
    h = _hakem(token)
    sayi = _aktif_sayi()
    veri = await req.json()
    i, hid = veri.get("index"), veri.get("id")     # id=None → bağlantıyı kaldır
    govde, govde_alani = _govde(sayi)

    maddeler = govde.get("brief") or []
    if not isinstance(i, int) or not (0 <= i < len(maddeler)):
        raise HTTPException(400, "Madde bulunamadı")
    if not isinstance(maddeler[i], dict):
        maddeler[i] = {"text": str(maddeler[i])}

    if hid is None:
        maddeler[i].pop("ref", None)
        maddeler[i].pop("slug", None)
        maddeler[i]["ref" if govde_alani == "draft_json" else "slug"] = None
        db.govde_guncelle(sayi["id"], govde_alani, govde)
        db.logla(sayi["id"], h["ad"], "brief_baglanti", {"index": i, "hedef": None})
        return {"ok": True, "yayinda": sayi["status"] == "published"}

    st = _haber_bul(govde, govde_alani, hid)
    if not st:
        raise HTTPException(400, "Haber bulunamadı")

    if govde_alani == "draft_json":
        maddeler[i]["ref"] = hid
    else:
        if not st.get("slug"):
            raise HTTPException(400, "Haberin slug'ı yok — bağlanamaz")
        maddeler[i]["slug"] = st["slug"]

    db.govde_guncelle(sayi["id"], govde_alani, govde)
    db.logla(sayi["id"], h["ad"], "brief_baglanti",
             {"index": i, "hedef": hid, "baslik": (st.get("title") or "")[:80]})
    return {"ok": True, "yayinda": sayi["status"] == "published"}


@app.post("/api/{token}/swap")
async def takas(token: str, req: Request):
    h = _hakem(token)
    sayi = _duzenlenebilir()
    veri = await req.json()
    out_id, in_id = veri.get("out_id"), veri.get("in_id")

    taslak = sayi["draft_json"]
    stories = {s["id"]: s for s in taslak.get("stories", [])}
    cikan, giren = stories.get(out_id), stories.get(in_id)
    if not cikan or not giren:
        raise HTTPException(400, "Haber bulunamadı")
    if cikan.get("secim") != "one_cikan" or giren.get("secim") != "yedek":
        raise HTTPException(400, "Takas yönü geçersiz (öne çıkan ↔ yedek)")

    cikan["secim"], giren["secim"] = "yedek", "one_cikan"

    # çıkan haber manşetse: manşeti girene devret
    if taslak.get("lead_id") == out_id:
        taslak["lead_id"] = in_id
    # brief çıkan habere işaret ediyorsa ref'i kopar (metin kalır)
    for m in taslak.get("brief", []):
        if m.get("ref") == out_id:
            m["ref"] = None

    db.taslak_guncelle(sayi["id"], taslak)
    db.logla(sayi["id"], h["ad"], "takas", {"cikan": out_id, "giren": in_id})
    return {"ok": True}


@app.post("/api/{token}/remove")
async def cikar(token: str, req: Request):
    """Haberi yedeğe indir. Serbest: tek sınır manşetin çıkarılamamasıdır —
    yani en az manşet kalır. Sayıyı istediğiniz kadar düşürebilirsiniz."""
    h = _hakem(token)
    sayi = _duzenlenebilir()
    veri = await req.json()
    hid = veri.get("id")

    taslak = sayi["draft_json"]
    stories = taslak.get("stories", [])
    st = next((s for s in stories if s["id"] == hid), None)
    if not st or st.get("secim") != "one_cikan":
        raise HTTPException(400, "Haber bulunamadı veya zaten yedekte")
    if taslak.get("lead_id") == hid:
        raise HTTPException(400, "Manşet çıkarılamaz — önce başka bir haberi manşet yapın")

    st["secim"] = "yedek"
    for m in taslak.get("brief", []):
        if m.get("ref") == hid:
            m["ref"] = None

    db.taslak_guncelle(sayi["id"], taslak)
    db.logla(sayi["id"], h["ad"], "cikar", {"id": hid})
    return {"ok": True}


@app.post("/api/{token}/promote")
async def bultene_al(token: str, req: Request):
    """Yedek havuzundaki bir haberi doğrudan bültene ekle (takas gerektirmeden).
    Böylece 10 haberin yanına 4 yedeği de alıp 14'e çıkarabilirsiniz."""
    h = _hakem(token)
    sayi = _duzenlenebilir()
    veri = await req.json()
    hid = veri.get("id")

    taslak = sayi["draft_json"]
    st = next((s for s in taslak.get("stories", []) if s["id"] == hid), None)
    if not st or st.get("secim") == "one_cikan":
        raise HTTPException(400, "Haber bulunamadı veya zaten bültende")
    st["secim"] = "one_cikan"

    db.taslak_guncelle(sayi["id"], taslak)
    db.logla(sayi["id"], h["ad"], "bultene_al", {"id": hid})
    return {"ok": True}


@app.post("/api/{token}/lead")
async def manset(token: str, req: Request):
    h = _hakem(token)
    sayi = _duzenlenebilir()
    veri = await req.json()
    hid = veri.get("id")

    taslak = sayi["draft_json"]
    st = next((s for s in taslak.get("stories", []) if s["id"] == hid), None)
    if not st:
        raise HTTPException(400, "Haber bulunamadı")
    st["secim"] = "one_cikan"
    taslak["lead_id"] = hid

    db.taslak_guncelle(sayi["id"], taslak)
    db.logla(sayi["id"], h["ad"], "manset", {"id": hid})
    return {"ok": True}


@app.post("/api/{token}/radar-remove")
async def radar_cikar(token: str, req: Request):
    h = _hakem(token)
    sayi = _duzenlenebilir()
    veri = await req.json()
    kume, url = veri.get("kume"), veri.get("url")

    taslak = sayi["draft_json"]
    for k in taslak.get("radar", []):
        if k.get("kume") == kume:
            once = len(k.get("maddeler", []))
            k["maddeler"] = [m for m in k.get("maddeler", []) if m.get("url") != url]
            if len(k["maddeler"]) == once:
                raise HTTPException(400, "Radar maddesi bulunamadı")
            break
    else:
        raise HTTPException(400, "Küme bulunamadı")
    taslak["radar"] = [k for k in taslak["radar"] if k.get("maddeler")]

    db.taslak_guncelle(sayi["id"], taslak)
    db.logla(sayi["id"], h["ad"], "radar_cikar", {"kume": kume, "url": url})
    return {"ok": True}


@app.post("/api/{token}/approve")
async def onayla(token: str):
    """TEK onay yeterli. Yayın eşiği (Pazartesi 08:00 TSİ) geçtiyse
    bekletmeden ANINDA yayınla; geçmediyse Cron 2 yayınlar."""
    h = _hakem(token)
    sayi = _aktif_sayi()
    if sayi["status"] != "review":
        return {"ok": True, "durum": "zaten-onayli",
                "onaylayan": sayi.get("approved_by")}

    if not db.onayla(sayi["id"], h["ad"]):
        raise HTTPException(409, "Onay kaydedilemedi — sayfayı yenileyin")
    db.logla(sayi["id"], h["ad"], "onay")

    esik = yayin_esigi(sayi["created_at"])
    if datetime.now(timezone.utc) >= esik:
        _yayin_baslat(sayi["id"], h["ad"])      # geç onay → arka planda hemen yayınla
        return {"ok": True, "durum": "yayinlaniyor"}

    return {"ok": True, "durum": "onaylandi",
            "yayin": "Pazartesi 08:00 TSİ'de otomatik yayınlanacak"}


# ============================================================
# YAYIN İŞLERİ — arka planda çalışır, arayüz durumu yoklar
# ------------------------------------------------------------
# ⚠ NEDEN ARKA PLAN: Yayın işlemi ses üretimi + GitHub klon/push içerir ve
# 30-90 sn sürebilir; ücretsiz Render servisi ayrıca uykudan uyanıyorsa
# üstüne ~50 sn biner. Senkron yapılsaydı tarayıcı zaman aşımına düşer,
# yönetici "hata" görürken işlem aslında tamamlanmış olurdu. Bu yüzden iş
# hemen başlatılıp durum /yayin-durum ile yoklanır.
# Aynı anda tek iş çalışır (çift yayın/çift push olmasın).
# ============================================================
YAYIN_DURUMU = {"calisiyor": False, "tur": None, "url": None,
                "hata": None, "kim": None}
_yayin_kilidi = threading.Lock()


def _is_baslat(tur, kim, hedef):
    with _yayin_kilidi:
        if YAYIN_DURUMU["calisiyor"]:
            raise HTTPException(409, "Bir yayın işlemi zaten sürüyor — birkaç saniye bekleyin")
        YAYIN_DURUMU.update(calisiyor=True, tur=tur, url=None, hata=None, kim=kim)

    def calistir():
        try:
            url = hedef()
            with _yayin_kilidi:
                YAYIN_DURUMU.update(calisiyor=False, url=url, hata=None)
        except Exception as e:
            with _yayin_kilidi:
                YAYIN_DURUMU.update(calisiyor=False, url=None, hata=str(e)[:400])

    threading.Thread(target=calistir, daemon=True).start()


def _yayin_baslat(issue_id, kim):
    """Onaylı sayıyı arka planda yayınlar (tam yayın: ses + arşiv + push)."""
    def is_():
        import publish
        s = db.issue_getir(issue_id=issue_id)
        if isinstance(s["draft_json"], str):
            s["draft_json"] = json.loads(s["draft_json"])
        return publish.yayinla(s)
    _is_baslat("yayin", kim, is_)


@app.post("/api/{token}/publish")
async def hemen_yayinla(token: str):
    """'Şimdi yayınla' — onaylı sayıyı Pazartesi 08:00'i beklemeden yayınlar.
    Yöneticinin Render'a girmesine gerek kalmaz."""
    h = _hakem(token)
    sayi = _aktif_sayi()
    if sayi["status"] == "published":
        return {"ok": True, "durum": "zaten-yayinda"}
    if sayi["status"] != "approved":
        raise HTTPException(409, "Önce bülteni onaylayın")
    db.logla(sayi["id"], h["ad"], "elle_yayin")
    _yayin_baslat(sayi["id"], h["ad"])
    return {"ok": True, "durum": "yayinlaniyor"}


@app.post("/api/{token}/republish")
async def duzeltmeleri_yayinla(token: str):
    """Yayınlanmış sayıda yapılan metin düzeltmelerini siteye gönderir."""
    h = _hakem(token)
    sayi = _aktif_sayi()
    if sayi["status"] != "published":
        raise HTTPException(409, "Bu sayı henüz yayınlanmadı")
    final = sayi.get("final_json")
    if not final:
        raise HTTPException(409, "Yayınlanmış içerik bulunamadı")
    db.logla(sayi["id"], h["ad"], "duzeltme_yayini")

    def is_():
        import publish
        return publish.duzeltme_yayinla(final)
    _is_baslat("duzeltme", h["ad"], is_)
    return {"ok": True, "durum": "yayinlaniyor"}


@app.get("/api/{token}/yayin-durum")
def yayin_durumu(token: str):
    _hakem(token)
    with _yayin_kilidi:
        return dict(YAYIN_DURUMU)
