# -*- coding: utf-8 -*-
"""BİRLEŞTİRME BİRİM TESTİ — üç katmanlı mimarinin karar mantığı.

Kardeşi birlestirme_testi.py CANLI testtir: gerçek sayı verisiyle gerçek
LLM'i çağırır, ücretlidir ve sonucunu insan okur. Bu betik ise LLM'i TAKLİT
eder; ağ ve API anahtarı gerektirmez, iddia üretir ve çıkış kodu döner.
Amaç: katmanların ve emniyet denetimlerinin doğru karar verdiğini kanıtlamak.

Katmanlar:
  1. KESİN            — ortak aday kaynağı, LLM'siz
  2. SAYI PARMAK İZİ  — ayırt edici sayı örtüşmesi + ortak sinyal, LLM'siz
  3. KÜRESEL KÜMELEME — kalan TÜM olaylar tek istemde; grup boyutu ve
                        ortak sinyal denetimleriyle sınırlanır

Kullanım (bu dizinden):  python birlestirme_birim_testi.py
"""
import json
import os
import sys

from yollar import KOK  # noqa: F401  (repo kokunu sys.path'e ekler)

os.environ.setdefault("DATABASE_URL", "")
import pipeline as P    # noqa: E402

k = []


def ek(ad, kosul):
    k.append((ad, bool(kosul)))


def olay(anahtar, ozet, pid, puan=7, sirket=None, ulke=None,
         kategori="biyoyakit", dest=None, yatirim=None):
    return {"event_key": anahtar, "baslik_ozet": ozet, "primary_id": pid,
            "supporting_ids": list(dest or []), "puan": puan,
            "sirketler": list(sirket or []), "ulkeler": list(ulke or ["United States"]),
            "kategori": kategori, "olgunluk": "announced",
            "yatirim_usd_milyon": yatirim}


# ============================================================
# 1) _ayirt_edici_sayilar — birim
# ============================================================
def iz(metin):
    return P._ayirt_edici_sayilar({"baslik_ozet": metin})


ek("binlik ayıraçlı tutar iz bırakıyor (23,731 crore)",
   iz("India approves 23,731 crore rupee programme") == {"23731"})
ek("noktalı yazım aynı ize indiriyor (23.731)",
   iz("Programme worth 23.731 crore") == {"23731"})
ek("YIL iz sayılmıyor (2026)", iz("Launch planned for 2026") == set())
ek("yıl sınırları dışlanıyor (1900, 2100)",
   iz("Between 1900 and 2100") == set())
ek("1899 iz sayılıyor (yıl aralığı dışı)", "1899" in iz("Figure 1899 tonnes"))
ek("kısa sayı iz sayılmıyor (5 milyon)", iz("5 million dollars") == set())
ek("yüzde iz sayılmıyor", iz("Up by %3 this quarter") == set())
ek("baştaki sıfırlar atılıyor", iz("Value 0023731 units") == {"23731"})
ek("kapasite izi tutuyor (700,000 ton)",
   iz("Plant to process 700,000 tonnes") == {"700000"})

# ============================================================
# 2) _ortak_sinyal — birim
# ============================================================
a = olay("a", "x", "c1", sirket=["Neste"], ulke=["Finland"], kategori="biyoyakit")
ek("ortak şirket sinyal veriyor",
   P._ortak_sinyal(a, olay("b", "y", "c2", sirket=["Neste"], ulke=["Brazil"],
                           kategori="tarim")))
ek("ortak ülke sinyal veriyor",
   P._ortak_sinyal(a, olay("b", "y", "c2", sirket=["Shell"], ulke=["Finland"],
                           kategori="tarim")))
ek("aynı kategori sinyal veriyor",
   P._ortak_sinyal(a, olay("b", "y", "c2", sirket=["Shell"], ulke=["Brazil"],
                           kategori="biyoyakit")))
ek("hiç örtüşme yoksa sinyal YOK",
   not P._ortak_sinyal(a, olay("b", "y", "c2", sirket=["Shell"], ulke=["Brazil"],
                               kategori="tarim")))
ek("kategori boşsa sinyal sayılmıyor",
   not P._ortak_sinyal(olay("a", "x", "c1", sirket=[], ulke=["Peru"], kategori=None),
                       olay("b", "y", "c2", sirket=[], ulke=["Chile"], kategori=None)))

# ============================================================
# LLM taklidi
# ============================================================
CAGRI = {"n": 0, "istem": "", "gruplar": []}


def sahte_llm(model, sistem, kullanici, max_tokens, **kw):
    CAGRI["n"] += 1
    CAGRI["istem"] = kullanici
    return json.dumps({"gruplar": CAGRI["gruplar"]})


def patlak_llm(*a, **kw):
    CAGRI["n"] += 1
    raise RuntimeError("model yok")


P.llm.llm_cagri = sahte_llm


