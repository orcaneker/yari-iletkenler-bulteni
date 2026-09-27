# -*- coding: utf-8 -*-
"""TRİYAJ ŞEMA BİRİM TESTİ — eksik/bozuk alanlı triyaj çıktısı.

Gerçek vaka (kardeş proje biyoekonomi, 27 Eylül 2026, Render cron): triyaj modelinin döndürdüğü bir
olayda "baslik_ozet" alanı yoktu; boru hattı yazım mesajını kurarken
KeyError ile çöktü. Bu betik triyaj_olaylarini_onar'ın o kaydı onardığını
ve yazım mesajının eksik alanla bile kurulabildiğini kanıtlar.
Ağ ve API anahtarı gerektirmez.

Kullanım (bu dizinden):  python triyaj_sema_birim_testi.py
"""
import os
import sys

from yollar import KOK  # noqa: F401  (repo kokunu sys.path'e ekler)

os.environ.setdefault("DATABASE_URL", "")
import pipeline as P    # noqa: E402
import prompts          # noqa: E402

k = []


def ek(ad, kosul):
    k.append((ad, bool(kosul)))


adaylar = [
    {"id": "c01", "title": "Acme opens bioethanol plant in Brazil"},
    {"id": "c02", "title": "Zenith secures funding for mycoprotein"},
]
olaylar = [
    {"event_key": "tam", "baslik_ozet": "Tam olay", "primary_id": "c01",
     "supporting_ids": [], "kategori": "biyoyakit", "puan": 8},
    {"event_key": "ozetsiz", "primary_id": "c02", "kategori": "gida-protein",
     "puan": 7},                                          # 27 Eylül vakası
    {"event_key": "turkce-anahtar", "başlık_özet": "Türkçe anahtarlı özet",
     "primary_id": "c01", "supporting_ids": None, "puan": "6"},
    {"event_key": "yetim", "primary_id": "c99", "puan": 5},  # özet yok, aday yok
    "bozuk kayıt",
]

kalan, notlar = P.triyaj_olaylarini_onar(olaylar, adaylar)
by = {o["event_key"]: o for o in kalan}

ek("tam olay dokunulmadan geçti", by["tam"]["baslik_ozet"] == "Tam olay")
ek("eksik özet aday başlığından dolduruldu",
   by["ozetsiz"]["baslik_ozet"] == "Zenith secures funding for mycoprotein")
ek("Türkçe karakterli anahtar tanındı",
   by["turkce-anahtar"]["baslik_ozet"] == "Türkçe anahtarlı özet")
ek("None supporting_ids listeye çevrildi",
   by["turkce-anahtar"]["supporting_ids"] == [])
ek("metin puan sayıya çevrildi", by["turkce-anahtar"]["puan"] == 6)
ek("özetsiz ve kaynaksız olay atıldı", "yetim" not in by)
ek("sözlük olmayan kayıt atıldı", len(kalan) == 3)
ek("her onarım not düştü", len(notlar) == 4)

# Yazım mesajı eksik alanla bile kurulabilmeli (ikinci savunma hattı)
kaynak = {"name": "x.com", "domain": "x.com", "url": "https://x.com/a",
          "primary": True, "text": "metin"}
try:
    prompts.yazim_kullanici_mesaji(
        [{"event_key": "d1", "kaynaklar": [kaynak]}],
        [{"event_key": "r1", "kaynaklar": [kaynak]}],
        9, "2026-09-20", "2026-09-27", 7)
    ek("yazım mesajı eksik alanla kuruldu", True)
except KeyError as e:
    ek(f"yazım mesajı eksik alanla kuruldu (KeyError {e})", False)

# ============================================================
print("--- TRİYAJ ŞEMA BİRİM TESTİ ---")
for ad, ok in k:
    print(f"  {'✓' if ok else '✗'} {ad}")
gecen = sum(1 for _, o in k if o)
print(f"\n  {gecen}/{len(k)} geçti")
sys.exit(0 if gecen == len(k) else 1)
