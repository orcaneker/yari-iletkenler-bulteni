# -*- coding: utf-8 -*-
"""kaynak_metni_kirp() + _kesin_ayni() — "Related Stories" zehirlenmesi.

Gerçek vaka (biyoekonomi Sayı 3): biomassmagazine.com JS ile kurulduğu için
sunucu HTML'inde makale gövdesi yok, "Related Stories" listesi var. Hem Exa
hem bizim çıkarıcımız o listeyi makale metni sandı.
"""
import sys

from yollar import KOK, veri  # noqa: F401  (repo kokunu sys.path'e ekler)
import pipeline as p          # noqa: E402

hata = 0


def kontrol(ad, kosul):
    global hata
    hata += not kosul
    print(f"  {'✓' if kosul else '✗'} {ad}")


print("kaynak_metni_kirp() — ilgisiz blok kesimi:")

GERCEK = (
    "American Airlines and Infinium announce commercial passenger flight "
    "powered by eSAF | Biomass Magazine\n\nSECTIONS\n\nSOURCE: American "
    "Airlines\n\nAugust 11, 2026\n\n## Related Stories\n\n"
    "## Montana Renewables begins next phase of MaxSAF expansion\n"
    "With the initial phase of its MaxSAF 150 initiative now complete...\n"
    "## Gevo cancels plans for South Dakota SAF plant\n"
    "Gevo Inc. on Aug. 6 announced it has cancelled plans...")
k = p.kaynak_metni_kirp(GERCEK)
kontrol("Related Stories bloğu kesildi", "Related Stories" not in k)
kontrol("Montana Renewables özeti gitti", "Montana" not in k)
kontrol("Gevo özeti gitti", "Gevo" not in k)
kontrol("kalan metin ince → duvarlı sayılır (radara düşer)",
        p.odeme_duvarli("biomassmagazine.com", k))

print("\n  diğer blok başlıkları:")
for iz in ("Latest News", "Most Read", "You may also like", "İlgili Haberler",
           "Upcoming Events", "Sponsored Content"):
    metin = "Gerçek makale gövdesi burada duruyor ve yeterince uzun. " * 4 \
            + f"\n\n{iz}\n\nBaşka haberin özeti."
    kontrol(f"'{iz}' kesiliyor",
            "Başka haberin özeti" not in p.kaynak_metni_kirp(metin))

print("\n  NORMAL makaleye dokunulmuyor:")
duz = ("Neste, Rotterdam rafinerisinde SAF kapasitesini artırdı. " * 12
       + "Yatırımın 2027'de tamamlanması bekleniyor.")
kontrol("işaret yoksa metin AYNEN kalıyor", p.kaynak_metni_kirp(duz) == duz)
kontrol("boş metin çökmüyor", p.kaynak_metni_kirp("") == "")
kontrol("None çökmüyor", p.kaynak_metni_kirp(None) is None)

print("\n_kesin_ayni() — yalnızca birincil örtüşmesi:")
a = {"primary_id": "c001", "supporting_ids": ["c009", "c010"]}
b = {"primary_id": "c001", "supporting_ids": ["c020"]}
c = {"primary_id": "c002", "supporting_ids": ["c009"]}          # destek örtüşür
d = {"primary_id": "c003", "supporting_ids": []}
e = {"primary_id": None, "supporting_ids": ["c009"]}

kontrol("aynı birincil → KESİN aynı olay", p._kesin_ayni(a, b) is True)
kontrol("yalnızca destek örtüşüyor → kesin DEĞİL (asıl hata buydu)",
        p._kesin_ayni(a, c) is False)
kontrol("hiç örtüşme yok → değil", p._kesin_ayni(a, d) is False)
kontrol("birincili olmayan olay eşleşmiyor", p._kesin_ayni(e, a) is False)
kontrol("iki birincilsiz olay eşleşmiyor",
        p._kesin_ayni(e, {"primary_id": None, "supporting_ids": ["c009"]}) is False)

print(f"\n{'TÜMÜ GEÇTİ' if not hata else str(hata) + ' TEST BAŞARISIZ'}")
sys.exit(1 if hata else 0)