def kos(olaylar, gruplar=None, llm=sahte_llm):
    CAGRI["n"], CAGRI["gruplar"] = 0, gruplar or []
    P.llm.llm_cagri = llm
    kalan, notlar = P.olaylari_birlestir([dict(o) for o in olaylar])
    return {o["event_key"]: o for o in kalan}, notlar


# ============================================================
# 3) KATMAN 1 — kesin eşleşme, LLM'siz
# ------------------------------------------------------------
# ⚠ DAVRANIŞ DEĞİŞTİ (biyoekonomi Sayı 3). Eskiden HERHANGİ bir aday
# id'sinin örtüşmesi "kesin aynı olay" sayılıyordu. biomassmagazine.com'un
# "Related Stories" bloğu yüzünden triyaj dört ayrı SAF haberine aynı
# destek id'lerini paylaştırdı ve bu katman üçünü tek habere çökertti;
# okuyucuya üç alakasız "destek kaynağı" gösterildi.
# Artık yalnızca AYNI BİRİNCİL kaynak kesindir — bir makale iki olayın
# birincili olamaz. Destek listelerinin kesişmesi küresel kümeleme
# adımına bırakılır (LLM hakemi + _ortak_sinyal emniyeti).
# ============================================================
kalan, notlar = kos([
    olay("ana", "Neste expands refinery", "c10", puan=8, sirket=["Neste"]),
    olay("kopya", "Neste refinery expansion reported", "c10", puan=6,
         sirket=["Neste"]),                        # AYNI birincil: c10
])
ek("aynı birincil kaynak → LLM'siz birleşti",
   "ana" in kalan and "kopya" not in kalan)
ek("kesin birleşme notu yazıldı",
   any("kesin birleşme" in n for n in notlar))

# Yalnızca DESTEK örtüşmesi kesin sayılmamalı — asıl hata buydu.
kalan, notlar = kos([
    olay("esaf", "American Airlines and Infinium eSAF flight", "c10",
         puan=8, sirket=["Infinium"]),
    olay("montana", "Montana Renewables MaxSAF expansion", "c99",
         puan=7, sirket=["Montana Renewables"], dest=["c10"]),
])
ek("yalnızca destek örtüşmesi KESİN birleştirmiyor",
   "esaf" in kalan and "montana" in kalan)
ek("kesin birleşme notu YAZILMADI",
   not any("kesin birleşme" in n for n in notlar))

# ============================================================
# 4) KATMAN 2 — sayı parmak izi (GERÇEK VAKA: GOBARdhan)
# ============================================================
# Ortak şirket YOK, başlık benzerliği düşük — eski çift bazlı ön eleme bu
# çifti hiç sormuyordu ve mükerrer bültene giriyordu.
kalan, notlar = kos([
    olay("gobardhan-kabine", "India cabinet approves 23,731 crore GOBARdhan scheme",
         "c20", puan=8, sirket=[], ulke=["India"], kategori="biyoyakit"),
    olay("hindistan-biyogaz", "Compressed biogas push worth 23.731 crore rupees cleared",
         "c21", puan=7, sirket=[], ulke=["India"], kategori="biyoyakit"),
])
ek("sayı parmak iziyle LLM'siz birleşti (GOBARdhan)",
   "gobardhan-kabine" in kalan and "hindistan-biyogaz" not in kalan)
ek("parmak izi notu ortak sayıyı yazıyor",
   any("sayı parmak izi (23731)" in n for n in notlar))
ek("parmak izi katmanı LLM çağırmadı (tek olay kaldı)", CAGRI["n"] == 0)

# aynı sayı AMA alakasız olay → birleşmemeli
kalan, _ = kos([
    olay("tesis-a", "Plant to process 700,000 tonnes of straw", "c30",
         puan=8, sirket=["Alfa"], ulke=["Spain"], kategori="atik-donusum"),
    olay("tesis-b", "Unrelated firm ships 700,000 tonnes of soy", "c31",
         puan=7, sirket=["Beta"], ulke=["Brazil"], kategori="tarim"),
])
ek("aynı sayı ama ortak sinyal yoksa birleşmiyor",
   "tesis-a" in kalan and "tesis-b" in kalan)

# ============================================================
# 5) KATMAN 3 — küresel kümeleme
# ============================================================
UC = [
    olay("saf-anlasma", "Montana Renewables to supply SAF to MSP airport", "c40",
         puan=8, sirket=["Montana Renewables"], kategori="biyoyakit"),
    olay("saf-harmanlama", "Blending hub starts serving MSP with aviation fuel", "c41",
         puan=6, sirket=["Flint Hills"], kategori="biyoyakit"),
    olay("alakasiz", "Aleph Farms wins Singapore approval", "c42",
         puan=7, sirket=["Aleph Farms"], ulke=["Singapore"], kategori="gida-protein"),
]
kalan, notlar = kos(UC, gruplar=[
    {"anahtarlar": ["saf-anlasma", "saf-harmanlama"], "gerekce": "ayni tedarik"}])
