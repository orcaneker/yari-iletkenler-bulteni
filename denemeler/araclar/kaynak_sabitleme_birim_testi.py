# -*- coding: utf-8 -*-
"""KAYNAK SABİTLEME BİRİM TESTİ — kaynaklari_sabitle() karar mantığı.

Yazım modeli tek promptta onlarca URL görüyor ve kaynak yazarken bunları
karıştırabiliyor; kaynağı olmayan bir gelişmeyi genel bilgisinden yazıp
üstüne başka bir olayın URL'ini iliştirebiliyor. Bu betik, sabitleme
adımının yanlış URL'i düzeltip kaynaksız haberi yayından düşürdüğünü
doğrular. Ağ ve API anahtarı gerekmez.

Kullanım (bu dizinden):  python kaynak_sabitleme_birim_testi.py
"""
import os, sys

from yollar import KOK  # noqa: F401  (repo kokunu sys.path'e ekler)
os.environ.setdefault("DATABASE_URL", "")
import pipeline as P    # noqa: E402

DOGRU = "https://ornek-resmi.org/duyuru/a"
YANLIS = "https://baska-yayin.com/makale/alakasiz-b"


def kaynak(url, metin=""):
    return {"name": P.domain_of(url), "domain": P.domain_of(url), "url": url,
            "published_date": "2026-07-28", "text": metin, "tier": 1,
            "paywall": False, "primary": True}


derin = [
    {"event_key": "olay-bir", "baslik_ozet": "Acme opens new plant",
     "sirketler": ["Acme"], "ulkeler": ["Germany"],
     "kaynaklar": [kaynak(DOGRU, "Acme yeni tesisini açtı.")]},
    {"event_key": "olay-iki", "baslik_ozet": "Zenith secures funding",
     "sirketler": ["Zenith"], "ulkeler": ["Japan"],
     "kaynaklar": [kaynak("https://ornek-resmi.org/duyuru/c", "Zenith fon sağladı.")]},
]
radar_havuz = [{"kaynaklar": [kaynak(YANLIS)]}]

taslak = {
    "stories": [
        # 1) id doğru, ama model URL'i radar kaleminden yapıştırmış → DÜZELTİLMELİ
        {"id": "olay-bir", "title": "Acme Almanya'da tesis açtı", "companies": ["Acme"],
         "source": {"url": YANLIS, "name": "Acme / Başka Yayın"}},
        # 2) id bozuk, ama URL doğru → URL basamağıyla eşleşmeli
        {"id": "event_002", "title": "Zenith fon sağladı", "companies": ["Zenith"],
         "source": {"url": "https://ornek-resmi.org/duyuru/c", "name": "x"}},
        # 3) hiçbir olaya karşılığı yok → ÇIKARILMALI
        {"id": "hayalet-olay", "title": "Kaynağı olmayan uydurma haber",
         "companies": ["Hayalet"], "source": {"url": YANLIS, "name": "y"}},
    ],
    "radar": [{"kume": "K", "maddeler": [
        {"title": "gecerli", "url": YANLIS},
        {"title": "havuzda-yok", "url": "https://uydurma.example/x"},
    ]}],
}

notlar, dusen = P.kaynaklari_sabitle(taslak, derin, radar_havuz)
s = taslak["stories"]
radar_urller = [m["url"] for k in taslak["radar"] for m in k["maddeler"]]

kontroller = [
    ("kaynağı olmayan haber çıkarıldı", len(dusen) == 1 and "uydurma" in dusen[0]),
    ("geçerli 2 haber korundu", len(s) == 2),
    ("yanlış URL düzeltildi", s[0]["source"]["url"] == DOGRU),
    ("melez kaynak adı temizlendi", s[0]["source"]["name"] == "ornek-resmi.org"),
    ("bozuk id URL ile eşleşti", s[1].get("event_key") == "olay-iki"),
    ("havuzda olmayan radar URL'i elendi", radar_urller == [YANLIS]),
]
print("--- KAYNAK SABİTLEME BİRİM TESTİ ---")
for ad, ok in kontroller:
    print(f"  {'✓' if ok else '✗'} {ad}")
_gecen = sum(1 for _, o in kontroller if o)
print(f"\n  {_gecen}/{len(kontroller)} geçti")
sys.exit(0 if all(ok for _, ok in kontroller) else 1)
