# -*- coding: utf-8 -*-
"""
YARI İLETKEN BÜLTENİ — TASLAK PIPELINE (CRON 1 — Pazar 12:30 TSİ)
====================================================================
Akış:
  1. Durum (state) yükle       → canlı siteden (Render diski geçici)
  2. Exa ile tara              → 12 sorgu × ek sorgular
  3. Normalize + dedup         → URL temizliği, görülmüş olay elemesi
  4. Aşama 1: triyaj modeli    → olay kümeleme, eleme, puanlama
  5. Aşama 2: yazım modeli     → 14 derin olayın TAMAMI tam haber
                                  (one_cikan + yedek) + radar + brief
  6. Doğrula + görsel bağla    → taslak JSON
  7. Neon'a kaydet (review)    → Resend ile hakemlere davet
  8. Çalışma raporu e-postası

Çalıştırma:
  python pipeline.py                    # tam akış
  python pipeline.py --dry-run          # DB/e-posta yok; taslak_preview.json üretir
  python pipeline.py --mock             # Exa/LLM yok; sahte taslakla DB+davet testi
  python pipeline.py --mock --dry-run   # tamamen çevrimdışı test
"""

import os
import re
import html as html_mod
import sys
import json
import time
import hashlib
import argparse
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests

from config import (
    AYARLAR, KATEGORILER, SORGULAR, OLGUNLUK,
    KAYNAK_TIER1, KAYNAK_TIER2, KAYNAK_AKADEMIK, KAYNAK_TURKIYE, KAYNAK_DISLA,
    KAYNAK_ODEME_DUVARI, ODEME_DUVARI_IZLERI, ODEME_DUVARI_MIN_KARAKTER,
    TEYIT, DURAK_KELIMELER, FIYAT, EXA_FIYAT,
)
import prompts
import llm

EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
REVIEW_BASE_URL = os.environ.get("REVIEW_BASE_URL", "").rstrip("/")
RAPOR_ALICI = os.environ.get("RAPOR_ALICI", "")
# Tanımlıysa yazım adımı bu modelde de çalıştırılıp sonuç e-postayla
# karşılaştırılır. Yayınlanan bülten etkilenmez. Örn: openai:gpt-5.6-luna
KARSILASTIR_MODEL = os.environ.get("KARSILASTIR_MODEL", "").strip()
# Tanımlıysa taslak KAYDEDİLMEZ ve davet GÖNDERİLMEZ; yalnızca karşılaştırma
# e-postası atılır. Model denemesini tekrarlarken incelemedeki taslağı ezmemek
# ve diğer yöneticilere mükerrer davet göndermemek için.
KIYAS_MODU = os.environ.get("SADECE_KARSILASTIR", "").strip().lower() \
    not in ("", "0", "false", "hayir")

EXA_URL = "https://api.exa.ai/search"
SITE_URL = AYARLAR["site_url"].rstrip("/")

LOG = []
YASAKLI_DOMAINLER = set()   # Exa'nın lisans nedeniyle reddettiği alan adları

# ── EXA KULLANIM SAYACI ──────────────────────────────────────────
# "deneme"  : API'ye giden HER istek (başarısızlar ve yeniden denemeler dahil).
#             ⚠ Fatura bunu takip ediyor: 403 sonrası yasaklı alan adı ayıklanıp
#             atılan tekrar istek de ücretlendiriliyor. Yalnızca 200'leri saymak
#             faturayı olduğundan DÜŞÜK gösteriyordu (48 sayılırken fatura ~72).
# "cagri"   : 200 dönen istekler (kaç tanesi işe yaradı).
# "ek_sonuc": her istekte 10'u aşan sonuç adedi (taban ücret ilk 10'u kapsar).
# "bildirilen": Exa yanıtta maliyet bildiriyorsa (costDollars) toplanır —
#             o zaman tahmin yerine GERÇEK tutar raporlanır.
EXA_KULLANIM = {"deneme": 0, "cagri": 0, "sonuc": 0, "ek_sonuc": 0,
                "bildirilen": 0.0, "bildirim_var": False}


def _exa_bildirilen_maliyet(veri):
    """Exa yanıtındaki maliyet alanını bul (varsa). Şema değişirse sessizce None."""
    for anahtar in ("costDollars", "cost_dollars", "cost"):
        d = veri.get(anahtar)
        if isinstance(d, (int, float)):
            return float(d)
        if isinstance(d, dict):
            for alt in ("total", "totalDollars", "amount"):
                if isinstance(d.get(alt), (int, float)):
                    return float(d[alt])
    return None


def exa_maliyet():
    """(rapor metni, tutar) — Exa arama maliyeti.

    Exa yanıtta maliyet bildiriyorsa GERÇEK tutar kullanılır; bildirmiyorsa
    yayınlanmış fiyat listesinden tahmin edilir (o zaman 'tahmin' diye yazar).
    """
    k = EXA_KULLANIM
    taban = k["deneme"] * EXA_FIYAT["arama"]      # fatura denemeleri sayıyor
    ek = k["ek_sonuc"] * EXA_FIYAT["ek_sonuc"]
    tahmin = taban + ek
    basarisiz = k["deneme"] - k["cagri"]

    satirlar = [
        f"  exa.ai arama ({k['deneme']} istek"
        + (f", {basarisiz} yeniden deneme/hatalı" if basarisiz else "")
        + f" · {k['sonuc']:,} sonuç)",
        f"    taban {k['deneme']}×${EXA_FIYAT['arama']:.4f} = ${taban:.3f} · "
        f"ek sonuç {k['ek_sonuc']:,}×${EXA_FIYAT['ek_sonuc']:.4f} = ${ek:.3f}",
    ]
    if k["bildirim_var"]:
        satirlar.append(f"    = ${k['bildirilen']:.3f}  (Exa'nın bildirdiği GERÇEK tutar; "
                        f"liste fiyatı tahmini ${tahmin:.3f})")
        return "\n".join(satirlar), k["bildirilen"]
    satirlar.append(f"    ≈ ${tahmin:.3f}  (tahmin — Exa yanıtta tutar bildirmiyor; "
                    f"kesin rakam exa.ai panelinde)")
    return "\n".join(satirlar), tahmin


def log(msg):
    satir = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
    print(satir, flush=True)
    LOG.append(satir)


llm.set_logger(log)


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


# Her koşulda reddedilenler — bunlar haber fotoğrafı OLAMAZ.
GORSEL_RED_KESIN = (
    "/logo", "-logo", "_logo", "logo.", "favicon", "placeholder",
    "og-default", "og_default", "default-image", "1x1", "/pixel",
    "spacer", "amp-logo", "site-logo", "header-logo", "publisher-logo",
    "sprite", "/icons/", "-icon.", "_icon.",
    # kurumsal/jenerik marka kartları (haber fotoğrafı DEĞİL): resmî sitelerin
    # fotoğrafsız basın bültenlerinde koyduğu markalı OG görselleri. Örn. gov.uk
    # "govuk-opengraph-image-….png" ve "s300_GOV.UK__12_.png" gibi numaralı kartlar.
    "opengraph-image", "gov.uk__", "govuk-opengraph", "default-og", "generic-og",
    # reklam kuşakları — Exa bazen makale görseli sanıp bunları veriyor.
    # Gerçek vaka: Green Queen haberine "Green-Queen-Wire-Banner-Ad.png" bağlandı.
    "banner-ad", "banner_ad", "wire-banner", "/ads/", "advertisement", "-advert",
)

# ⚠ Yalnızca dosya adı KISA ve jenerikse reddedilir.
# Birçok yayın, makalenin paylaşım kartını makalenin KENDİ slug'ıyla
# adlandırıyor — bu kart makalenin gerçek görselidir. Gerçek vaka:
# Green Queen'in og:image'ı ".../ferments-du-futur-food-fermentation-project-
# funding-france-social.png" idi; eski liste "-social" izini gördüğü için
# bunu paylaşım ikonu sanıp eledi ve haberler görselsiz yayınlandı.
# Kısa "social.png" / "share-thumb.png" ise gerçekten ikondur.
GORSEL_JENERIK = ("social", "share", "thumb", "avatar")
# Jenerik sözcük dosya adına HÂKİM mi? Ham uzunluk eşiği kırılgandı:
# "ferments-du-futur-social" tam 24 karakter olduğu için gerçek bir makale
# görseli elenebiliyordu. Artık jenerik sözcükleri düşüp KALAN harflere
# bakıyoruz — "social" tek başınaysa hiçbir şey kalmaz (ikon), makale
# slug'ı varsa çok şey kalır (gerçek görsel).
GORSEL_JENERIK_ASGARI_KALAN = 6
_BOYUT_EKI = re.compile(r"[-_]\d{2,4}x\d{2,4}$")
_UZANTI = re.compile(r"\.(jpe?g|png|webp|gif|avif|bmp)$")


def gorsel_gecerli(u):
    """Yalnızca KESİN logo/reklam/placeholder işaretlerini ele; kararsızsa KORU."""
    if not u or not isinstance(u, str):
        return False
    if not u.lower().startswith("http"):
        return False
    ul = u.lower().split("?")[0]
    if ul.endswith(".svg"):
        return False
    if any(x in ul for x in GORSEL_RED_KESIN):
        return False
    ad = _BOYUT_EKI.sub("", _UZANTI.sub("", ul.rsplit("/", 1)[-1]))
    # ⚠ Kurumsal logolar her zaman "-logo"/"_logo" biçiminde adlandırılmıyor;
    # camelCase de yaygın. Gerçek vaka (biyoekonomi Sayı 2): Biomass
    # Magazine'in Montana Renewables haberinin og:image'ı
    # "MontanaRenewablesLogo_1683754971.jpg" idi — 665x665 kare bir logo.
    # Kesin liste ("-logo", "_logo", "logo.") bunu yakalamıyordu.
    # Yayında kullanılan 38 görselin hiçbirinin adında "logo" geçmiyor,
    # yani koşulsuz eleme gerçek fotoğrafları etkilemiyor.
    if "logo" in ad:
        return False
    if any(x in ad for x in GORSEL_JENERIK):
        kalan = ad
        for t in GORSEL_JENERIK:
            kalan = kalan.replace(t, "")
        if len(re.sub(r"[^a-z0-9çğıöşü]", "", kalan)) < GORSEL_JENERIK_ASGARI_KALAN:
            return False
    return True


def gorsel_sec(r):
    """Exa sonucundan gerçek haber görseli çıkar; şüpheliyse None."""
    ex = r.get("extras") or {}
    for u in (ex.get("imageLinks") or []):
        if gorsel_gecerli(u):
            return u
    if gorsel_gecerli(r.get("image")):
        return r["image"]
    return None


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
    metin = metin.replace(chr(160), " ").replace(chr(8203), "")
    return "".join(c for c in metin if c == "\n" or c == "\t" or ord(c) >= 32)


def odeme_duvarli(domain: str, metin: str) -> bool:
    if any(domain.endswith(d) for d in KAYNAK_ODEME_DUVARI):
        return True
    m = (metin or "").lower()
    if any(iz in m for iz in ODEME_DUVARI_IZLERI):
        return True
    if len(metin or "") < ODEME_DUVARI_MIN_KARAKTER:
        return True
    return False


def kaynak_tier(domain: str) -> int:
    if any(domain.endswith(d) for d in KAYNAK_TIER1):
        return 1
    if any(domain.endswith(d) for d in KAYNAK_TIER2 + KAYNAK_TURKIYE):
        return 2
    if any(domain.endswith(d) for d in KAYNAK_AKADEMIK):
        return 2
    return 3


def iso_hafta(d: datetime):
    """Sayının hafta kimliği — ör. '2026-H31' (2026'nın 31. haftası).

    H = Hafta. ISO 8601'in 'W' (week) harfi yerine Türkçe karşılığı
    kullanılıyor; hafta numarası yine ISO 8601 takvimine göre hesaplanır.

    ⚠ Bu değer yalnızca ekranda görünen bir etiket DEĞİLDİR; aynı zamanda
    arşiv dosyası adı (data/arsiv/<hafta>.json), sesli özet dosyası adı,
    kalıcı bağlantı (?hafta=…) ve veritabanındaki UNIQUE anahtardır.
    Formatı değiştirmek yayınlanmış sayıların bağlantılarını kırar —
    değiştirilecekse arşiv boşken yapılmalıdır.
    """
    y, w, _ = d.isocalendar()
    return f"{y}-H{w:02d}"


_KACIS_HARITASI = {"\n": "\\n", "\r": "\\r", "\t": "\\t",
                   "\b": "\\b", "\f": "\\f"}


def _kontrol_kacir(govde):
    """JSON dizeleri İÇİNDEKİ ham kontrol karakterlerini kaçışla.

    Dize dışındaki boşluklara dokunulmaz (JSON'da geçerlidirler); yalnızca
    tırnak içinde kalan U+0000-001F aralığı kaçışlanır. Bu dönüşüm kayıpsızdır:
    metnin kendisi değişmez, yalnızca JSON'a uygun biçimde yazılır.
    """
    cikti, dize_icinde, kacis = [], False, False
    for ch in govde:
        if kacis:                       # önceki karakter ters bölüydü
            cikti.append(ch)
            kacis = False
        elif ch == "\\":
            cikti.append(ch)
            kacis = dize_icinde
        elif ch == '"':
            dize_icinde = not dize_icinde
            cikti.append(ch)
        elif dize_icinde and ch < " ":
            cikti.append(_KACIS_HARITASI.get(ch, f"\\u{ord(ch):04x}"))
        else:
            cikti.append(ch)
    return "".join(cikti)