ek("LLM grubu birleştirildi",
   "saf-anlasma" in kalan and "saf-harmanlama" not in kalan)
ek("gruplanmayan olay korundu", "alakasiz" in kalan)
ek("en yüksek puanlı olay tutuldu", kalan["saf-anlasma"]["puan"] == 8)
ek("LLM'e TEK istek gitti", CAGRI["n"] == 1)
ek("istemde TÜM olaylar var (çift değil)",
   all(x in CAGRI["istem"] for x in ("saf-anlasma", "saf-harmanlama", "alakasiz")))
ek("isteme tam metin girmedi", "metin:" not in CAGRI["istem"])
ek("istem küçük kaldı (<4000 krkt)", len(CAGRI["istem"]) < 4000)

# ortak sinyal yoksa LLM kararı REDDEDİLİYOR
kalan, _ = kos([
    olay("bir", "Alpha announces plant", "c50", puan=8,
         sirket=["Alpha"], ulke=["Chile"], kategori="biyoyakit"),
    olay("iki", "Beta unrelated deal", "c51", puan=7,
         sirket=["Beta"], ulke=["Norway"], kategori="tarim"),
], gruplar=[{"anahtarlar": ["bir", "iki"], "gerekce": "hatali gruplama"}])
ek("ortak sinyal yoksa LLM kararı reddedildi",
   "bir" in kalan and "iki" in kalan)

# grup çok büyükse tema gruplaması sayılıp atlanıyor
BES = [olay(f"g{i}", f"Event number {i} about biofuel", f"c6{i}",
            puan=7, sirket=[f"Firma{i}"], kategori="biyoyakit") for i in range(5)]
kalan, _ = kos(BES, gruplar=[
    {"anahtarlar": [f"g{i}" for i in range(5)], "gerekce": "hepsi biyoyakit"}])
ek("5'li grup atlandı (tema gruplaması şüphesi)", len(kalan) == 5)

# bilinmeyen anahtar sessizce yok sayılıyor
kalan, _ = kos(UC, gruplar=[
    {"anahtarlar": ["saf-anlasma", "olmayan-anahtar"], "gerekce": "x"}])
ek("bilinmeyen anahtar güvenle yok sayıldı", len(kalan) == 3)

# ============================================================
# 6) DAYANIKLILIK
# ============================================================
kalan, _ = kos([
    olay("ana", "Neste expands refinery", "c70", puan=8, sirket=["Neste"]),
    olay("kopya", "Neste refinery expansion", "c70", puan=6,
         sirket=["Neste"]),                        # AYNI birincil
    olay("ucuncu", "Another unrelated item", "c72", puan=7,
         sirket=["Gamma"], kategori="tarim"),
], llm=patlak_llm)
ek("LLM hatasında akış sürüyor, kesin birleşme yine yapıldı",
   "kopya" not in kalan and "ana" in kalan and "ucuncu" in kalan)

kalan, _ = kos([olay("tek", "Only one event", "c80")])
ek("tek olayda LLM hiç çağrılmıyor", CAGRI["n"] == 0 and len(kalan) == 1)

kalan, _ = kos(UC, gruplar=[{"anahtarlar": ["saf-anlasma"], "gerekce": "tek"}])
ek("tek anahtarlı grup yok sayıldı", len(kalan) == 3)

# ============================================================
# 7) BİRLEŞME ANLAMBİLİMİ — bilgi kaybolmuyor
# ============================================================
kalan, _ = kos([
    olay("tut", "Alpha deal in Spain", "c90", puan=8,
         sirket=["Alpha"], ulke=["Spain"], kategori="biyoyakit", yatirim=None),
    olay("kat", "Alpha deal detail", "c91", puan=9, dest=["c92"],
         sirket=["Gamma"], ulke=["Portugal"], kategori="biyoyakit", yatirim=500),
], gruplar=[{"anahtarlar": ["tut", "kat"], "gerekce": "ayni anlasma"}])
tutulan = kalan.get("tut") or kalan.get("kat")
ek("birleşmede kaynaklar toplandı",
   {"c91", "c92"} <= set(tutulan["supporting_ids"]) | {tutulan["primary_id"]})
ek("birleşmede puan en yükseğe çekildi", tutulan["puan"] == 9)
ek("şirket listeleri birleşti", {"Alpha", "Gamma"} <= set(tutulan["sirketler"]))
ek("ülke listeleri birleşti", {"Spain", "Portugal"} <= set(tutulan["ulkeler"]))
ek("boş yatırım destekten dolduruldu", tutulan["yatirim_usd_milyon"] == 500)

# ============================================================
print("--- BİRLEŞTİRME BİRİM TESTİ ---")
for ad, ok in k:
    print(f"  {'✓' if ok else '✗'} {ad}")
gecen = sum(1 for _, o in k if o)
print(f"\n  {gecen}/{len(k)} geçti")
sys.exit(0 if gecen == len(k) else 1)
