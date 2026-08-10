# -*- coding: utf-8 -*-
"""TARİH OKUMA BİRİM TESTİ — _tarih_ayikla() katman sırası.

Bazı yayınlar hiçbir makine-okur tarih etiketi vermiyor; tarih yalnızca
başlığın altında düz metin duruyor. O zaman pencere denetimi hiç çalışmıyor
ve Exa'nın (bazen yanlış) tarihi kabul ediliyordu. Bu betik, görünür tarihin
okunduğunu, "ilgili haberler" tarihlerine ATLANMADIĞINI ve metadata varsa
ona dokunulmadığını doğrular.

⚠ Pencere içi tarihler BUGÜNE GÖRELİ üretilir — tarih_dogrula yaşı bugüne
göre hesapladığı için sabit tarih yazmak testi günler ilerleyince kırar.

Kullanım (bu dizinden):  python tarih_okuma_birim_testi.py
"""
import os, sys
from datetime import datetime, timezone, timedelta

# ⚠ tarih_dogrula yasi BUGUNE gore hesapliyor; sabit tarih yazmak
# testi gunler ilerleyince kirar. Pencere ICI tarih goreli uretilir.
ICI = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()

from yollar import KOK  # noqa: F401  (repo kokunu sys.path'e ekler)
os.environ.setdefault("DATABASE_URL", "")
import pipeline as P    # noqa: E402

DOLGU = ("Bu paragraf makale gövdesini temsil eder ve kırk karakterden "
         "uzun olduğu için çıkarımda tutulur. " * 2)

# ans.org: hiç metadata yok, tarih başlıkta düz metin
ANS = f"""<html><head><title>NRC approves TerraPower construction permit</title></head>
<body><article>
<h1>NRC approves TerraPower construction permit</h1>
<span>Thu, Mar 5, 2026, 1:27AM</span><span>Nuclear News</span>
<p>{DOLGU}</p>
</article>
<aside><h3>Related</h3><p>Wed, Jul 29, 2026 baska bir makalenin tarihi burada duruyor</p></aside>
</body></html>"""

# metadata VAR → görünür tarihe hiç düşülmemeli
METADATALI = f"""<html><head>
<meta property="article:published_time" content="2026-07-28T09:10:14-0400">
</head><body><article><h1>DOE</h1><span>March 1, 2020</span><p>{DOLGU}</p></article></body></html>"""

TR = f"""<html><body><article><h1>Haber</h1>
<span>30.07.2026 14:05</span><p>{DOLGU}</p></article></body></html>"""

WNN = f"""<html><body><article><h1>TRISO</h1>
<span>Monday, 27 July 2026</span><p>{DOLGU}</p></article></body></html>"""

ISO = f"""<html><body><article><h1>X</h1><span>2026-08-01</span><p>{DOLGU}</p></article></body></html>"""

TARIHSIZ = f"""<html><body><article><h1>X</h1><p>{DOLGU}</p></article></body></html>"""

k = []
def ek(ad, kosul): k.append((ad, bool(kosul)))

ek("ans.org görünür tarihi okundu (2026-03-05)", P._tarih_ayikla(ANS) == "2026-03-05")
ek("ilgili-haberler tarihi ALINMADI", P._tarih_ayikla(ANS) != "2026-07-29")
ek("metadata varsa görünür tarihe düşülmüyor",
   P._tarih_ayikla(METADATALI) == "2026-07-28")
ek("Türkçe gg.aa.yyyy okundu", P._tarih_ayikla(TR) == "2026-07-30")
ek("'27 July 2026' okundu", P._tarih_ayikla(WNN) == "2026-07-27")
ek("ISO okundu", P._tarih_ayikla(ISO) == "2026-08-01")
ek("tarih yoksa None", P._tarih_ayikla(TARIHSIZ) is None)
ek("geçersiz tarih güvenli (32 Mart)",
   P._gorunur_tarih("<article><h1>x</h1><span>Mar 32, 2026</span></article>") is None)

# --- entegrasyon: pencere dışı olay ATILIYOR mu ---
P.sayfa_bilgisi = lambda url: ("2026-03-05", None, "")
olay = {"baslik_ozet": "TerraPower", "kaynaklar": [{
    "url": "https://ans.org/news/article-7818/x", "domain": "ans.org",
    "name": "ans.org", "published_date": "2026-07-29", "text": "m" * 900,
    "tier": 2, "paywall": False, "primary": True}]}
kalan, _ = P.tarih_dogrula([olay], 7)
ek("Mart tarihli olay pencere dışı diye ATILDI", len(kalan) == 0)

P.sayfa_bilgisi = lambda url: (ICI, None, "")
olay2 = {"baslik_ozet": "guncel", "kaynaklar": [{
    "url": "https://x.example/1", "domain": "x.example", "name": "x",
    "published_date": ICI, "text": "m" * 900, "tier": 2,
    "paywall": False, "primary": True}]}
kalan2, _ = P.tarih_dogrula([olay2], 7)
ek("pencere içi olay korundu", len(kalan2) == 1)

# --- event_date artık taslakta kalmıyor ---
taslak = {"stories": [{"id": "a", "title": "T", "excerpt": "e", "detail": "d",
                       "category": list(P.KATEGORILER)[0], "source": {"url": "u"},
                       "secim": "one_cikan", "event_date": "2026-07-24",
                       "published_date": "2026-07-28"}] * 1,
          "brief": [{"text": "x"}] * 5, "lead_id": "a", "radar": []}
P.dogrula_taslak(taslak)
ek("event_date taslaktan ayıklandı", "event_date" not in taslak["stories"][0])

print("--- TARİH OKUMA BİRİM TESTİ ---")
for ad, ok in k:
    print(f"  {'✓' if ok else '✗'} {ad}")
_gecen = sum(1 for _, o in k if o)
print(f"\n  {_gecen}/{len(k)} geçti")
sys.exit(0 if all(o for _, o in k) else 1)
