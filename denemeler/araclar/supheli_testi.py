# -*- coding: utf-8 -*-
"""gorsel_supheli() — logo/stok görseli ayırt ediyor mu?"""
import os
import sys

from yollar import KOK, veri  # noqa: F401  (repo kokunu sys.path'e ekler)
import pipeline as p  # noqa: E402

ORNEKLER = [
    ("https://www.worldbiogasassociation.org/wp-content/uploads/2025/12/"
     "WBA-wheel-in-square-transparent.png", True, "WBA logosu (gerçek vaka)"),
    ("https://www.bioenergy-news.com/wp-content/uploads/2026/02/"
     "bigstock-Growth-And-Expansion-44625217.jpg", True, "Bigstock stok (gerçek vaka)"),
    ("https://www.bioenergy-news.com/wp-content/uploads/2026/08/"
     "Power-Wood-La-Crete-Peace-River-Plant-Earthworks-Aerial-scaled.jpg",
     False, "gerçek haber görseli"),
    ("https://www.foodnavigator.com/resizer/v2/XQYOXGCATVCNVH55UUCZEDE4VY.jpg"
     "?auth=abc&width=1200", False, "makale görseli"),
    ("https://ornek.com/uploads/site-logo.png", True, "logo"),
    ("https://ornek.com/uploads/foto-150x150.jpg", True, "küçük kare (ikon)"),
    ("https://ornek.com/uploads/shutterstock_88231.jpg", True, "Shutterstock"),
    ("https://ornek.com/uploads/tesis-2026-havadan.jpg", False, "normal"),
]

hata = 0
print("gorsel_supheli() denetimi:\n")
for u, bekle, ad in ORNEKLER:
    v = p.gorsel_supheli(u)
    ok = v == bekle
    hata += not ok
    print(f"  {'✓' if ok else '✗'} şüpheli={str(v):5} {ad:32} {u.split('/')[-1][:44]}")
print(f"\n{len(ORNEKLER) - hata}/{len(ORNEKLER)} geçti")
sys.exit(1 if hata else 0)
