# -*- coding: utf-8 -*-
"""_olu_baglanti() — ölü bağlantıyı bot engelinden ayırt ediyor mu?"""
import sys

from yollar import KOK, veri  # noqa: F401  (repo kokunu sys.path'e ekler)
import pipeline as p          # noqa: E402


class Yanit:
    def __init__(self, kod, varilan):
        self.status_code, self.url = kod, varilan


MAKALE = "https://ornek.com/news/aleph-farms-singapore-approval.html"

DURUMLAR = [
    (Yanit(200, MAKALE), MAKALE, False, "sayfa açıldı"),
    (Yanit(200, "https://www.ornek.com/"), MAKALE, True, "site KÖKÜNE yönlendi"),
    (Yanit(200, "https://www.ornek.com/news"), MAKALE, True, "haber dizinine yönlendi"),
    (Yanit(404, MAKALE), MAKALE, True, "404"),
    (Yanit(410, MAKALE), MAKALE, True, "410 kalıcı silinmiş"),
    (Yanit(403, MAKALE), MAKALE, False, "403 bot engeli — ÖLÜ SAYILMAZ"),
    (Yanit(503, MAKALE), MAKALE, False, "503 geçici — ÖLÜ SAYILMAZ"),
    (Yanit(200, "https://www.ornek.com/news/aleph-farms-singapore-approval/"),
     MAKALE, False, "sonuna / eklenmiş, aynı sayfa"),
    # istenen adres zaten kök ise kökte bitmek normaldir
    (Yanit(200, "https://www.ornek.com/"), "https://ornek.com/", False,
     "kökten köke — sorun yok"),
]

hata = 0
print("_olu_baglanti() denetimi:\n")
for r, istenen, bekle, ad in DURUMLAR:
    v = p._olu_baglanti(r, istenen)
    ok = v == bekle
    hata += not ok
    print(f"  {'✓' if ok else '✗'} ölü={str(v):5} {ad}")

print(f"\n{len(DURUMLAR) - hata}/{len(DURUMLAR)} geçti")
sys.exit(1 if hata else 0)