def json_ayikla(metin):
    """Model ```json bloğu veya önsöz eklerse kurtar.

    LLM'ler uzun JSON'da ara sıra kaçışsız tırnak / eksik virgül üretir
    (haber metinlerinde alıntı geçince tipik). Katı parse başarısızsa
    json_repair ile onarılır — bu kütüphane tam bu iş için yazılmıştır.
    """
    metin = temizle(metin).strip()
    metin = re.sub(r"^```(?:json)?\s*", "", metin)
    metin = re.sub(r"\s*```$", "", metin)
    bas, son = metin.find("{"), metin.rfind("}")
    if bas == -1 or son == -1:
        raise ValueError("JSON bulunamadı")
    govde = metin[bas:son + 1]
    try:
        return json.loads(govde)
    except json.JSONDecodeError as e:
        # ── 1) Ham kontrol karakteri onarımı ──
        # Sonnet 5 uzun metinlerde dize İÇİNE kaçışsız satır başı/sekme
        # koyabiliyor → "Invalid control character". json_repair bu durumda
        # bazen gövdenin tamamını değil yalnızca ilk birkaç kaydı kurtarıyor;
        # gerçek vaka (Sayı 2): 14 haberden 5'i kurtarıldı, radar tamamen
        # kayboldu, kalanın yerine modelin yer tutucusu kaldı.
        # Bu kaçışlama deterministik ve kayıpsız — json_repair'e düşmeden önce
        # denenir.
        try:
            d = json.loads(_kontrol_kacir(govde))
            log(f"  ⚠ JSON'da kaçışsız kontrol karakteri vardı — onarıldı ({e})")
            return d
        except json.JSONDecodeError:
            pass
        # ── 2) Son çare: json_repair (kayıplı olabilir) ──
        log(f"  ⚠ JSON hatalı ({e}) — json_repair ile onarılıyor")
        from json_repair import repair_json
        onarik = repair_json(govde, return_objects=True)
        if isinstance(onarik, dict) and onarik:
            return onarik
        raise


# ============================================================
# 1) STATE — canlı siteden
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


def son_sayi_no(state):
    """Yayınlanmış son sayı numarası — sayacın tek doğruluk kaynağı.

    ⚠ NEDEN SADECE STATE'E GÜVENİLMEZ: state canlı siteden HTTP ile çekilir;
    istek başarısız olursa issue_no=0 döner ve sayı numarası 1'e geri düşer
    (arşivde mükerrer numara oluşur). docs/data/arsiv/*.json git'te tutulduğu
    için Render her çalışmada klonladığında yayınlanmış tüm sayılar yerelde
    hazırdır ve ağa bağımlı değildir.

    İkisinin BÜYÜĞÜ alınır: yerel arşiv otoriterdir, state ise arşiv dosyası
    henüz commit edilmemiş bir ara durumu yakalayabilir.
    """
    en_buyuk = 0
    dizin = os.path.join(AYARLAR["cikti_dizini"], "data", "arsiv")
    if os.path.isdir(dizin):
        for ad in os.listdir(dizin):
            if not ad.endswith(".json"):
                continue
            try:
                with open(os.path.join(dizin, ad), encoding="utf-8") as f:
                    n = (json.load(f).get("issue") or {}).get("number")
                if isinstance(n, int):
                    en_buyuk = max(en_buyuk, n)
            except Exception as e:
                log(f"  ⚠ arşiv dosyası okunamadı ({ad}): {e}")
    state_no = state.get("issue_no", 0) or 0
    if en_buyuk != state_no:
        log(f"  Sayaç: yerel arşiv {en_buyuk} · canlı state {state_no} "
            f"→ {max(en_buyuk, state_no)} kabul edildi")
    return max(en_buyuk, state_no)


# ============================================================
# 2) EXA TARAMA
# ============================================================
def domain_listesi(setler):
    m = {"tier1": KAYNAK_TIER1, "tier2": KAYNAK_TIER2,
         "akademik": KAYNAK_AKADEMIK, "turkiye": KAYNAK_TURKIYE}
    out = []
    for s in setler:
        out += m.get(s, [])
    return [d for d in dict.fromkeys(out) if d not in YASAKLI_DOMAINLER]


def exa_ara(sorgu, dom_dahil, bas_tarih, bit_tarih, sonuc, konum=None, ek_disla=None):
    payload = {
        "query": sorgu,
        "type": AYARLAR["exa_tip"],
        "category": "news",
        "numResults": sonuc,
        "startPublishedDate": bas_tarih,
        "endPublishedDate": bit_tarih,
        "excludeDomains": KAYNAK_DISLA + list(ek_disla or []),
        "contents": {
            "text": {"maxCharacters": AYARLAR["exa_metin_karakter"]},
            "highlights": {"maxCharacters": 1000, "query": sorgu},
            "extras": {"imageLinks": 2},   # görsel için AÇIKÇA istenmeli
        },
    }
    if dom_dahil:
        payload["includeDomains"] = dom_dahil
    if konum:
        payload["userLocation"] = konum

    for deneme in range(3):
        try:
            EXA_KULLANIM["deneme"] += 1     # fatura her isteği sayıyor
            r = requests.post(
                EXA_URL,
                headers={"x-api-key": EXA_API_KEY, "Content-Type": "application/json"},
                json=payload, timeout=60,
            )
            if r.status_code == 200:
                veri = r.json()
                sonuclar = veri.get("results", [])
                EXA_KULLANIM["cagri"] += 1
                EXA_KULLANIM["sonuc"] += len(sonuclar)
                EXA_KULLANIM["ek_sonuc"] += max(0, len(sonuclar) - 10)
                bildirilen = _exa_bildirilen_maliyet(veri)
                if bildirilen is not None:
                    EXA_KULLANIM["bildirilen"] += bildirilen
                    if not EXA_KULLANIM["bildirim_var"]:
                        EXA_KULLANIM["bildirim_var"] = True
                        log(f"  Exa gerçek maliyet bildiriyor — tahmin yerine o kullanılacak")
                return sonuclar

            # 403 "domains are not available" → Exa bazı alan adlarını lisans
            # nedeniyle kabul etmiyor. Ayıkla ve tekrar dene (kendini onarma).
            if r.status_code == 403 and "not available" in r.text:
                yasakli = re.findall(r"([a-z0-9.-]+\.[a-z]{2,})",
                                     r.text.split("not available:")[-1])
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
                    "max_yas_gun": gun,   # bu sorgunun izin verdiği azami yaş
                    "published_date": (r.get("publishedDate") or "")[:10] or None,
                    "author": r.get("author"),
                    "image": gorsel_sec(r),
                    "snippet": (temizle(one) or tam)[:AYARLAR["exa_triyaj_karakter"]],
                    "text": tam[:AYARLAR["exa_metin_karakter"]],
                    "paywall": odeme_duvarli(domain_of(url), tam),
                    "sorgu_id": s["id"],
                    "kategori_ipucu": s["kategori"],
                })
                bulunan += 1
        log(f"  {s['id']:<14} → {bulunan} sonuç")

    return adaylar, hatali_sorgu


# ============================================================
# 2.5) TEYİT ARAMASI — duvarlı olaya erişilebilir kaynak bul
# ============================================================
def _kelimeler(baslik):
    t = (baslik or "").lower()
    t = re.sub(r"[^a-z0-9çğıöşü\s]", " ", t)
    return {k for k in t.split() if len(k) >= 4 and k not in DURAK_KELIMELER}


def benzerlik(a, b):
    A, B = _kelimeler(a), _kelimeler(b)
    if not A or not B:
        return 0.0, 0
    ortak = A & B
    return len(ortak) / len(A | B), len(ortak)


def teyit_ara(olaylar, adaylar):
    """Tüm kaynakları duvarlı olan olaylar için erişilebilir kaynak ara.
    Bulunursa olay yazılabilir hale gelir ama 'ikinci_el' işaretlenir."""
    if not TEYIT.get("aktif"):
        return 0

    hedefler = [o for o in olaylar if o.get("sadece_radar")][:TEYIT["max_olay"]]
    if not hedefler:
        return 0

    log(f"Teyit araması — {len(hedefler)} duvarlı olay")
    bulunan = 0
    mevcut_urller = {a["url"] for a in adaylar}

    for o in hedefler:
        k0 = o["kaynaklar"][0]
        baslik = o.get("baslik_ozet") or k0["name"]

        try:
            d0 = datetime.strptime(k0.get("published_date") or "", "%Y-%m-%d")
        except Exception:
            d0 = datetime.now(timezone.utc).replace(tzinfo=None)
        tol = TEYIT["gun_toleransi"]
        bas = (d0 - timedelta(days=tol)).strftime("%Y-%m-%dT00:00:00Z")
        bit = (d0 + timedelta(days=tol)).strftime("%Y-%m-%dT23:59:59Z")

        sonuclar = exa_ara(baslik, None, bas, bit, TEYIT["sonuc"],
                           ek_disla=KAYNAK_ODEME_DUVARI)

        en_iyi, en_iyi_skor = None, 0.0
        for r in sonuclar:
            url = url_normalize(r.get("url", ""))
            metin = temizle(r.get("text") or "")
            if not url or len(metin) < TEYIT["min_metin"]:
                continue
            if odeme_duvarli(domain_of(url), metin):
                continue
            skor, ortak = benzerlik(baslik, r.get("title") or "")
            if skor < TEYIT["min_benzerlik"] or ortak < TEYIT["min_ortak_kelime"]:
                continue
            if skor > en_iyi_skor:
                en_iyi, en_iyi_skor = (r, url, metin), skor

        if not en_iyi:
            continue

        r, url, metin = en_iyi
        yeni = {
            "name": domain_of(url), "domain": domain_of(url), "url": url,
            "published_date": (r.get("publishedDate") or "")[:10] or None,
            "text": metin[:AYARLAR["exa_metin_karakter"]],
            "image": gorsel_sec(r),
            "tier": kaynak_tier(domain_of(url)),
            "paywall": False, "primary": True,
        }
        for k in o["kaynaklar"]:
            k["primary"] = False
        o["kaynaklar"].insert(0, yeni)
        o["sadece_radar"] = False
        o["ikinci_el"] = True
        bulunan += 1
        if url not in mevcut_urller:
            adaylar.append({
                "id": f"t{len(adaylar):04d}", "title": r.get("title") or "",
                "url": url, "domain": domain_of(url),
                "published_date": yeni["published_date"], "image": gorsel_sec(r),
                "snippet": metin[:AYARLAR["exa_triyaj_karakter"]], "text": yeni["text"],
                "paywall": False, "tier": yeni["tier"],
            })
        log(f"  ✓ teyit ({en_iyi_skor:.2f}): {domain_of(url)} ← {baslik[:50]}")

    log(f"Teyit: {bulunan}/{len(hedefler)} olay kurtarıldı")
    return bulunan


# ============================================================
# 3) DETERMİNİSTİK ELEME
# ============================================================
def on_eleme(adaylar, state):
    """Görülmüş URL + başlık tekrarı + TARİH DİSİPLİNİ.

    ⚠ Tarih filtresi DETERMİNİSTİKTİR ve LLM'e bırakılmaz: Exa'nın tarih
    parametreleri bazen eski/tarihsiz sonuç sızdırıyor (2025'ten kalma
    haberler görüldü). Yayın tarihi olmayan veya sorgusunun penceresinden
    (7 gün) yaşlı her aday burada, LLM'e hiç
    gitmeden elenir. Haftalık bültenin tarih güvencesi bu satırlardır.
    """
    gorulmus_url = set(state.get("urls", []))
    bugun = datetime.now(timezone.utc).date()
    kalan, elenen, tarih_elenen = [], 0, 0
    baslik_hash = set()

    for a in adaylar:
        pd = a.get("published_date")
        if not pd:
            tarih_elenen += 1          # tarihi doğrulanamayan aday bültene giremez
            continue
        try:
            yas = (bugun - datetime.strptime(pd, "%Y-%m-%d").date()).days
        except ValueError:
            tarih_elenen += 1
            continue
        # +1 gün tolerans: saat dilimi farkları; negatif alt sınır: "gelecek
        # tarihli" bozuk veriyi de ele
        if yas > a.get("max_yas_gun", AYARLAR["pencere_gun"]) + 1 or yas < -1:
            tarih_elenen += 1
            continue
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

    log(f"Deterministik eleme: tarih dışı {tarih_elenen} + tekrar {elenen} elendi, "
        f"{len(kalan)} kaldı")
    return kalan, elenen + tarih_elenen


