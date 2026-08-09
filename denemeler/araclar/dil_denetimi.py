# -*- coding: utf-8 -*-
"""DİL DENETİMİ — Türkçeleştirme kurallarının ihlallerini sayar.

Kullanım:  python denemeler/araclar/dil_denetimi.py dosya1.json dosya2.json ...
"""
import json
import re
import sys

KURALLAR = [
    ("İngilizce ay adı",
     r"\b(January|February|March|April|June|July|August|September|October|November|December)\b"),
    ("İngilizce büyüklük (million/billion/thousand/tonnes)",
     r"\b(million|billion|thousand|tonnes|per cent)\b"),
    ("Anglo ondalık ($1.52 / US$3.2bn)",
     r"(?:US\$|CA\$|A\$|\$|€|£)\s?\d+(?:[.,]\d+)?\s?(?:bn|m\b|k\b)?|\b\d+\.\d+\s?(?:bn|m|million|billion)\b"),
    ("Anglo binlik ayırıcı (700,000)", r"\b\d{1,3},\d{3}\b"),
    ("Mali yıl kısaltması (FY2026-27)", r"\bFY\s?\d{4}"),
    ("Markdown işareti", r"(?m)^\s*[*\-#]\s|\*\*"),
    ("Para kısaltması (EUR 57m / DKK 182)",
     r"\b(EUR|USD|GBP|DKK|ZAR|SEK|NOK|CHF|JPY|CNY|INR)\s?\d"),
]


def denetle(yol):
    d = json.load(open(yol, encoding="utf-8"))
    d = d.get("taslak") if isinstance(d.get("taslak"), dict) else d
    metin = "\n".join((s.get("title") or "") + "\n" + (s.get("excerpt") or "")
                      + "\n" + (s.get("detail") or "") for s in d["stories"])
    metin += "\n" + "\n".join(m.get("text", "") for m in (d.get("brief") or []))
    print(f"\n{yol}   ({len(d['stories'])} haber)")
    toplam = 0
    for ad, kalip in KURALLAR:
        bul = re.findall(kalip, metin, re.I if "Markdown" not in ad else 0)
        toplam += len(bul)
        if bul:
            ornek = [b if isinstance(b, str) else next((x for x in b if x), "")
                     for b in bul[:4]]
            print(f"  ⚠ {ad:46} {len(bul):3}   ör: {', '.join(repr(o) for o in ornek)}")
        else:
            print(f"  ✓ {ad:46}   0")
    print(f"  ── TOPLAM İHLAL: {toplam}")
    return toplam


for y in sys.argv[1:]:
    denetle(y)
