# -*- coding: utf-8 -*-
"""TARİH RAPORU BİRİM TESTİ — doğrulanamayan tarih sayacı.

Hiçbir yerde tarih yayımlamayan bir sayfada pencere denetimi çalışmıyor.
Bu haberleri elemiyoruz (bazı meşru kaynaklar tarih vermiyor) ama sessiz de
kalmamalı. Bu betik, doğrulanamayanların ELENMEDİĞİNİ, işaretlendiğini ve
rapor satırının alan adı + tarihle kurulduğunu doğrular.

⚠ Pencere içi tarihler BUGÜNE GÖRELİ üretilir.

Kullanım (bu dizinden):  python tarih_raporu_birim_testi.py
"""
import os, sys
from datetime import datetime, timezone, timedelta

ICI = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()

from yollar import KOK  # noqa: F401  (repo kokunu sys.path'e ekler)
os.environ.setdefault("DATABASE_URL", "")
import pipeline as P    # noqa: E402


def olay(ad, url, dom, tarih):
    return {"baslik_ozet": ad, "kaynaklar": [{
        "url": url, "domain": dom, "name": dom, "published_date": tarih,
        "text": "m" * 900, "tier": 2, "paywall": False, "primary": True}]}


# sayfa_bilgisi: ans.org tarih vermiyor, digerleri veriyor
def sahte(url):
    if "ans.org" in url:
        return None, None, ""                      # tarih YOK
    if "eski.example" in url:
        return "2026-03-05", None, ""              # pencere disi
    return ICI, None, ""                          # saglam


P.sayfa_bilgisi = sahte

olaylar = [
    olay("dogrulanamayan bir", "https://ans.org/news/a-1", "ans.org", ICI),
    olay("dogrulanamayan iki", "https://ans.org/news/a-2", "ans.org", ICI),
    olay("saglam", "https://wnn.example/x", "wnn.example", ICI),
    olay("gercekten eski", "https://eski.example/y", "eski.example", ICI),
]

kalan, _ = P.tarih_dogrula(olaylar, 7)
bayrak = {o["baslik_ozet"]: o.get("tarih_dogrulandi") for o in kalan}

k = []
def ek(ad, kosul): k.append((ad, bool(kosul)))

ek("pencere dışı olay atıldı", all("eski" not in o["baslik_ozet"] for o in kalan))
ek("doğrulanamayan olaylar ELENMEDİ", len(kalan) == 3)
ek("doğrulanamayanlar False işaretli",
   bayrak.get("dogrulanamayan bir") is False and bayrak.get("dogrulanamayan iki") is False)
ek("doğrulanan True işaretli", bayrak.get("saglam") is True)

sayac = [o for o in kalan if o.get("tarih_dogrulandi") is False]
ek("sayaç 2 buluyor", len(sayac) == 2)

# rapor satiri main'deki ifadeyle ayni sekilde kuruluyor mu
satirlar = [f"{(o.get('baslik_ozet') or '?')[:58]} "
            f"[{o['kaynaklar'][0]['domain']}, "
            f"{o['kaynaklar'][0].get('published_date')}]"
            for o in sayac]
ek("rapor satırında alan adı ve tarih var",
   all("ans.org" in s and ICI in s for s in satirlar))

print("--- TARİH RAPORU BİRİM TESTİ ---")
for ad, ok in k:
    print(f"  {'✓' if ok else '✗'} {ad}")
print("\n  rapora düşecek satırlar:")
for s in satirlar:
    print(f"    ? {s}")
_gecen = sum(1 for _, o in k if o)
print(f"\n  {_gecen}/{len(k)} geçti")
sys.exit(0 if all(o for _, o in k) else 1)
