# -*- coding: utf-8 -*-
"""_destek_sec() — destek kaynağı kalabalığı ve aynı yayının tekrarı.

Gerçek vaka (yarı iletken Sayı 3, Sony/TSMC Kumamoto): habere sekiz destek
bağlantısı düşmüştü — 2 × asia.nikkei, 3 × digitimes, 1 × apps.digitimes,
dunya.com, ekonomim.com.
"""
import sys

from yollar import KOK, veri  # noqa: F401  (repo kokunu sys.path'e ekler)
import pipeline as p          # noqa: E402

hata = 0


def kontrol(ad, kosul):
    global hata
    hata += not kosul
    print(f"  {'✓' if kosul else '✗'} {ad}")


def k(dom, yol="a"):
    return {"name": dom, "domain": dom, "url": f"https://{dom}/{yol}"}


print("_yayin_koku() — aynı yayının farklı alt alan adları:")
for dom, bekle in (("asia.nikkei.com", "nikkei.com"),
                   ("apps.digitimes.com", "digitimes.com"),
                   ("digitimes.com", "digitimes.com"),
                   ("www.eetimes.com", "eetimes.com"),
                   ("bbc.co.uk", "bbc.co.uk"),
                   ("greenqueen.com.hk", "greenqueen.com.hk"),
                   ("news.bbc.co.uk", "bbc.co.uk")):
    v = p._yayin_koku(dom)
    kontrol(f"{dom:24} → {v}", v == bekle)

print("\n_destek_sec() — gerçek Sony/TSMC kaynak listesi:")
birincil = k("eetimes.com")
kaynaklar = [k("asia.nikkei.com", "1"), k("asia.nikkei.com", "2"),
             k("digitimes.com", "1"), k("digitimes.com", "2"),
             k("digitimes.com", "3"), k("apps.digitimes.com", "4"),
             k("dunya.com"), k("ekonomim.com")]
s = p._destek_sec(kaynaklar, birincil)
kokler = [p._yayin_koku(x["domain"]) for x in s]

kontrol(f"8 kaynak → {len(s)} destek (azami {p.DESTEK_AZAMI})",
        len(s) == p.DESTEK_AZAMI)
kontrol("aynı yayından yalnızca bir bağlantı", len(kokler) == len(set(kokler)))
kontrol("nikkei bir kez", kokler.count("nikkei.com") == 1)
kontrol("digitimes bir kez (apps. alt alanı dahil)",
        kokler.count("digitimes.com") == 1)
kontrol("sıra korunuyor — ilk üç farklı yayın seçildi",
        kokler == ["nikkei.com", "digitimes.com", "dunya.com"])

print("\n  birincil kaynağın yayını desteğe girmiyor:")
s2 = p._destek_sec([k("eetimes.com", "baska"), k("dunya.com")], k("eetimes.com"))
kontrol("aynı yayın destek olarak tekrarlanmıyor",
        [x["domain"] for x in s2] == ["dunya.com"])

print("\n  sınır durumları:")
kontrol("destek yoksa boş liste", p._destek_sec([], birincil) == [])
kontrol("tek destek aynen geçiyor",
        len(p._destek_sec([k("dunya.com")], birincil)) == 1)
kontrol("azamiden az destek kırpılmıyor",
        len(p._destek_sec([k("a.com"), k("b.com")], birincil)) == 2)

print(f"\n{'TÜMÜ GEÇTİ' if not hata else str(hata) + ' TEST BAŞARISIZ'}")
sys.exit(1 if hata else 0)