# ============================================================
# 4) AŞAMA 1 — TRİYAJ
# ============================================================
def triyaj(adaylar, bas, bit, state):
    onceki = [e.get("baslik_ozet", "") for e in state.get("events", [])]
    olaylar, reject = [], []
    B = AYARLAR["triyaj_batch"]

    # Sistem bloğu her partide AYNI → cache'lenir (Anthropic tarafında).
    sistem = prompts.TRIYAJ_PROMPT + prompts.onceki_olaylar_bloku(onceki)

    for i in range(0, len(adaylar), B):
        parti = adaylar[i:i + B]
        log(f"  Triyaj partisi {i//B + 1} ({len(parti)} aday)")
        try:
            cikti = llm.llm_cagri(
                AYARLAR["model_triyaj"], sistem,
                prompts.triyaj_kullanici_mesaji(parti, bas, bit),
                AYARLAR["max_tokens_triyaj"],
                cache=True,
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


# ============================================================
# 4.5) OLAY BİRLEŞTİRME — partiler arası mükerrer temizliği
# ------------------------------------------------------------
# ⚠ triyaj() adayları PARTİLER halinde işler; kümeleme her partinin
# İÇİNDE olur. Ayrı partilere düşen iki haber aynı olayı anlatsa bile
# model onları hiç birlikte görmez. Parti sonrası birleştirme de yalnızca
# event_key dizgisi birebir aynıysa çalışıyordu — farklı anahtar üreten
# iki kayıt yan yana durmaya devam ediyordu.
# Gerçek vaka (yarı iletken, Sayı 1): Samsung–Broadcom anlaşması ve AB
# yapay zeka giga fabrikaları ikişer kez haber oldu; 12 haberin 2'si
# tekrardı ve yatırım metriği çift sayıyordu.
#
# İki katman:
#   1. KESİN — ortak aday kaynağı ya da aynı birincil URL: LLM'e sorulmaz.
#   2. ADAY  — şirket örtüşmesi + başlık benzerliği eşik üstü çiftler
#              TEK bir küçük isteme konur (tam metin yok, sadece özetler).
# ============================================================
BIRLESTIRME_AZAMI_OLAY = 80          # tek isteme konacak azami olay sayısı
BIRLESTIRME_AZAMI_KUME = 4           # bundan büyük grup = tema gruplaması şüphesi


def _olay_sirketler(o):
    return {s.lower().strip() for s in (o.get("sirketler") or []) if len(s) >= 3}


def _kesin_ayni(a, b):
    """LLM'e sormaya gerek olmayan durumlar."""
    ids_a = set([a.get("primary_id")] + list(a.get("supporting_ids") or [])) - {None}
    ids_b = set([b.get("primary_id")] + list(b.get("supporting_ids") or [])) - {None}
    return bool(ids_a & ids_b)


def _ayirt_edici_sayilar(o):
    """Olayın özetindeki AYIRT EDİCİ sayılar (biçimden arındırılmış).

    Ayırt edici = en az 4 basamaklı ve YIL DEĞİL. "5 milyon", "%3", "2026"
    gibi değerler onlarca haberde geçer ve birleştirme sinyali taşımaz;
    "23731" (crore rupi) ya da "700000" (ton/yıl) pratikte tek bir olaya aittir.
    Para birimi çevrimi bu izi bozmaz: iki yayın "USD 2.5bn" ve "US$2.7bn"
    yazsa bile ikisi de rupi tutarını aktarıyorsa iz tutar.
    """
    ham = re.findall(r"\d[\d.,]*", o.get("baslik_ozet") or "")
    izler = set()
    for h in ham:
        s = h.rstrip(".,").replace(".", "").replace(",", "").lstrip("0")
        if len(s) >= 4 and not (1900 <= int(s) <= 2100 if s.isdigit() else False):
            izler.add(s)
    return izler


def _ortak_sinyal(a, b):
    """İki olayın aynı olabilmesi için asgari örtüşme.

    LLM kararının üstüne konan ucuz emniyet kemeri: model yanlışlıkla
    alakasız iki haberi gruplarsa (tema gruplaması) burada elenir.
    Yanlış birleştirme İKİ haberi birden yok ettiği için bu denetim var.
    """
    if _olay_sirketler(a) & _olay_sirketler(b):
        return True
    ulke_a = {u.lower().strip() for u in (a.get("ulkeler") or [])}
    ulke_b = {u.lower().strip() for u in (b.get("ulkeler") or [])}
    if ulke_a & ulke_b:
        return True
    return bool(a.get("kategori")) and a.get("kategori") == b.get("kategori")


def _birlestir_cift(tutulan, atilan):
    """atilan'ı tutulan'a kat: kaynakları birleştir, puanı yükselt."""
    ids = list(dict.fromkeys(
        list(tutulan.get("supporting_ids") or [])
        + ([atilan.get("primary_id")] if atilan.get("primary_id") else [])
        + list(atilan.get("supporting_ids") or [])))
    tutulan["supporting_ids"] = [i for i in ids if i != tutulan.get("primary_id")]
    tutulan["puan"] = max(tutulan.get("puan") or 0, atilan.get("puan") or 0)
    for alan in ("sirketler", "ulkeler"):
        tutulan[alan] = list(dict.fromkeys(
            (tutulan.get(alan) or []) + (atilan.get(alan) or [])))
    if not tutulan.get("yatirim_usd_milyon"):
        tutulan["yatirim_usd_milyon"] = atilan.get("yatirim_usd_milyon")


def olaylari_birlestir(olaylar):
    """Partiler arası mükerrer olayları tek olaya indir.
    Dönen: (kalan olaylar, notlar)"""
    if len(olaylar) < 2:
        return olaylar, []

    notlar = []
    olaylar = sorted(olaylar, key=lambda o: o.get("puan") or 0, reverse=True)
    olu = set()                       # birleştirilip düşen olayların indisi

    # --- 1) KESİN eşleşmeler ---
    for i in range(len(olaylar)):
        if i in olu:
            continue
        for j in range(i + 1, len(olaylar)):
            if j in olu:
                continue
            if _kesin_ayni(olaylar[i], olaylar[j]):
                _birlestir_cift(olaylar[i], olaylar[j])
                olu.add(j)
                notlar.append(f"kesin birleşme (ortak kaynak): "
                              f"{olaylar[j].get('event_key')} → {olaylar[i].get('event_key')}")

    # --- 2) SAYI PARMAK İZİ (deterministik, LLM'siz) ---
    # Aynı ayırt edici tutarı/kapasiteyi taşıyan iki olay pratikte aynı olaydır.
    for i in range(len(olaylar)):
        if i in olu:
            continue
        pi = _ayirt_edici_sayilar(olaylar[i])
        if not pi:
            continue
        for j in range(i + 1, len(olaylar)):
            if j in olu or not (pi & _ayirt_edici_sayilar(olaylar[j])):
                continue
            if not _ortak_sinyal(olaylar[i], olaylar[j]):
                continue          # aynı sayı ama alakasız olay → dokunma
            ortak_sayi = sorted(pi & _ayirt_edici_sayilar(olaylar[j]))[0]
            _birlestir_cift(olaylar[i], olaylar[j])
            olu.add(j)
            notlar.append(f"sayı parmak izi ({ortak_sayi}): "
                          f"{olaylar[j].get('event_key')} → {olaylar[i].get('event_key')}")

    # --- 3) KÜRESEL KÜMELEME — kalan TÜM olaylar tek istemde ---
    # ⚠ Burada eskiden eşik tabanlı bir ÖN ELEME vardı ve asıl kusur oydu:
    # eşiği geçemeyen çift hakeme hiç gitmiyordu. Künye küçük olduğu için
    # (olay başına ~200 karakter) hepsini birden sormak birkaç sent tutuyor.
    kalanlar = [(n, o) for n, o in enumerate(olaylar) if n not in olu]
    sorulan = kalanlar[:BIRLESTIRME_AZAMI_OLAY]
    gruplar = []
    if len(sorulan) >= 2:
        try:
            cikti = llm.llm_cagri(
                AYARLAR.get("model_birlestirme") or AYARLAR["model_yazim"],
                prompts.BIRLESTIRME_PROMPT,
                prompts.birlestirme_kullanici_mesaji([o for _, o in sorulan]),
                AYARLAR.get("max_tokens_birlestirme", 4000),
            )
            gruplar = json_ayikla(cikti).get("gruplar") or []
        except Exception as e:
            log(f"  ! Birleştirme adımı başarısız ({e}) — mükerrer kontrolü atlandı")

    indis = {o.get("event_key"): n for n, o in sorulan if o.get("event_key")}
    for g in gruplar:
        anahtarlar = [a for a in (g.get("anahtarlar") or []) if a in indis]
        indisler = [indis[a] for a in anahtarlar if indis[a] not in olu]
        if len(indisler) < 2:
            continue
        if len(indisler) > BIRLESTIRME_AZAMI_KUME:
            log(f"  ! {len(indisler)} olaylık grup atlandı (tema gruplaması şüphesi): "
                f"{', '.join(anahtarlar[:5])}")
            continue
        # en yüksek puanlı olay tutulur — diğerleri ona katılır
        indisler.sort(key=lambda n: -(olaylar[n].get("puan") or 0))
        tutulan = indisler[0]
        for n in indisler[1:]:
            if not _ortak_sinyal(olaylar[tutulan], olaylar[n]):
                log(f"  ! birleştirme reddedildi (ortak sinyal yok): "
                    f"{olaylar[n].get('event_key')} ↮ {olaylar[tutulan].get('event_key')}")
                continue
            _birlestir_cift(olaylar[tutulan], olaylar[n])
            olu.add(n)
            notlar.append(
                f"birleştirildi ({(g.get('gerekce') or '')[:40]}): "
                f"{olaylar[n].get('event_key')} → {olaylar[tutulan].get('event_key')}")

    kalan = [o for n, o in enumerate(olaylar) if n not in olu]
    log(f"Olay birleştirme: {len(sorulan)} olay tek istemde soruldu · "
        f"{len(gruplar)} mükerrer grup bulundu · "
        f"{len(olu)} olay birleştirildi · {len(kalan)} olay kaldı")
    for n in notlar[:10]:
        log(f"  · {n}")
    return kalan, notlar


def olaylari_zenginlestir(olaylar, adaylar):
    """Olaylara kaynak metinlerini bağla + birincil kaynak onarımı.
    Tüm kaynaklar duvarlıysa 'sadece_radar' işaretlenir."""
    idx = {a["id"]: a for a in adaylar}
    zengin, degistirilen, radara_dusen = [], 0, 0

    for o in olaylar:
        pid = o.get("primary_id")
        ids = list(dict.fromkeys(([pid] if pid else []) + (o.get("supporting_ids") or [])))
        kaynaklar = []
        for aid in ids:
            a = idx.get(aid)
            if not a:
                continue
            kaynaklar.append({
                "name": a["domain"], "domain": a["domain"], "url": a["url"],
                "published_date": a["published_date"],
                "text": a.get("text") or a["snippet"],
                "image": a.get("image"), "tier": a["tier"],
                "paywall": a.get("paywall", False), "primary": False,
            })
        if not kaynaklar:
            continue

        acik = [k for k in kaynaklar if not k["paywall"]]
        if acik:
            en_iyi = min(acik, key=lambda k: (k["tier"], -len(k.get("text") or "")))
            if kaynaklar[0] is not en_iyi:
                degistirilen += 1
            kaynaklar.remove(en_iyi)
            kaynaklar.insert(0, en_iyi)
            kaynaklar[0]["primary"] = True
            o["sadece_radar"] = False
        else:
            kaynaklar[0]["primary"] = True
            o["sadece_radar"] = True
            radara_dusen += 1

        o["kaynaklar"] = kaynaklar
        zengin.append(o)

    log(f"Birincil kaynak onarıldı: {degistirilen} olay · "
        f"Sadece-radar (tüm kaynaklar duvarlı): {radara_dusen} olay")
    return zengin


# ============================================================
# 5) AŞAMA 2 — YAZIM
# ============================================================
# ⚠ NEDEN TAMLIK DENETİMİ VAR
# Gerçek vaka (biyoekonomi, Sayı 2 — 9 Ağustos 2026): 14 derin olay verildi,
# model 5 haber yazıp kalanların yerine "__PLACEHOLDER_NOT_USED__" adlı bir
# yer tutucu koydu ve radar bölümünü hiç açmadı. Çıktı çağrı başına 8,3K
# token'dı — tam bülten 29-33K gerektiriyor, yani model işi yarıda bıraktı.
# Boru hattı bunu fark etmedi: dogrula_taslak yalnızca "stories az (5)" diye
# bir uyarı satırı yazdı, taslak Neon'a kaydedildi ve 3 hakeme davet gitti.
# Aynı olayla yapılan iki tekrar denemesinde model 14/14 yazdı — arıza her
# hafta değil, BAZI haftalar çıkıyor. Bu yüzden sessiz geçmemeli.
YAZIM_ASGARI_ORAN = 0.7          # derin olayların bu kadarı haber olmalı
YAZIM_YER_TUTUCU_IZLERI = ("placeholder", "not_used", "notused", "todo", "tbd")


def yazim_eksik(b, derin, radar_havuz):
    """Yazım çıktısı kabul edilebilir mi? Sorun varsa AÇIKLAMA döndürür."""
    stories = b.get("stories") or []
    if derin and len(stories) < max(1, int(len(derin) * YAZIM_ASGARI_ORAN)):
        return f"{len(derin)} derin olaya karşılık yalnızca {len(stories)} haber yazıldı"

    yer_tutucu = [s.get("id") or s.get("title") or "?" for s in stories
                  if any(iz in ((s.get("id") or "") + (s.get("title") or "")).lower()
                         for iz in YAZIM_YER_TUTUCU_IZLERI)]
    if yer_tutucu:
        return f"model yer tutucu üretti: {', '.join(yer_tutucu[:3])}"

    radar_madde = sum(len(k.get("maddeler") or []) for k in (b.get("radar") or []))
    if radar_havuz and not radar_madde:
        return f"{len(radar_havuz)} radar adayı verildi ama radar boş döndü"

    return None


def yaz(derin, radar_havuz, sayi_no, bas, bit, pencere, model=None):
    """json_repair'e rağmen geçersiz çıktı gelirse yazımı BİR kez daha dene —
    haftalık cron tek bozuk üretim yüzünden boş geçmesin.

    model: None ise MODEL_YAZIM ortam değişkeni, o da yoksa
    AYARLAR["model_yazim"]. Model karşılaştırma modunda (KARSILASTIR_MODEL)
    aynı veriyle ikinci bir model çalıştırmak için kullanılır.

    ⚠ MODEL_YAZIM neden var: model denemesi yaparken config.py'yi düzenlemek
    gerekiyordu; düzeltmeyi geri almayı unutmak, haftalık cron'un yanlış
    modelle yayına çıkması demek. Ortam değişkeni tek çalışmayı etkiler.
    """
    model = model or os.environ.get("MODEL_YAZIM", "").strip() \
        or AYARLAR["model_yazim"]
    # Akıl yürüten modellerde düşünme token'ları da çıktı bütçesinden düşer →
    # görünür metnin kesilmemesi için daha geniş limit kullanılır.
    # (gpt-5.x · Sonnet 5 · Opus 4.7+ · Fable 5 — hepsinde düşünme varsayılan açık)
    AKIL_YURUTEN = ("openai:gpt-5", "anthropic:claude-sonnet-5",
                    "anthropic:claude-opus-", "anthropic:claude-fable-")
    limit = (AYARLAR.get("max_tokens_yazim_reasoning", AYARLAR["max_tokens_yazim"])
             if model.startswith(AKIL_YURUTEN) else AYARLAR["max_tokens_yazim"])
    log(f"  yazım modeli: {model} · max_tokens={limit:,} · "
        f"{len(derin)} derin olay + {len(radar_havuz)} radar adayı")
    son_hata, son_b, son_eksik = None, None, None
    for deneme in range(2):
        if deneme:
            log(f"  ⚠ Yazım yeniden deneniyor (2/2) — sebep: "
                f"{son_eksik or 'çıktı kurtarılamadı'}")
        try:
            cikti = llm.llm_cagri(
                model, prompts.YAZIM_PROMPT,
                prompts.yazim_kullanici_mesaji(derin, radar_havuz, sayi_no, bas, bit, pencere),
                limit,
                stream=True,     # uzun çıktı — zaman aşımını önler
            )
            b = json_ayikla(cikti)
        except (ValueError, json.JSONDecodeError) as e:
            son_hata = e
            continue

        eksik = yazim_eksik(b, derin, radar_havuz)
        if not eksik:
            return b
        son_b, son_eksik = b, eksik           # elde bir şey var; yine de sakla

    if son_b is not None:
        # İki deneme de eksik kaldı: elde olanı DÖNDÜR ama sessizce geçme —
        # bu uyarı çalışma raporunun en üstüne çıkar.
        son_b["_yazim_uyarisi"] = son_eksik
        log(f"  ‼ YAZIM EKSİK KALDI (2 deneme): {son_eksik}")
        return son_b
    raise son_hata


# ============================================================
# 5.9) MODEL KARŞILAŞTIRMA (opsiyonel)
# ------------------------------------------------------------
# KARSILASTIR_MODEL ortam değişkeni tanımlıysa yazım adımı AYNI olaylarla
# ikinci bir modelde daha çalıştırılır ve iki çıktı e-postayla yan yana
# gönderilir. Yayınlanan bülten DEĞİŞMEZ — asıl model neyse o yayınlanır;
# ikinci çıktı yalnızca kaliteyi kıyaslamak içindir.
#
# Kullanımı (Render → Environment):
#   KARSILASTIR_MODEL = openai:gpt-5.6-luna
# Karşılaştırma bitince değişkeni SİLİN, yoksa her hafta ekstra ücret çıkar.
# ============================================================
def _ilk_paragraf(metin, n=400):
    p = (metin or "").split("\n\n")[0].strip()
    return p[:n] + ("…" if len(p) > n else "")


def model_karsilastir(model, derin, radar_havuz, sayi_no, bas, bit, pencere, asil):
    """İkinci modelle yazımı tekrarlar, karşılaştırma metni döndürür.
    Hata olursa akışı BOZMAZ — None döner."""
    log(f"Model karşılaştırma — ikinci yazım: {model}")
    onceki = dict(llm.KULLANIM)          # asıl yazımın kullanımını ayırmak için
    try:
        b2 = yaz(derin, radar_havuz, sayi_no, bas, bit, pencere, model=model)
    except Exception as e:
        log(f"  ! Karşılaştırma yazımı başarısız: {e}")
        return None

    # sadece bu modelin maliyeti
    k = llm.KULLANIM.get(model, {})
    f = FIYAT.get(model)
    m2 = ((k.get("in", 0) * f["in"] + k.get("out", 0) * f["out"]) / 1e6) if f else 0.0
    ka = onceki.get(AYARLAR["model_yazim"], {})
    fa = FIYAT.get(AYARLAR["model_yazim"])
    m1 = ((ka.get("in", 0) * fa["in"] + ka.get("out", 0) * fa["out"]) / 1e6) if fa else 0.0

    # haberleri BİRİNCİL KAYNAK URL'iyle eşle (id'ler modele göre değişebilir)
    def indeksle(b):
        d = {}
        for s in (b.get("stories") or []):
            u = url_normalize((s.get("source") or {}).get("url") or "")
            if u:
                d[u] = s
        return d
    a_idx, b_idx = indeksle(asil), indeksle(b2)
    ortak = [u for u in a_idx if u in b_idx][:4]

    # nesnel uzunluk ölçüsü — "kısa/uzun" izlenimini rakamla doğrula
    def ort(b, alan):
        d = [len(s.get(alan) or "") for s in (b.get("stories") or [])]
        return sum(d) / len(d) if d else 0

    def rakam_sayisi(b):
        """excerpt'lerdeki sayı adedi — veri yoğunluğunun kaba göstergesi."""
        n = [len(re.findall(r"\d", s.get("excerpt") or ""))
             for s in (b.get("stories") or [])]
        return sum(n) / len(n) if n else 0

    satirlar = [
        "MODEL KARŞILAŞTIRMASI — aynı haberler, iki farklı yazım modeli",
        "=" * 66,
        f"A) {AYARLAR['model_yazim']}   (yayınlanan bu)",
        f"B) {model}   (yalnızca karşılaştırma)"
        + (f"   · reasoning_effort={os.environ.get('REASONING_EFFORT') or AYARLAR.get('reasoning_effort')}"
           if model.startswith("openai:") else ""),
        "",
        "UZUNLUK / YOĞUNLUK (haber başına ortalama)",
        f"  özet   : A {ort(asil,'excerpt'):>5.0f} krkt   ·   B {ort(b2,'excerpt'):>5.0f} krkt",
        f"  metin  : A {ort(asil,'detail'):>5.0f} krkt   ·   B {ort(b2,'detail'):>5.0f} krkt",
        f"  özetteki rakam adedi: A {rakam_sayisi(asil):.1f}   ·   B {rakam_sayisi(b2):.1f}",
        "",
        f"Maliyet (yalnızca yazım adımı):  A ≈ ${m1:.3f}   ·   B ≈ ${m2:.3f}",
        f"Token:  A girdi {ka.get('in',0):,} / çıktı {ka.get('out',0):,}"
        f"   ·   B girdi {k.get('in',0):,} / çıktı {k.get('out',0):,}",
        f"Üretilen haber:  A {len(asil.get('stories') or [])}  ·  B {len(b2.get('stories') or [])}",
        f"Karşılaştırılabilen (aynı kaynaklı) haber: {len(ortak)}",
        "=" * 66, "",
    ]
    for i, u in enumerate(ortak, 1):
        a, b = a_idx[u], b_idx[u]
        satirlar += [
            f"── HABER {i} ─────────────────────────────────────────────",
            f"kaynak: {u}", "",
            f"[A] BAŞLIK : {a.get('title','')}",
            f"[B] BAŞLIK : {b.get('title','')}", "",
            f"[A] ÖZET   : {a.get('excerpt','')}",
            f"[B] ÖZET   : {b.get('excerpt','')}", "",
            f"[A] METİN  : {_ilk_paragraf(a.get('detail'))}",
            f"[B] METİN  : {_ilk_paragraf(b.get('detail'))}", "", "",
        ]
    if not ortak:
        satirlar.append("(İki model ortak haber üretmedi — kıyas yapılamadı.)")
    satirlar += ["=" * 66,
                 "Değerlendirirken bakılacaklar: Türkçe akıcılık, rakamların",
                 "eksiksiz aktarımı, yorum/analiz kaçağı olup olmadığı,",
                 "terimlerin ilk geçişte parantezle verilmesi."]
    return "\n".join(satirlar)


# ============================================================
# 5.95) KAYNAK SABİTLEME — modelin yazdığı URL'i boru hattının
#       kendi verisiyle DEĞİŞTİR
# ------------------------------------------------------------
# ⚠ Yazım modeli tek promptta onlarca URL görüyor (BÖLÜM A derin olaylar +
# BÖLÜM B radar adayları) ve kaynak yazarken bunları karıştırabiliyor.
# Gerçek vaka (biyoekonomi, Sayı 1): manşetteki SOCAR–Pegasus SAF haberine
# promptun BAŞKA bir kalemine ait Neste/biomassmagazine URL'si iliştirildi;
# görsel de o URL'in sayfasından çekildiği için haberin üstüne alakasız bir
# Neste sunum slaydı düştü. source.name de melez çıktı:
# "SOCAR Türkiye / Biomass Magazine".
#
# Kural: model artık URL'in SAHİBİ DEĞİL. Her haber event_key ile kendi
# olayına bağlanır; source / supporting_sources / published_date alanları
# o olayın gerçek kaynaklarından yeniden yazılır. Hiçbir olaya bağlanamayan
# haber YAYINLANMAZ — kaynağı doğrulanamayan metin, eksik haberden kötüdür.
# ============================================================
BENZERLIK_ESIGI = 0.18          # bu değerin altındaki eşleşme kabul edilmez


def _olay_metni(o):
    """Olayı temsil eden karşılaştırma metni (özet + şirketler + ülkeler)."""
    return " ".join([o.get("baslik_ozet") or ""]
                    + list(o.get("sirketler") or [])
                    + list(o.get("ulkeler") or []))


def _haber_metni(s):
    """Haberi temsil eden karşılaştırma metni.

    Başlık Türkçe, olay özeti çoğunlukla İngilizce → asıl taşıyıcı sinyal
    şirket/ülke adları. Bu yüzden ikisi de metne katılır."""
    return " ".join([s.get("title") or "", s.get("excerpt") or ""]
                    + list(s.get("companies") or [])
                    + list(s.get("countries") or []))


def _kaynak_yaz(st, o):
    """Haberin kaynak alanlarını olayın GERÇEK kaynaklarıyla doldur."""
    kaynaklar = o.get("kaynaklar") or []
    if not kaynaklar:
        return False
    bir = kaynaklar[0]
    onceki_tip = ((st.get("source") or {}).get("type")) or None
    st["source"] = {
        "name": bir["name"], "url": bir["url"], "domain": bir["domain"],
        "type": onceki_tip, "tier": bir["tier"], "primary": True,
    }
    st["supporting_sources"] = [
        {"name": k["name"], "url": k["url"], "domain": k["domain"]}
        for k in kaynaklar[1:]
    ]
    if bir.get("published_date"):
        st["published_date"] = bir["published_date"]
    st["event_key"] = o.get("event_key")
    # varlik_denetimi için geçici — taslak kaydedilmeden önce silinir
    st["_kaynak_metni"] = bir.get("text") or ""
    return True


def kaynaklari_sabitle(taslak, derin, radar_havuz=None):
    """Haberleri olaylarına bağla, kaynakları üzerine yaz, bağlanamayanı çıkar.

    Eşleme merdiveni (her basamak yalnızca BOŞTA olan olaylara bakar, aynı
    olay iki habere verilemez):
      1. id == event_key            → modelin kopyaladığı anahtar (normal yol)
      2. source.url                 → olayın kaynak URL'lerinden biriyle eşleşme
      3. şirket/ülke/başlık benzerliği (eşik üstü ve tek aday)
      4. artakalanlar sırayla       → |haber| == |olay| olduğunda kapanış

    Dönen: (notlar, dusenler) — notlar log/e-posta için, dusenler çıkarılan
    haberlerin başlıkları.
    """
    stories = taslak.get("stories") or []
    if not derin or not stories:
        return [], []

    notlar, bosta = [], {}
    for o in derin:
        anahtar = o.get("event_key")
        if anahtar and o.get("kaynaklar"):
            bosta[anahtar] = o
    eslesen = {}                       # story index -> olay

    # --- 1) event_key ---
    for i, s in enumerate(stories):
        k = s.get("id")
        if k in bosta:
            eslesen[i] = bosta.pop(k)

    # --- 2) URL ---
    url_sahibi = {}
    for o in bosta.values():
        for k in o["kaynaklar"]:
            url_sahibi.setdefault(url_normalize(k["url"]), o.get("event_key"))
    for i, s in enumerate(stories):
        if i in eslesen:
            continue
        u = url_normalize((s.get("source") or {}).get("url") or "")
        anahtar = url_sahibi.get(u)
        if anahtar and anahtar in bosta:
            eslesen[i] = bosta.pop(anahtar)
            notlar.append(f"URL ile eşlendi (id tutmadı): "
                          f"'{(s.get('title') or '?')[:45]}' → {anahtar}")

    # --- 3) benzerlik ---
    for i, s in enumerate(stories):
        if i in eslesen or not bosta:
            continue
        metin = _haber_metni(s)
        puanlar = sorted(
            ((benzerlik(metin, _olay_metni(o))[0], a) for a, o in bosta.items()),
            reverse=True)
        if puanlar and puanlar[0][0] >= BENZERLIK_ESIGI:
            # ikinci aday da yakınsa karar verme — 4. basamağa bırak
            if len(puanlar) > 1 and puanlar[1][0] > puanlar[0][0] * 0.8:
                continue
            anahtar = puanlar[0][1]
            eslesen[i] = bosta.pop(anahtar)
            notlar.append(f"benzerlikle eşlendi ({puanlar[0][0]:.2f}): "
                          f"'{(s.get('title') or '?')[:45]}' → {anahtar}")

    # --- 4) artakalanlar sırayla ---
    artan = [i for i in range(len(stories)) if i not in eslesen]
    if artan and len(artan) == len(bosta):
        for i, anahtar in zip(artan, list(bosta)):
            eslesen[i] = bosta.pop(anahtar)
            notlar.append(f"sırayla eşlendi (son çare): "
                          f"'{(stories[i].get('title') or '?')[:45]}' → {anahtar}")

    # --- kaynakları üzerine yaz / bağlanamayanı çıkar ---
    kalanlar, dusenler, degisen = [], [], 0
    for i, s in enumerate(stories):
        o = eslesen.get(i)
        if not o:
            dusenler.append(s.get("title") or "?")
            notlar.append(
                f"✗ ÇIKARILDI — hiçbir olaya bağlanamadı: "
                f"'{(s.get('title') or '?')[:60]}' "
                f"(modelin yazdığı kaynak: {(s.get('source') or {}).get('url') or '-'})")
            continue
        onceki = url_normalize((s.get("source") or {}).get("url") or "")
        if _kaynak_yaz(s, o):
            if onceki and onceki != url_normalize(s["source"]["url"]):
                degisen += 1
                notlar.append(f"kaynak düzeltildi: '{(s.get('title') or '?')[:40]}' "
                              f"{onceki[:55]} → {s['source']['url'][:55]}")
            kalanlar.append(s)
        else:
            dusenler.append(s.get("title") or "?")
    taslak["stories"] = kalanlar

    # Manşet düşen habere işaret ediyorsa lead_id'yi TEMİZLE — dogrula_taslak
    # o zaman en yüksek puanlıyı seçip log'a yazar. Bırakılırsa yayın aşaması
    # sessizce yedek mekanizmasına düşer ve kimse manşetin değiştiğini görmez.
    if taslak.get("lead_id") and not any(
            s.get("id") == taslak["lead_id"] for s in kalanlar):
        notlar.append(f"manşet düşen habere işaret ediyordu "
                      f"({taslak['lead_id']}) → lead_id temizlendi")
        taslak["lead_id"] = None

    # --- radar: URL beyaz listesi (model burada da URL uyduruyor olabilir) ---
    izinli = set()
    for o in list(derin) + list(radar_havuz or []):
        for k in (o.get("kaynaklar") or []):
            izinli.add(url_normalize(k["url"]))
    radar_atilan = 0
    for kume in (taslak.get("radar") or []):
        once = len(kume.get("maddeler", []))
        kume["maddeler"] = [m for m in kume.get("maddeler", [])
                            if url_normalize(m.get("url") or "") in izinli]
        radar_atilan += once - len(kume["maddeler"])
    taslak["radar"] = [k for k in (taslak.get("radar") or []) if k.get("maddeler")]
    if radar_atilan:
        notlar.append(f"radar: {radar_atilan} madde havuzda olmayan URL taşıyordu → çıkarıldı")

    log(f"Kaynak sabitleme: {len(kalanlar)} haber bağlandı · "
        f"{degisen} kaynak düzeltildi · {len(dusenler)} haber çıkarıldı · "
        f"radar {radar_atilan} madde elendi")
    return notlar, dusenler


def varlik_denetimi(taslak):
    """Kaynak doğru bağlandıktan SONRA: haberin şirketleri kaynak metninde
    gerçekten geçiyor mu? Geçmiyorsa yanlış kümeleme ya da uydurma içerik
    şüphesi var — haberi ELEMEZ, yalnızca işaretler."""
    uyarilar = []
    for st in (taslak.get("stories") or []):
        sirketler = [c for c in (st.get("companies") or []) if len(c) >= 3]
        metin = (st.get("_kaynak_metni") or "").lower()
        if not sirketler or not metin:
            continue
        if not any(c.split()[0].lower() in metin for c in sirketler):
            uyarilar.append(
                f"⚠ şirket eşleşmiyor: '{(st.get('title') or '?')[:50]}' — "
                f"{', '.join(sirketler[:3])} birincil kaynak metninde geçmiyor")
    return uyarilar


# ============================================================
# 6) DOĞRULAMA — taslak düzeyinde
# ============================================================
ESLESME = {
    # Model bazen değer zinciri etiketini/eş anlamlıyı kategori sanıyor — sessizce onar.
    "duzenleme": "politika", "mevzuat": "politika", "strateji": "politika",
    "ihracat-kontrolu": "politika", "yaptirim": "politika", "teşvik": "politika",
    "yatirim": "yatirim", "kapasite": "yatirim", "fab": "yatirim",
    "ekipman": "ekipman", "malzeme": "ekipman", "litografi": "ekipman", "euv": "ekipman",
    "teknoloji": "teknoloji", "sure-teknolojisi": "teknoloji", "dugum": "teknoloji",
    "paketleme": "paketleme", "chiplet": "paketleme", "test": "paketleme",
    "bellek": "bellek", "dram": "bellek", "nand": "bellek", "hbm": "bellek",
    "ai-cip": "ai-cip", "veri-merkezi": "ai-cip", "hizlandirici": "ai-cip",
    "tasarim": "tasarim", "eda": "tasarim", "ip": "tasarim", "risc-v": "tasarim",
    "guc": "guc", "bilesik-yari-iletken": "guc", "sic": "guc", "gan": "guc",
    "uygulama": "uygulama", "otomotiv": "uygulama", "savunma": "uygulama",
    "piyasa": "rapor", "akademik": "rapor", "arastirma": "rapor",
}


# ============================================================
# 6.2) ÜSLUP ÖLÇÜMÜ — cümle disiplini tutuyor mu?
# ------------------------------------------------------------
# YAZIM_PROMPT'a cümle uzunluğu kuralı eklendi (hedef 12-20, üst sınır 28).
# Tutup tutmadığı ölçülmezse körlemesine gidilir. Ölçülen taban (biyoekonomi
# Sayı 2, kural eklenmeden önce): ortalama 20,5 kelime · %18'i 30+ kelime ·
# en uzun 48. Bu satır raporda görünür; haberi ENGELLEMEZ.
# ============================================================
CUMLE_UST_SINIR = 28


def uslup_ozeti(stories):
    """detail metinlerinin cümle uzunluğu istatistiği. Boşsa None."""
    uzunluk = []
    for s in (stories or []):
        for c in re.split(r"(?<=[.!?])\s+", s.get("detail") or ""):
            c = c.strip()
            if len(c) > 10:
                uzunluk.append(len(c.split()))
    if not uzunluk:
        return None
    uzunluk.sort()
    n = len(uzunluk)
    return {
        "cumle": n,
        "ortalama": round(sum(uzunluk) / n, 1),
        "medyan": uzunluk[n // 2],
        "en_uzun": uzunluk[-1],
        "asan": sum(1 for k in uzunluk if k > CUMLE_UST_SINIR),
        "asan_yuzde": round(sum(1 for k in uzunluk if k > CUMLE_UST_SINIR) / n * 100),
    }


def dogrula_taslak(b, kapsam_bas=None, kapsam_bit=None):
    """Şema doğrulama + slug üretimi + radar tarih kesimi.
    Metrikler yayında (nihai seçim üzerinden) hesaplanır — burada değil."""
    hatalar = []

    # --- radar tarih kesimi: kapsam dışı madde bültene giremez ---
    # (tarih_dogrula olay bazında zaten eledi; bu, modelin yazdığı tarihe
    # karşı son emniyet kemeridir — ISO tarihlerde dizge karşılaştırma yeter)
    if kapsam_bas:
        atilan = 0
        for k in (b.get("radar") or []):
            once = len(k.get("maddeler", []))
            k["maddeler"] = [
                m for m in k.get("maddeler", [])
                if not (isinstance(m.get("date"), str) and len(m["date"]) >= 10
                        and (m["date"][:10] < kapsam_bas
                             or (kapsam_bit and m["date"][:10] > kapsam_bit)))
            ]
            atilan += once - len(k["maddeler"])
        b["radar"] = [k for k in (b.get("radar") or []) if k.get("maddeler")]
        if atilan:
            hatalar.append(f"radar: {atilan} kapsam dışı madde çıkarıldı")
    stories = b.get("stories") or []
    if len(stories) < 8:
        hatalar.append(f"stories az ({len(stories)})")
    if len(b.get("brief") or []) != 5:
        hatalar.append("brief 5 madde değil")
    if not b.get("lead_id"):
        # manşet belirtilmemişse en yüksek puanlı one_cikan haberi seç
        secili = [s for s in stories if s.get("secim") == "one_cikan"] or stories
        if secili:
            b["lead_id"] = max(secili, key=lambda s: s.get("score") or 0).get("id")
            hatalar.append("lead_id yoktu — puanla seçildi")

    # --- slug üretimi (benzersiz) ---
    gorulen = set()
    for st in stories:
        sl = slugify(st.get("title", ""))
        temel, i = sl, 2
        while sl in gorulen:
            sl = f"{temel}-{i}"
            i += 1
        gorulen.add(sl)
        st["slug"] = sl
        st["neden_onemli"] = None          # analiz katmanı şimdilik kapalı
        # Olay tarihi KALDIRILDI: modelin metinden çıkardığı, doğrulanamayan
        # bir tarihti ve doğrulanmış published_date ile çelişiyordu.
        # (DOE haberi: kaynak 28 Temmuz yayımlı, olay tarihi 24 Temmuz yazıldı.)
        st.pop("event_date", None)
        if st.get("secim") not in ("one_cikan", "yedek"):
            st["secim"] = "yedek"
            hatalar.append(f"'{(st.get('title') or '?')[:30]}' → secim onarıldı")

    # --- alan kontrolü + kategori onarımı ---
    for st in stories:
        for alan in ("title", "excerpt", "detail", "category", "source"):
            if not st.get(alan):
                hatalar.append(f"'{(st.get('title') or '?')[:30]}' → {alan} eksik")
        c = st.get("category")
        if c not in KATEGORILER:
            yeni_c = ESLESME.get(c)
            if not yeni_c:
                vc = (st.get("value_chain") or [None])[0]
                yeni_c = ESLESME.get(vc, "rapor")
            st["category"] = yeni_c
            hatalar.append(f"kategori onarıldı: '{c}' → '{yeni_c}'")
        m = st.get("maturity")
        if m and m not in OLGUNLUK:
            st["maturity"] = None
            hatalar.append(f"olgunluk onarıldı: '{m}' → null")

    # --- manşetin one_cikan olduğundan emin ol ---
    lead = next((s for s in stories if s.get("id") == b.get("lead_id")), None)
    if lead and lead.get("secim") != "one_cikan":
        lead["secim"] = "one_cikan"

    # --- öne çıkan sayısını 8-10 aralığına çek ---
    secili = [s for s in stories if s.get("secim") == "one_cikan"]
    if len(secili) > AYARLAR["one_cikan_max"]:
        fazla = sorted((s for s in secili if s.get("id") != b.get("lead_id")),
                       key=lambda s: s.get("score") or 0)
        for s in fazla[:len(secili) - AYARLAR["one_cikan_max"]]:
            s["secim"] = "yedek"
            hatalar.append(f"öne çıkan fazlaydı → yedeğe: {s.get('slug')}")
    elif len(secili) < AYARLAR["one_cikan_min"]:
        yedekler = sorted((s for s in stories if s.get("secim") == "yedek"),
                          key=lambda s: -(s.get("score") or 0))
        for s in yedekler[:AYARLAR["one_cikan_min"] - len(secili)]:
            s["secim"] = "one_cikan"
            hatalar.append(f"öne çıkan azdı → seçildi: {s.get('slug')}")

    # --- brief: metin + ref (id) — slug çevirisi yayında yapılır ---
    yeni_brief = []
    for m in (b.get("brief") or []):
        if isinstance(m, str):
            yeni_brief.append({"text": m, "ref": None})
        else:
            yeni_brief.append({"text": m.get("text", ""), "ref": m.get("ref")})
    b["brief"] = yeni_brief
    return hatalar


# ============================================================
# 5.5) SAYFA DOĞRULAMA — gerçek tarih + gerçek görsel
# ------------------------------------------------------------
# ⚠ Exa'nın publishedDate alanı bazen DÜPEDÜZ YANLIŞ: Ağustos 2025
# tarihli bir DCD makalesini "17 Temmuz 2026" diye etiketlediği görüldü.
# Bu yüzden triyajdan geçen her olayın birincil kaynak SAYFASI çekilir;
# makalenin kendi meta etiketlerinden (article:published_time,
# datePublished...) gerçek tarih okunur. Aynı çekimde og:image de alınır
# → Exa'nın yanlış görsel tahminleri (paylaşım ikonu, alakasız render)
# yerine makalenin kendi görseli kullanılır.
# ============================================================
# Sayfadan cikarilan metin, Exa metninin yerini ancak BELIRGIN olcude
# zenginse alir - kisa/bozuk cikarimla iyi metni bozmayalim.
METIN_ASGARI = 600
METIN_KAT = 1.3

OG_GORSEL_KALIPLARI = (
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
)
# Makale KAPSAMLI tarih işaretleri (sayfa geneli değil — güvenilir katman).
# ⚠ Genel "<time datetime=...>" kalıbı BİLEREK YOK: haber sayfaları "ilgili
# haberler" bölümlerinde BAŞKA makalelerin tarihlerini taşır; ilk <time>'ı
# almak DCD'de Ağustos 2025 makalesini "17 Temmuz 2026" gösterdi.
TARIH_META_KALIPLARI = (
    r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
    r'"datePublished"\s*:\s*"([^"]+)"',
    r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+name=["\'](?:pubdate|publish-date|publication_date|date)["\'][^>]+content=["\']([^"\']+)',
)
# class'ında makale ipucu taşıyan <time> (ör. DCD: class="article-intro__date")
_TIME_SINIF = r'(?:article|entry|post|intro|publish|byline)'
TARIH_TIME_KALIPLARI = (
    rf'<time[^>]+class=["\'][^"\']*{_TIME_SINIF}[^"\']*["\'][^>]*datetime=["\'](\d{{4}}-\d{{2}}-\d{{2}})',
    rf'<time[^>]+datetime=["\'](\d{{4}}-\d{{2}}-\d{{2}})[^"\']*["\'][^>]*class=["\'][^"\']*{_TIME_SINIF}',
)


def _gecerli_tarih(aday):
    try:
        datetime.strptime(aday[:10], "%Y-%m-%d")
        return aday[:10]
    except ValueError:
        return None


# ⚠ Bazı yayınlar HİÇBİR makine-okur tarih etiketi vermiyor: ne
# article:published_time, ne JSON-LD, ne <time>. Tarih yalnızca başlığın
# altında düz metin olarak duruyor. O zaman _tarih_ayikla None dönüyordu,
# pencere denetimi HİÇ çalışmıyordu ve Exa'nın (bazen düpedüz yanlış)
# tarihi olduğu gibi kalıyordu. Gerçek vaka (nükleer, Sayı 1): ans.org'un
# iki haberi Mart 2026 tarihliyken Temmuz sonu diye yayımlandı — biri
# manşetti.
#
# Çözüm: makalenin BAŞ kısmındaki görünür tarihi oku. Kapsam bilerek dar
# tutulur (gövdenin ilk 400 karakteri) — sayfa geneli taransa "ilgili
# haberler" bölümündeki BAŞKA makalelerin tarihleri yakalanırdı.
_AY_ADLARI = {
    "jan": 1, "oca": 1, "feb": 2, "şub": 2, "sub": 2, "mar": 3,
    "apr": 4, "nis": 4, "may": 5, "jun": 6, "haz": 6,
    "jul": 7, "tem": 7, "aug": 8, "ağu": 8, "agu": 8, "sep": 9, "eyl": 9,
    "oct": 10, "eki": 10, "nov": 11, "kas": 11, "dec": 12, "ara": 12,
}
_BAS_KAPSAM = 400


def _gorunur_tarih(html):
    """Makale başındaki düz metin tarihini ISO'ya çevir; bulunamazsa None."""
    bloklar = _ARTICLE_BLOK.findall(_TEMIZLE_ETIKET.sub(" ", html))
    kapsam = max(bloklar, key=len) if bloklar else html
    metin = re.sub(r"\s+", " ", html_mod.unescape(_IC_ETIKET.sub(" ", kapsam)))
    bas = metin[:_BAS_KAPSAM]

    def kur(y, a, g):
        try:
            return datetime(int(y), int(a), int(g)).strftime("%Y-%m-%d")
        except ValueError:
            return None

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", bas)          # 2026-07-30
    if m:
        return kur(*m.groups())
    m = re.search(r"\b([A-Za-zÇĞİÖŞÜçğıöşü]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})\b", bas)
    if m and m.group(1)[:3].lower() in _AY_ADLARI:              # Mar 26, 2026
        return kur(m.group(3), _AY_ADLARI[m.group(1)[:3].lower()], m.group(2))
    m = re.search(r"\b(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]{3,9})\.?\s+(\d{4})\b", bas)
    if m and m.group(2)[:3].lower() in _AY_ADLARI:              # 27 July 2026
        return kur(m.group(3), _AY_ADLARI[m.group(2)[:3].lower()], m.group(1))
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", bas)  # 30.07.2026
    if m:
        return kur(m.group(3), m.group(2), m.group(1))
    return None


def _tarih_ayikla(html):
    """Katmanlı çıkarım: (1) makale-kapsamlı meta/JSON-LD, (2) makale
    sınıflı <time>, (3) sayfadaki datePublished <time>'lar TEK benzersiz
    değerse o, (4) makale başındaki GÖRÜNÜR tarih.
    Birden çok aday varsa BELİRSİZ → None (yanlış karar verme)."""
    for kalip in TARIH_META_KALIPLARI:
        m = re.search(kalip, html, re.I)
        if m:
            t = _gecerli_tarih(m.group(1))
            if t:
                return t
    for kalip in TARIH_TIME_KALIPLARI:
        m = re.search(kalip, html, re.I)
        if m:
            t = _gecerli_tarih(m.group(1))
            if t:
                return t
    tarihler = set(re.findall(
        r'itemprop=["\']datePublished["\'][^>]*datetime=["\'](\d{4}-\d{2}-\d{2})', html))
    tarihler |= set(re.findall(
        r'datetime=["\'](\d{4}-\d{2}-\d{2})[^"\']*["\'][^>]*itemprop=["\']datePublished["\']', html))
    if len(tarihler) == 1:
        return tarihler.pop()
    return _gorunur_tarih(html)


# ⚠ Exa bazı sayfalardan metnin YALNIZCA küçük bir parçasını döndürüyor
# (JS ile kurulan sayfalar, Türkçe haber siteleri, kayıt duvarları). Boru
# hattı bunu fark etmiyordu: aday kaydına ne geldiyse onu yazım modeline
# veriyordu ve model "kaynakta olmayanı yazma" kuralına uyarak KISA metin
# üretiyordu. Gerçek vaka (nükleer, Sayı 1): ANS'ın TerraPower haberinde
# sayfada 5.520 karakter varken bültende 463 karakter yazıldı; ekonomim'in
# Çin haberinde 1.976'ya karşılık 493.
#
# Sayfayı tarih ve og:image için ZATEN indiriyoruz — aynı indirmeden gövde
# metnini de çıkarıyoruz. Ek ağ maliyeti YOK.
_TEMIZLE_ETIKET = re.compile(
    r"<(script|style|noscript|svg|template)\b[^>]*>.*?</\1>|<!--.*?-->",
    re.I | re.S)
_ARTICLE_BLOK = re.compile(r"<article\b[^>]*>(.*?)</article>", re.I | re.S)
_PARAGRAF = re.compile(r"<p\b[^>]*>(.*?)</p>", re.I | re.S)
_IC_ETIKET = re.compile(r"<[^>]+>")
PARAGRAF_ASGARI = 40          # bundan kısa <p> genelde altyazı/menü


def _govde_metni(html):
    """HTML'den makale gövdesini çıkar. Bağımlılık yok — <p> temelli."""
    if not html:
        return ""
    temiz = _TEMIZLE_ETIKET.sub(" ", html)
    bloklar = _ARTICLE_BLOK.findall(temiz)
    kapsam = max(bloklar, key=len) if bloklar else temiz
    paragraflar = []
    for ham in _PARAGRAF.findall(kapsam):
        t = html_mod.unescape(_IC_ETIKET.sub(" ", ham))
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) >= PARAGRAF_ASGARI:
            paragraflar.append(t)
    return "\n\n".join(paragraflar)[:AYARLAR["exa_metin_karakter"]]


# ⚠ ÖLÜ KAYNAK BAĞLANTISI
# Exa'nın dizininde, artık var olmayan bir sayfanın metni durabiliyor: aday
# metinle birlikte geliyor, haber yazılıyor, ama okuyucu bağlantıya
# tıkladığında sitenin ANA SAYFASINA düşüyor. Gerçek vaka (biyoekonomi,
# Sayı 2): Aleph Farms haberinin birincil kaynağı
# foodingredientsfirst.com/news/aleph-farms-singapore-cultivated-beef-approval.html
# idi; adres foodingredientsfirst.com köküne yönleniyordu. Olayın üç
# erişilebilir kaynağı daha vardı ama boru hattı bunu fark etmedi.
#
# ⚠ 403 ÖLÜ SAYILMAZ: birçok yayın bot koruması yüzünden 403 döndürür ama
# sayfa tarayıcıda açılır (euractiv.com böyle). Ağ hatası da ölü değildir —
# geçici kesinti yüzünden geçerli kaynağı düşürmeyelim.
_KOK_YOLLAR = {"", "news", "home", "index.html", "index.php", "articles"}
OLU = "ÖLÜ"          # sayfa_bilgisi'nin tarih yerine döndürdüğü işaret


def _olu_baglanti(r, istenen):
    """Yanıt, istenen makaleye DEĞİL sitenin köküne mi düştü?"""
    if r.status_code in (404, 410):
        return True
    if r.status_code != 200:
        return False                      # 403/5xx → karar verme
    varilan = urlparse(r.url).path.strip("/").lower()
    if varilan in _KOK_YOLLAR:
        # istenen adres zaten kök değilse, kökte bitmek "sayfa yok" demektir
        return urlparse(istenen).path.strip("/").lower() not in _KOK_YOLLAR
    return False


def sayfa_bilgisi(url):
    """Makale sayfasını çek → (gerçek yayın tarihi, og görseli, gövde metni).
    Ağ hatası / bulunamadı / belirsiz tarih → (None, ...); akış etkilenmez.

    Bağlantı ölüyse tarih yerine "ÖLÜ" işareti döner — çağıran kaynağı düşürür.
    """
    try:
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BultenBot/1.0)"})
        if _olu_baglanti(r, url):
            return OLU, None, ""
        if r.status_code != 200:
            return None, None, ""
        html = r.text[:150000]
    except Exception:
        return None, None, ""

    tarih = _tarih_ayikla(html)

    gorsel = None
    for kalip in OG_GORSEL_KALIPLARI:
        m = re.search(kalip, html, re.I)
        if m and gorsel_gecerli(m.group(1)):
            gorsel = m.group(1)
            break
    return tarih, gorsel, _govde_metni(html)


def tarih_dogrula(olaylar, pencere):
    """Olayların birincil kaynak sayfalarını çekip gerçek tarihi doğrula.

    · Sayfadaki gerçek tarih pencere dışıysa → olay TAMAMEN atılır
      (radar dahil hiçbir yerde görünmez)
    · Tarih bulunduysa kaynak kaydına yazılır → bültende doğru görünür
    · Sayfanın og:image'ı toplanır → görsel bağlamada birinci öncelik
    Dönen: (kalan olaylar, url→görsel sözlüğü)
    """
    bugun = datetime.now(timezone.utc).date()
    onbellek, sayfa_gorselleri = {}, {}
    kalan, atilan, zenginlesen, olu = [], 0, 0, 0

    for o in olaylar[:60]:          # maliyet/süre sınırı — kullanılan en çok 40
        # ── Ölü birincil bağlantıyı düşür, sıradakini birincil yap ──
        # Olayın başka erişilebilir kaynağı varsa haber kurtulur; hiç
        # kalmazsa olay tamamen atılır (okuyucunun açamadığı tek kaynak,
        # eksik haberden kötüdür).
        while o["kaynaklar"]:
            u0 = o["kaynaklar"][0]["url"]
            if u0 not in onbellek:
                onbellek[u0] = sayfa_bilgisi(u0)
            if onbellek[u0][0] is not OLU:
                break
            olu += 1
            log(f"  ✗ ölü kaynak bağlantısı (site köküne yönleniyor): "
                f"{o['kaynaklar'][0]['domain']} — {(o.get('baslik_ozet') or '')[:44]}")
            o["kaynaklar"].pop(0)
            if o["kaynaklar"]:
                o["kaynaklar"][0]["primary"] = True
        if not o["kaynaklar"]:
            atilan += 1
            log(f"  ✗ olay atıldı — erişilebilir kaynağı kalmadı: "
                f"{(o.get('baslik_ozet') or '')[:55]}")
            continue

        k = o["kaynaklar"][0]
        url = k["url"]
        tarih, gorsel, sayfa_metni = onbellek[url]

        if gorsel:
            sayfa_gorselleri[url_normalize(url)] = {
                "url": gorsel, "credit": k["domain"], "type": "og-sayfa"}

        # Exa metni ince kaldıysa sayfadan çıkardığımızla değiştir — yazım
        # modeli kaynakta olmayanı yazmadığı için ince metin KISA haber demek.
        eski = k.get("text") or ""
        if len(sayfa_metni) >= METIN_ASGARI and len(sayfa_metni) > len(eski) * METIN_KAT:
            k["text"] = sayfa_metni
            zenginlesen += 1
            log(f"  ↑ kaynak metni sayfadan zenginleştirildi "
                f"({len(eski)} → {len(sayfa_metni)} krkt) [{k['domain']}]")


        if tarih:
            k["published_date"] = tarih          # görünen tarihi düzelt
            o["tarih_dogrulandi"] = True
            try:
                yas = (bugun - datetime.strptime(tarih, "%Y-%m-%d").date()).days
            except ValueError:
                yas = None
            if yas is not None and (yas > pencere + 1 or yas < -1):
                atilan += 1
                log(f"  ✗ gerçek tarih pencere dışı ({tarih}): "
                    f"{(o.get('baslik_ozet') or '')[:55]} [{k['domain']}]")
                continue
        else:
            # ⚠ Sayfada hiçbir tarih bulunamadı — pencere denetimi bu olay
            # için ÇALIŞMADI, Exa'nın tarihi olduğu gibi kalıyor. Elemiyoruz
            # (bazı meşru kaynaklar tarih yayımlamıyor) ama raporda görünsün:
            # Sayı 1'de ans.org'un iki haberi tam olarak buradan sızmıştı.
            o["tarih_dogrulandi"] = False
            log(f"  ? tarih doğrulanamadı, Exa tarihi kullanılıyor "
                f"({k.get('published_date')}): "
                f"{(o.get('baslik_ozet') or '')[:48]} [{k['domain']}]")
        kalan.append(o)

    kalan += olaylar[60:]
    dogrulanamayan = sum(1 for o in kalan if o.get("tarih_dogrulandi") is False)
    log(f"Tarih doğrulama: {len(onbellek)} sayfa çekildi · {atilan} olay atıldı · "
        f"{olu} ölü kaynak bağlantısı düşürüldü · "
        f"{len(sayfa_gorselleri)} sayfa görseli · {zenginlesen} kaynak metni zenginleşti · "
        f"{dogrulanamayan} olayın tarihi doğrulanamadı")
    return kalan, sayfa_gorselleri


# ============================================================
# 6.5) GÖRSEL BAĞLAMA
# ============================================================
def og_gorsel_cek(url):
    """Son çare: makalenin OG görselini HTML'den çek."""
    return sayfa_bilgisi(url)[1]


# ⚠ Bazı yayınlar HOTLINK KORUMASI uyguluyor: görsel kendi sayfalarında
# açılıyor ama Referer başka bir alan adıysa sunucu reddediyor. Bizim
# tarafta hiçbir hata görünmez — og:image etiketi okunur, URL kaydedilir,
# ama okuyucunun tarayıcısı görseli çekemez ve haber görselsiz görünür.
# Gerçek vaka (yarı iletken, Sayı 1): donanimhaber.com'un og:image'ı
# bültende hiç yüklenmedi; aynı olayın bloomberght kaynağındaki görsel
# sorunsuz çalışıyordu ama sıraya hiç gelmemişti.
# Çözüm: seçilen görsel, bültenin kendi adresi Referer olarak gönderilerek
# denenir; geçmezse bir sonraki aday görsele düşülür.
GORSEL_DENETIM_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")


def gorsel_erisilebilir(url, onbellek=None):
    """Görsel DIŞ bir siteden çekilebiliyor mu? Ağ hatasında KABUL et —
    geçici bir kesinti yüzünden çalışan görseli atmayalım."""
    if onbellek is not None and url in onbellek:
        return onbellek[url]
    sonuc = True
    try:
        # Başlıklar, okuyucunun tarayıcısının yapacağı çapraz kaynaklı
        # <img> isteğini taklit eder — bazı korumalar Sec-Fetch-* başlıklarına
        # da bakıyor, eksik gönderirsek yanlış "erişilebilir" kararı çıkar.
        r = requests.get(url, timeout=8, stream=True, headers={
            "User-Agent": GORSEL_DENETIM_UA,
            "Referer": SITE_URL.rstrip("/") + "/",
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        })
        tur = (r.headers.get("content-type") or "").lower()
        r.close()
        # Yalnızca KESİN ret durumunda ele: sunucu hata döndürdü ya da
        # görsel yerine HTML (engel sayfası) verdi.
        if r.status_code != 200 or not tur.startswith("image/"):
            sonuc = False
    except requests.RequestException:
        sonuc = True                      # ağ sorunu — karar verme, koru
    if onbellek is not None:
        onbellek[url] = sonuc
    return sonuc


# ⚠ Birincil kaynağın sayfa görseli HER ZAMAN en iyisi değil. Gerçek vaka
# (biyoekonomi, Sayı 2): World Biogas Association haberine kurumun LOGOSU
# (WBA-wheel-in-square-transparent.png), Hindistan haberine ise sitenin genel
# amaçlı STOK görseli (bigstock-Growth-And-Expansion-44625217.jpg) düştü.
# İkisi de erişilebilir olduğu için "ilk çalışan adayı al" kuralına takılmadı.
# Çözüm: dosya adından şüpheli olanları listenin SONUNA at — elenmezler,
# yalnızca habere özel bir görsel varsa o öne geçer.
GORSEL_SUPHELI_IZLER = (
    "logo", "-transparent", "favicon", "sprite", "avatar", "placeholder",
    "default", "generic", "banner", "header", "watermark", "no-image",
    "bigstock", "shutterstock", "istock", "gettyimages", "depositphotos",
    "adobestock", "dreamstime", "stock-photo", "stockphoto",
)


GORSEL_AZAMI_ADAY = 4        # haber başına denetlenecek azami aday (istek sınırı)


def gorsel_supheli(url):
    """Dosya adı stok görseli / logo olduğunu düşündürüyor mu?"""
    u = (url or "").lower()
    if any(iz in u for iz in GORSEL_SUPHELI_IZLER):
        return True
    # 150x150 gibi küçük kare boyut adı → çoğunlukla küçük resim/ikon
    return bool(re.search(r"[-_](\d{2,3})x\1[._]", u))


def gorselleri_bagla(taslak, adaylar, olaylar=None, sayfa_gorselleri=None):
    """TÜM haberlere (yedekler dahil) görsel bağla — takas sonrası da görsel olsun.

    Öncelik: (1) makale sayfasından doğrulanmış og:image (tarih_dogrula
    çekti — en güvenilir), (2) Exa'nın verdiği görsel, (3) olayın diğer
    kaynaklarındaki görsel, (4) son çare OG çekimi.
    Her aday, bağlanmadan önce dış siteden çekilebilirlik denetiminden geçer."""
    sayfa_gorselleri = sayfa_gorselleri or {}
    idx = {}
    for a in adaylar:
        if a.get("image"):
            # ⚠ anahtar NORMALİZE edilmeli — aramalar url_normalize ile yapılıyor.
            # Ham URL ile anahtarlanırken bu katman pratikte hiç eşleşmiyordu.
            idx[url_normalize(a["url"])] = {
                "url": a["image"], "credit": a["domain"], "type": "og"}

    olay_gorsel = {}
    for o in (olaylar or []):
        g = next((k.get("image") for k in o.get("kaynaklar", []) if k.get("image")), None)
        if g:
            for k in o.get("kaynaklar", []):
                olay_gorsel[url_normalize(k["url"])] = {
                    "url": g, "credit": k["domain"], "type": "og"}

    stories = taslak.get("stories") or []
    bagli, kaynaksiz, elenen = 0, 0, 0
    denetim = {}
    for st in stories:
        urller = [(st.get("source") or {}).get("url")]
        urller += [k.get("url") for k in (st.get("supporting_sources") or [])]
        urller = [url_normalize(u) for u in urller if u]

        # Tüm adaylar öncelik sırasıyla; aynı URL bir kez.
        adaylar_g, gorulen = [], set()
        for aday in ([sayfa_gorselleri[u] for u in urller if u in sayfa_gorselleri]
                     + [idx[u] for u in urller if u in idx]
                     + [olay_gorsel[u] for u in urller if u in olay_gorsel]):
            if aday["url"] not in gorulen:
                gorulen.add(aday["url"])
                adaylar_g.append(aday)
        # Şüpheliler (logo/stok) sıranın SONUNA — sadece başka aday yoksa seçilir.
        adaylar_g.sort(key=lambda a: gorsel_supheli(a["url"]))

        # Erişilebilir olanları topla: ilki bağlanır, kalanlar hakemin
        # "değiştir" panelinde alternatif olarak sunulur.
        erisilebilir = []
        for aday in adaylar_g[:GORSEL_AZAMI_ADAY]:
            if gorsel_erisilebilir(aday["url"], denetim):
                erisilebilir.append(aday)
                continue
            elenen += 1
            log(f"  ✗ görsel dış siteden çekilemiyor (hotlink engeli?): "
                f"{aday['credit']} — {(st.get('title') or '?')[:45]}")

        if erisilebilir:
            st["image"] = erisilebilir[0]
            if gorsel_supheli(erisilebilir[0]["url"]):
                log(f"  ⚠ yalnızca şüpheli görsel bulundu (logo/stok olabilir): "
                    f"{erisilebilir[0]['url'][:70]} — {(st.get('title') or '?')[:40]}")
            bagli += 1
        else:
            st["image"] = {"url": None, "credit": None, "type": None}
            kaynaksiz += 1
        # Hakem "değiştir" panelinde görsün diye alternatifler taslakta kalır.
        # (publish.nihai_kur bu alanı yayına çıkarmadan siler.)
        st["gorsel_adaylari"] = erisilebilir[1:]

    # Son çare: görselsiz ÖNE ÇIKAN haberler için OG etiketi çek (≤6 istek)
    cekilen = 0
    for st in stories:
        if st.get("secim") != "one_cikan" or (st.get("image") or {}).get("url") or cekilen >= 6:
            continue
        u = (st.get("source") or {}).get("url")
        og = og_gorsel_cek(u) if u else None
        if og and gorsel_erisilebilir(og, denetim):
            st["image"] = {"url": og, "credit": (st.get("source") or {}).get("name"),
                           "type": "og-fetch"}
            bagli += 1; kaynaksiz -= 1; cekilen += 1

    log(f"Görsel bağlandı: {bagli} haber (OG çekilen: {cekilen}) · "
        f"erişilemediği için elenen aday: {elenen} · görselsiz: {kaynaksiz}")
    return bagli


# ============================================================
# MOCK — API'siz test taslağı
# ============================================================
def mock_taslak(sayi_no, bas, bit, pencere):
    def st(i, secim, kat, baslik):
        return {
            "id": f"event_{i:03d}", "secim": secim,
            "title": baslik,
            "excerpt": f"Örnek özet {i}: yatırım 8 milyar dolar değerinde, "
                       f"kapasite 40 bin wafer/ay. Bu bir test metnidir, gerçek haber değildir.",
            "detail": ("Bu bir TEST haberidir; gerçek bir gelişmeyi yansıtmaz.\n\n"
                       "İkinci paragraf: proje kapsamında 40 bin wafer/ay "
                       "kapasiteli bir fab planlanıyor, toplam yatırım "
                       "8 milyar dolar.\n\n"
                       "Üçüncü paragraf: takvim paylaşılmadı."),
            "neden_onemli": None, "category": kat, "subcategories": [],
            "value_chain": ["wafer-uretim"], "maturity": "announced",
            "companies": ["Örnek A.Ş."], "countries": ["Taiwan"],
            "technologies": ["FinFET"], "technology_nodes": ["28nm"],
            "capacity": "40 bin wafer/ay",
            "investment": {"amount_original": 8000, "currency": "USD",
                           "amount_usd_million": 8000,
                           "public_support_usd_million": None},
            "published_date": bit,
            "source": {"name": "example.org", "url": f"https://example.org/haber-{i}",
                       "type": "trade_press", "tier": 2, "primary": True},
            "supporting_sources": [],
            "image": {"url": None, "credit": None, "type": None},
            "score": 9 - (i % 5),
        }

    katlar = ["politika", "yatirim", "ekipman", "teknoloji",
              "paketleme", "bellek", "ai-cip", "turkiye", "rapor"]
    stories = [st(i + 1, "one_cikan", katlar[i % len(katlar)],
                  f"[TEST] Öne çıkan haber {i+1}: örnek yarı iletken gelişmesi")
               for i in range(9)]
    stories += [st(i + 10, "yedek", katlar[i % len(katlar)],
                   f"[TEST] Yedek haber {i+10}: takas için bekleyen gelişme")
                for i in range(5)]
    return {
        "brief": [{"text": f"[TEST] 60 saniyede madde {i+1} — örnek gelişme özeti.",
                   "ref": stories[i]["id"] if i < 3 else None} for i in range(5)],
        "lead_id": "event_001",
        "stories": stories,
        "radar": [
            {"kume": "İhracat kontrolleri",
             "maddeler": [{"title": f"[TEST] Radar maddesi {i+1}",
                           "source": "EE Times", "url": f"https://example.org/radar-{i}",
                           "date": bit, "category": "politika"} for i in range(4)]},
            {"kume": "Avrupa fab yatırımları",
             "maddeler": [{"title": f"[TEST] Radar maddesi {i+5}",
                           "source": "DigiTimes", "url": f"https://example.org/radar-{i+4}",
                           "date": bit, "category": "yatirim"} for i in range(4)]},
        ],
    }


# ============================================================
# DAVETİ YENİDEN GÖNDER — Exa/LLM çalıştırmadan
# ------------------------------------------------------------
# Taslak Neon'a davetlerden ÖNCE yazıldığı için, e-posta gönderimi
# başarısız olsa bile üretilen iş kaybolmaz (yalnızca hakemler linki
# alamaz). Tipik sebep: MAIL_FROM doğrulanmamış alan adında → Resend 403.
# Ayarı düzelttikten sonra bu komut daveti yeniden gönderir; pipeline'ı
# baştan çalıştırmaya gerek kalmaz (ne ücret ödenir ne taslak ezilir).
# ============================================================
def davet_yinele():
    import db
    import emails

    sayi = db.issue_getir(status="review")
    if not sayi:
        log("İnceleme bekleyen taslak yok — gönderilecek davet de yok")
        return 1

    taslak = sayi["draft_json"]
    if isinstance(taslak, str):
        taslak = json.loads(taslak)

    # publish.nihai_kur ile aynı seçim mantığı — manşet başlığı davette geçiyor
    secili = [s for s in (taslak.get("stories") or [])
              if s.get("secim") == "one_cikan"]
    lead = next((s for s in secili if s.get("id") == taslak.get("lead_id")), None)
    if not lead and secili:
        lead = max(secili, key=lambda s: s.get("score") or 0)

    hakemler = db.hakemler()
    if not hakemler:
        log("Kayıtlı hakem yok — önce: python db.py --seed \"Ad Soyad\" mail@ornek.com")
        return 1

    log(f"Sayı {sayi['sayi_no']} ({sayi['hafta']}) için davet yineleniyor — "
        f"{len(hakemler)} hakem")
    if not REVIEW_BASE_URL:
        log("  ⚠ REVIEW_BASE_URL tanımlı değil — linkler çalışmaz")

    gonderilen = 0
    for h in hakemler:
        link = f"{REVIEW_BASE_URL}/r/{h['token']}" if REVIEW_BASE_URL else "(REVIEW_BASE_URL yok)"
        ok = emails.davet_gonder(h, link, sayi["sayi_no"], sayi["hafta"],
                                 (lead or {}).get("title", "?"), len(secili))
        log(f"  {'✓' if ok else '✗'} {h['ad']} <{h['email']}>")
        if not ok:
            log(f"     link: {link}")     # gönderilemeyeni elle iletebilmek için
        gonderilen += bool(ok)

    log(f"Davet: {gonderilen}/{len(hakemler)} hakeme ulaştı")
    return 0 if gonderilen else 1


# ============================================================
# ANA AKIŞ
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="DB ve e-posta yok; taslak_preview.json üretir")
    ap.add_argument("--mock", action="store_true",
                    help="Exa/LLM yok; sahte taslak üretir")
    ap.add_argument("--davet-yinele", action="store_true",
                    help="Bekleyen taslağın davetlerini yeniden gönderir; "
                         "Exa/LLM çalıştırmaz, ücret doğurmaz")
    args = ap.parse_args()

    # Davet yinelemesi hiçbir arama/model anahtarı gerektirmez — anahtar
    # kontrolünden ÖNCE ele alınıyor.
    if args.davet_yinele:
        sys.exit(davet_yinele())

    if not args.mock and (not EXA_API_KEY or not os.environ.get("ANTHROPIC_API_KEY",
                          os.environ.get("OPENAI_API_KEY"))):
        sys.exit("HATA: EXA_API_KEY ve LLM anahtarı gerekli (veya --mock kullanın)")

    t0 = time.time()
    bugun = datetime.now(timezone.utc)
    log("═" * 46)
    log(f"YARI İLETKEN BÜLTENİ — TASLAK — {bugun.strftime('%Y-%m-%d')}")

    state = state_yukle()
    sayi_no = AYARLAR.get("sayi_no_sabit") or (son_sayi_no(state) + 1)
    hafta = iso_hafta(bugun)
    pencere = AYARLAR["pencere_gun"]
    kapsam_bas = (bugun - timedelta(days=pencere)).strftime("%Y-%m-%d")
    kapsam_bit = bugun.strftime("%Y-%m-%d")

    rapor = {"queries_run": 0, "results_found": 0, "dedup_removed": 0,
             "events_created": 0, "llm_rejected": 0, "written": 0,
             "radar_items": 0, "failed_queries": [],
             "tarih_dogrulanamayan": [], "uslup": None}
    karsilastirma = None          # KARSILASTIR_MODEL tanımlıysa doldurulur

    if args.mock:
        log("MOCK modu — Exa/LLM atlanıyor")
        b = mock_taslak(sayi_no, kapsam_bas, kapsam_bit, pencere)
        adaylar, olaylar, sayfa_gorselleri = [], [], {}
        derin, radar_havuz = [], []
    else:
        # --- Tarama (7 gün → yetersizse 14 gün) ---
        log(f"Exa taraması ({pencere} gün)…")
        adaylar, hatali = tara(pencere)
        log(f"Ham sonuç: {len(adaylar)}")

        if len(adaylar) < 40:
            pencere = AYARLAR["pencere_genis_gun"]
            kapsam_bas = (bugun - timedelta(days=pencere)).strftime("%Y-%m-%d")
            log(f"Yetersiz — pencere {pencere} güne genişletiliyor")
            adaylar, hatali = tara(pencere)
            log(f"Ham sonuç: {len(adaylar)}")

        rapor["queries_run"] = sum(1 + len(s.get("ek_sorgular", [])) for s in SORGULAR)
        rapor["results_found"] = len(adaylar)
        rapor["failed_queries"] = hatali

        adaylar, elenen = on_eleme(adaylar, state)
        rapor["dedup_removed"] = elenen
        if not adaylar:
            sys.exit("HATA: eleme sonrası aday kalmadı")

        # --- Aşama 1: triyaj ---
        log("Aşama 1 — triyaj…")
        olaylar, reject = triyaj(adaylar, kapsam_bas, kapsam_bit, state)
        # Partiler arası mükerrerleri temizle — triyaj bunu göremez
        olaylar, birlestirme_notlari = olaylari_birlestir(olaylar)
        rapor["birlestirilen_olay"] = len(birlestirme_notlari)
        rapor["birlestirme_notlari"] = birlestirme_notlari   # raporda tek tek görünsün
        olaylar = olaylari_zenginlestir(olaylar, adaylar)
        teyit_ara(olaylar, adaylar)

        # Exa tarihlerine güvenme — kaynak sayfalarından gerçek tarihi oku
        log("Tarih doğrulama (kaynak sayfaları çekiliyor — birkaç dk sürebilir)…")
        olaylar, sayfa_gorselleri = tarih_dogrula(olaylar, pencere)
        rapor["events_created"] = len(olaylar)
        rapor["llm_rejected"] = len(reject)

        # En yüksek puanlı D olay TAM METİNLE gider — HEPSİ haber yazılır.
        D = AYARLAR["derin_olay_sayisi"]
        T = AYARLAR["toplam_olay_sayisi"]
        yazilabilir = [o for o in olaylar if not o.get("sadece_radar")]
        duvarlilar = [o for o in olaylar if o.get("sadece_radar")]
        derin = yazilabilir[:D]
        radar_havuz = (yazilabilir[D:] + duvarlilar)[:T - D]
        log(f"Yazıma giden: {len(derin)} derin (tam metin) + {len(radar_havuz)} radar adayı")

        # Tarihi doğrulanamayan haberler: pencere denetimi bu olaylar için
        # ÇALIŞMADI, Exa tarihine güveniliyor. Elenmiyorlar (bazı meşru
        # kaynaklar tarih yayımlamıyor) ama raporda görünsünler — sistemin
        # en sessiz kör noktası burasıydı.
        rapor["tarih_dogrulanamayan"] = [
            f"{(o.get('baslik_ozet') or '?')[:58]} "
            f"[{o['kaynaklar'][0]['domain']}, "
            f"{o['kaynaklar'][0].get('published_date')}]"
            for o in derin if o.get("tarih_dogrulandi") is False]

        # --- Aşama 2: yazım ---
        log("Aşama 2 — yazım…")
        b = yaz(derin, radar_havuz, sayi_no, kapsam_bas, kapsam_bit, pencere)
        rapor["yazim_uyarisi"] = b.pop("_yazim_uyarisi", None)

        # --- opsiyonel: ikinci modelle aynı veriden yazım (yalnızca kıyas) ---
        if KARSILASTIR_MODEL:
            karsilastirma = model_karsilastir(
                KARSILASTIR_MODEL, derin, radar_havuz, sayi_no,
                kapsam_bas, kapsam_bit, pencere, b)

    # Kaynakları modelden GERİ AL — şema doğrulamasından da görsel
    # bağlamadan da ÖNCE, çünkü ikisi de source.url'e güveniyor.
    kaynak_notlari, dusen_haberler = kaynaklari_sabitle(b, derin, radar_havuz)
    kaynak_notlari += varlik_denetimi(b)
    for n in kaynak_notlari[:20]:
        log(f"  · {n}")
    rapor["kaynak_notlari"] = kaynak_notlari
    rapor["kaynaksiz_dusen"] = dusen_haberler

    rapor["uslup"] = uslup_ozeti(b.get("stories"))
    if rapor["uslup"]:
        u = rapor["uslup"]
        log(f"Üslup: ortalama {u['ortalama']} kelime/cümle · medyan {u['medyan']} · "
            f"{CUMLE_UST_SINIR} kelimeyi aşan {u['asan']} cümle (%{u['asan_yuzde']}) · "
            f"en uzun {u['en_uzun']}")

    hatalar = dogrula_taslak(b, kapsam_bas, kapsam_bit)
    if hatalar:
        log(f"⚠ {len(hatalar)} şema uyarısı")
        for h in hatalar[:10]:
            log(f"  ! {h}")

    gorselleri_bagla(b, adaylar, olaylar, sayfa_gorselleri)

    for st in (b.get("stories") or []):     # geçici alanları temizle
        st.pop("_kaynak_metni", None)

    stories = b.get("stories") or []
    rapor["written"] = len(stories)
    rapor["radar_items"] = sum(len(k.get("maddeler", [])) for k in b.get("radar", []))

    taslak = {
        "issue": {
            "number": sayi_no,
            "hafta": hafta,
            "draft_date": bugun.strftime("%Y-%m-%d"),
            "coverage_start": kapsam_bas,
            "coverage_end": kapsam_bit,
            "window_days": pencere,
        },
        "brief": b.get("brief", []),
        "lead_id": b.get("lead_id"),
        "stories": stories,
        "radar": b.get("radar", []),
        "hatalar": hatalar,
    }

    mm, mt = llm.maliyet_raporu()          # model (Haiku + yazım)
    em, et = exa_maliyet()                 # arama
    rapor["maliyet_model_usd"] = round(mt, 3)
    rapor["maliyet_exa_usd"] = round(et, 3)
    rapor["maliyet_usd"] = round(mt + et, 3)   # genel toplam

    lead = next((s for s in stories if s.get("id") == taslak["lead_id"]),
                stories[0] if stories else {})
    secili_sayi = sum(1 for s in stories if s.get("secim") == "one_cikan")

    # ── SADECE KIYAS MODU ──────────────────────────────────────────
    # SADECE_KARSILASTIR tanımlıysa: taslak Neon'a YAZILMAZ, hakemlere davet
    # GİTMEZ, yalnızca karşılaştırma e-postası (tek alıcı: RAPOR_ALICI) gider.
    # Böylece model denemesi tekrarlanırken incelemedeki taslak ezilmez ve
    # diğer yöneticilere mükerrer davet düşmez.
    if KIYAS_MODU:
        log("SADECE KIYAS MODU — taslak kaydedilmedi, davet gönderilmedi")
        if karsilastirma and RAPOR_ALICI:
            import emails
            emails.rapor_gonder(
                RAPOR_ALICI,
                f"[Kıyas] Sayı {sayi_no} — {AYARLAR['model_yazim']} vs {KARSILASTIR_MODEL}",
                karsilastirma + f"\n\nTOKEN VE MALİYET (tüm adımlar)\n{mm}")
            log("Karşılaştırma e-postası gönderildi")
        elif not karsilastirma:
            log("! Karşılaştırma üretilemedi — KARSILASTIR_MODEL tanımlı mı?")
        log(f"Tamamlandı — {time.time() - t0:.0f} sn · tahmini maliyet ${mt:.3f}")
        log("═" * 46)
        return

    if args.dry_run:
        with open("taslak_preview.json", "w", encoding="utf-8") as f:
            json.dump(taslak, f, ensure_ascii=False, indent=2)
        log("DRY RUN — DB/e-posta atlandı → taslak_preview.json yazıldı")
        if karsilastirma:
            with open("model_karsilastirma.txt", "w", encoding="utf-8") as f:
                f.write(karsilastirma)
            log("Model karşılaştırması → model_karsilastirma.txt")
    else:
        import db
        import emails
        issue_id = db.taslak_kaydet(hafta, sayi_no, taslak, rapor)
        db.logla(issue_id, None, "taslak_olusturuldu",
                 {"stories": len(stories), "secili": secili_sayi})
        log(f"Taslak Neon'a kaydedildi (issue_id={issue_id})")

        # --- Hakemlere davet ---
        hakemler = db.hakemler()          # bir kez çek, hem davette hem raporda kullan
        gonderilen = 0
        for h in hakemler:
            link = f"{REVIEW_BASE_URL}/r/{h['token']}" if REVIEW_BASE_URL else "(REVIEW_BASE_URL yok)"
            if emails.davet_gonder(h, link, sayi_no, hafta,
                                   lead.get("title", "?"), secili_sayi):
                gonderilen += 1
        log(f"Davet e-postası: {gonderilen} hakeme gönderildi")
        # Hakem VAR ama hiçbirine ulaşılamadıysa bu sessiz değil, GÜRÜLTÜLÜ bir
        # hatadır: taslak Neon'da bekler, kimse linkini bilmez, Pazartesi yayın
        # olmaz. En sık sebebi MAIL_FROM'un doğrulanmamış alan adı olması.
        if hakemler and gonderilen == 0:
            log("  ⚠⚠ HİÇBİR DAVET GİTMEDİ — taslak incelemesiz kalacak.")
            log("     Genellikle MAIL_FROM doğrulanmamış alan adında olur "
                "(Resend 403). Düzeltip şunu çalıştırın: "
                "python pipeline.py --davet-yinele")

        # --- Çalışma raporu (hakemler + RAPOR_ALICI) ---
        # Koşul artık RAPOR_ALICI'ya bağlı DEĞİL: rapor hakemlere de gittiği
        # için o değişken boş olsa bile gönderim yapılmalı.
        if hakemler or RAPOR_ALICI:
            govde = (
                f"Yarı İletken Bülteni — Sayı {sayi_no} Taslak Raporu\n"
                + (f"\n‼ DİKKAT — YAZIM EKSİK KALDI: {rapor['yazim_uyarisi']}\n"
                   f"  İki deneme de tamamlanmadı. Bülteni yayına almadan ÖNCE\n"
                   f"  eksikleri gözden geçirin.\n"
                   if rapor.get("yazim_uyarisi") else "")
                + f"{'=' * 52}\n"
                f"Kapsam        : {kapsam_bas} — {kapsam_bit} ({pencere} gün)\n\n"
                f"Sorgu çalıştırıldı : {rapor['queries_run']}\n"
                f"Ham sonuç          : {rapor['results_found']}\n"
                f"Deterministik elenen: {rapor['dedup_removed']}\n"
                f"Mükerrer birleşen  : {rapor.get('birlestirilen_olay', 0)}\n"
                + "".join(f"  ⇄ {n}\n"
                          for n in (rapor.get("birlestirme_notlari") or [])[:10]) +
                f"Olay oluşturuldu   : {rapor['events_created']}\n"
                f"LLM reddetti       : {rapor['llm_rejected']}\n"
                f"Yazılan haber      : {rapor['written']} ({secili_sayi} öne çıkan + "
                f"{rapor['written'] - secili_sayi} yedek)\n"
                f"Radar maddesi      : {rapor['radar_items']}\n\n"
                f"Exa'nın reddettiği alan adları: "
                f"{', '.join(sorted(YASAKLI_DOMAINLER)) or '(yok)'}\n\n"
                f"Başarısız sorgular : {len(rapor['failed_queries'])}\n"
                + "".join(f"  - {q}\n" for q in rapor["failed_queries"]) +
                f"\nÜSLUP (cümle disiplini)\n"
                + (f"  ortalama {rapor['uslup']['ortalama']} kelime/cümle · "
                   f"medyan {rapor['uslup']['medyan']} · "
                   f"en uzun {rapor['uslup']['en_uzun']} · "
                   f"{CUMLE_UST_SINIR} kelimeyi aşan: {rapor['uslup']['asan']} cümle "
                   f"(%{rapor['uslup']['asan_yuzde']})\n"
                   if rapor.get("uslup") else "  (ölçülemedi)\n") +
                f"\nTARİH DOĞRULAMA\n"
                f"  Tarihi doğrulanamayan haber: "
                f"{len(rapor.get('tarih_dogrulanamayan') or [])}\n"
                + "".join(f"  ? {t}\n"
                          for t in (rapor.get("tarih_dogrulanamayan") or []))
                + f"\nKAYNAK SABİTLEME\n"
                f"  Yayından düşen (kaynağı doğrulanamadı): "
                f"{len(rapor.get('kaynaksiz_dusen') or [])}\n"
                + "".join(f"  ✗ {t}\n" for t in (rapor.get("kaynaksiz_dusen") or []))
                + "".join(f"  · {n}\n" for n in (rapor.get("kaynak_notlari") or [])[:15]) +
                f"\nŞema uyarıları     : {len(hatalar)}\n"
                + "".join(f"  ! {h}\n" for h in hatalar[:15]) +
                f"\nMALİYET (bu sayının üretimi)\n{em}\n{mm}\n"
                f"  ══ GENEL TOPLAM ≈ ${mt + et:.3f}  (arama + model)\n\n"
                f"Durum: İNCELEME BEKLİYOR — davet {gonderilen} hakeme gitti.\n"
                f"{'=' * 52}\nLOG:\n" + "\n".join(LOG[-40:])
            )
            # Rapor artık TÜM hakemlere gidiyor (maliyet görünürlüğü için),
            # RAPOR_ALICI dahil — mükerrer adres olmasın diye tekilleştiriliyor.
            rapor_alicilari = list(dict.fromkeys(
                [h["email"] for h in hakemler] +
                ([RAPOR_ALICI] if RAPOR_ALICI else [])))
            # ⚠ Dönüş değeri KONTROL EDİLMELİ. Eskiden yok sayılıyordu ve log
            # alıcı sayısını basıyordu; Resend 403 dönerken bile "3 kişiye
            # gönderildi" yazıyordu. Sessiz hatayı gizleyen tam olarak buydu.
            rapor_ok = emails.rapor_gonder(
                rapor_alicilari,
                f"Yarı İletken Bülteni — Sayı {sayi_no} taslak hazır", govde)
            log(f"Çalışma raporu: {len(rapor_alicilari)} kişiye gönderildi" if rapor_ok
                else f"Çalışma raporu GÖNDERİLEMEDİ "
                     f"({len(rapor_alicilari)} alıcı) — yukarıdaki Resend hatasına bakın")

            # model karşılaştırması ayrı e-posta — rapor okunaklı kalsın
            if karsilastirma:
                emails.rapor_gonder(
                    RAPOR_ALICI,
                    f"[Karşılaştırma] Sayı {sayi_no} — {AYARLAR['model_yazim']} vs "
                    f"{KARSILASTIR_MODEL}", karsilastirma)
                log("Model karşılaştırma e-postası gönderildi")

    log("MALİYET")
    for satir in (em + "\n" + mm).split("\n"):
        log(satir)
    log(f"  ══ GENEL TOPLAM ≈ ${mt + et:.3f}  (arama ${et:.3f} + model ${mt:.3f})")
    log(f"Tamamlandı — {time.time() - t0:.0f} sn · tahmini maliyet ${mt + et:.3f}")
    log("═" * 46)


if __name__ == "__main__":
    main()
