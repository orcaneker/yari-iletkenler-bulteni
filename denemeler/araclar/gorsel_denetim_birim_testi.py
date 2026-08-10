# -*- coding: utf-8 -*-
"""GÖRSEL ERİŞİLEBİLİRLİK BİRİM TESTİ — gorsel_erisilebilir() + bağlama.

Bazı yayınlar hotlink koruması uyguluyor: görsel kendi sayfalarında açılıyor
ama Referer başka bir alan adıysa sunucu reddediyor. Boru hattı tarafında
hiçbir hata görünmediği için haber görselsiz yayınlanıyordu. Bu betik,
denetimin engelli görseli eleyip bir sonraki adaya düştüğünü doğrular.
requests taklit edilir; ağ gerekmez.

Kullanım (bu dizinden):  python gorsel_denetim_birim_testi.py
"""
import os, sys, types

from yollar import KOK  # noqa: F401  (repo kokunu sys.path'e ekler)
os.environ.setdefault("DATABASE_URL", "")
import pipeline as P    # noqa: E402
import requests


class SahteYanit:
    def __init__(self, kod, tur):
        self.status_code, self.headers = kod, {"content-type": tur}
    def close(self):
        pass


# alan adı → (durum kodu, içerik türü) | "AGHATASI" → istisna
DAVRANIS = {
    "www.donanimhaber.com": (403, "text/html; charset=utf-8"),   # hotlink engeli
    "geoim.bloomberght.com": (200, "image/jpeg"),
    "cdn.webrazzi.com": (200, "image/png"),
    "sessiz.example": (200, "text/html"),      # görsel yerine HTML döndüren
    "yok.example": (404, "text/html"),
    "kesinti.example": "AGHATASI",
}


def sahte_get(url, **kw):
    from urllib.parse import urlparse
    d = urlparse(url).netloc
    davranis = DAVRANIS.get(d, (200, "image/jpeg"))
    if davranis == "AGHATASI":
        raise requests.RequestException("baglanti kesildi")
    # başlıkların gerçekten gönderildiğini de doğrula
    h = kw.get("headers") or {}
    assert h.get("Referer", "").startswith("http"), "Referer gönderilmemiş"
    assert h.get("Sec-Fetch-Site") == "cross-site", "Sec-Fetch-Site eksik"
    return SahteYanit(*davranis)


requests.get = sahte_get
P.requests.get = sahte_get

D = "https://www.donanimhaber.com/img/a.jpg"
B = "https://geoim.bloomberght.com/l/x/jpg/960x540"
W = "https://cdn.webrazzi.com/uploads/a.png"

kontroller = []


def ek(ad, kosul):
    kontroller.append((ad, bool(kosul)))


# --- birim: erişilebilirlik kararı ---
ek("hotlink engeli (403+html) reddedildi", P.gorsel_erisilebilir(D) is False)
ek("geçerli görsel (200+image) kabul", P.gorsel_erisilebilir(B) is True)
ek("görsel yerine HTML reddedildi", P.gorsel_erisilebilir("https://sessiz.example/a.jpg") is False)
ek("404 reddedildi", P.gorsel_erisilebilir("https://yok.example/a.jpg") is False)
ek("ağ hatasında KORUNUYOR (fail-open)",
   P.gorsel_erisilebilir("https://kesinti.example/a.jpg") is True)

# --- önbellek: aynı URL iki kez sorulmuyor ---
sayac = {"n": 0}
_ger = sahte_get
def sayan(url, **kw):
    sayac["n"] += 1
    return _ger(url, **kw)
requests.get = P.requests.get = sayan
onb = {}
P.gorsel_erisilebilir(B, onb); P.gorsel_erisilebilir(B, onb); P.gorsel_erisilebilir(B, onb)
ek("önbellek çalışıyor (3 çağrı → 1 istek)", sayac["n"] == 1)
requests.get = P.requests.get = sahte_get

# --- entegrasyon: engelli görselden sonraki adaya düşüyor mu ---
taslak = {"stories": [{
    "title": "Samsung ile Broadcom 200 milyar dolarlık çip anlaşması imzaladı",
    "secim": "one_cikan",
    "source": {"url": "https://donanimhaber.com/haber/1", "name": "DonanımHaber"},
    "supporting_sources": [{"url": "https://bloomberght.com/haber/2"}],
}]}
sayfa_gorselleri = {
    P.url_normalize("https://donanimhaber.com/haber/1"):
        {"url": D, "credit": "donanimhaber.com", "type": "og-sayfa"},
    P.url_normalize("https://bloomberght.com/haber/2"):
        {"url": B, "credit": "bloomberght.com", "type": "og-sayfa"},
}
P.gorselleri_bagla(taslak, [], [], sayfa_gorselleri)
im = taslak["stories"][0]["image"]
ek("engelli birincil görsel atlandı", im["url"] != D)
ek("destek kaynağın görseli bağlandı", im["url"] == B)
ek("kredi destek kaynağa güncellendi", im["credit"] == "bloomberght.com")

# --- entegrasyon: tek aday da engelliyse görselsiz kalır ---
taslak2 = {"stories": [{
    "title": "Tek kaynaklı haber", "secim": "yedek",
    "source": {"url": "https://donanimhaber.com/haber/9", "name": "DonanımHaber"},
    "supporting_sources": [],
}]}
P.gorselleri_bagla(taslak2, [], [], {
    P.url_normalize("https://donanimhaber.com/haber/9"):
        {"url": D, "credit": "donanimhaber.com", "type": "og-sayfa"}})
ek("alternatifi yoksa görselsiz (engelli URL yazılmıyor)",
   (taslak2["stories"][0]["image"] or {}).get("url") is None)

print("--- GÖRSEL ERİŞİLEBİLİRLİK BİRİM TESTİ ---")
for ad, ok in kontroller:
    print(f"  {'✓' if ok else '✗'} {ad}")
_gecen = sum(1 for _, o in kontroller if o)
print(f"\n  {_gecen}/{len(kontroller)} geçti")
sys.exit(0 if all(o for _, o in kontroller) else 1)
