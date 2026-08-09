# -*- coding: utf-8 -*-
"""ÜSLUP DENETİMİ — "çeviri kokusu" ve prompt ihlallerini ölçer.

Dil denetimi (biçim) iki modelde de sıfırlandı; geriye AKICILIK kaldı.
Akıcılık öznel ama izleri nesnel:
  · cümle uzunluğu ÇEŞİTLİLİĞİ — tek düze kısa cümleler "makine" hissi verir
  · aynı ekle biten ardışık cümleler (…-yor. …-yor. …-yor.)
  · içerik taşımayan dolgu cümleleri (prompt bunları YASAKLIYOR)
  · kaynağın durumunu anlatan cümleler (prompt bunları da YASAKLIYOR)
"""
import json
import re
import statistics
import sys

DOLGU_IZLERI = [
    r"\bGelişme,",
    r"\bOlayın kapsamındaki\b",
    r"\bolarak sıralanıyor\b",
    r"\bdoğrudan ilgilendiriyor\b",
    r"\bfiziksel uygulama alanını oluşturuyor\b",
    r"\büzerinden tanımlandı\b",
    r"\bunsurları arasında yer aldı\b",
]
KAYNAK_IZLERI = [
    r"[Kk]aynak metinde", r"[Kk]aynak metninde", r"[Kk]aynakta .{0,24}(yok|bulunmuyor)",
    r"paylaşılmadı", r"detaylandırılmadı", r"belirtilmemiş",
    r"[Hh]aberin yayınlandığı", r"aynı içerikte", r"[Ee]lde bulunan",
    r"ulaşılamadı", r"bilgi bulunmuyor",
]


def cumleler(m):
    return [c.strip() for c in re.split(r"(?<=[.!?])\s+", m or "") if len(c.strip()) > 12]


def analiz(yol):
    d = json.load(open(yol, encoding="utf-8"))
    d = d.get("taslak") if isinstance(d.get("taslak"), dict) else d
    tum = " ".join(s.get("detail") or "" for s in d["stories"])
    c = cumleler(tum)
    uz = [len(x.split()) for x in c]

    # ardışık aynı ek: geniş zaman -yor/-iyor/-ıyor/-uyor
    yor = [bool(re.search(r"(ı|i|u|ü)yor\.?$", x.rstrip("."))) for x in c]
    ardisik = maks = 0
    for v in yor:
        ardisik = ardisik + 1 if v else 0
        maks = max(maks, ardisik)

    dolgu = sum(len(re.findall(p, tum)) for p in DOLGU_IZLERI)
    kaynak = sum(len(re.findall(p, tum)) for p in KAYNAK_IZLERI)
    baslik = [len((s.get("title") or "").split()) for s in d["stories"]]

    print(f"\n{yol}")
    print(f"  cümle sayısı            : {len(c)}")
    print(f"  ort. cümle uzunluğu     : {statistics.mean(uz):.1f} kelime")
    print(f"  cümle uzunluğu sapması  : {statistics.pstdev(uz):.1f}   "
          f"(düşük = tek düze ritim)")
    print(f"  kısa cümle payı (<12 kl): %{100 * sum(1 for u in uz if u < 12) / len(uz):.0f}")
    print(f"  '-yor' ile biten cümle  : %{100 * sum(yor) / len(c):.0f} "
          f"· en uzun ardışık dizi: {maks}")
    print(f"  ⛔ dolgu cümlesi izi     : {dolgu}")
    print(f"  ⛔ kaynağın durumu anlatılmış: {kaynak}")
    print(f"  ort. başlık uzunluğu    : {statistics.mean(baslik):.1f} kelime "
          f"(hedef 8-14)")


for y in sys.argv[1:]:
    analiz(y)
