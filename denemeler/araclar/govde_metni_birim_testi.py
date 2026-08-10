# -*- coding: utf-8 -*-
"""GÖVDE METNİ BİRİM TESTİ — _govde_metni() + metin zenginleştirme.

Exa bazı sayfalardan metnin yalnızca küçük bir parçasını döndürüyor; yazım
modeli de kaynakta olmayanı yazmadığı için haber kısa kalıyordu. Sayfa
tarih ve og:image için zaten indirildiğinden gövde metni aynı indirmeden
çıkarılıyor. Bu betik, çıkarımın menü/script/footer sızdırmadığını ve
zengin metnin ince metinle DEĞİŞTİRİLMEDİĞİNİ doğrular.

Kullanım (bu dizinden):  python govde_metni_birim_testi.py
"""
import os, sys

from yollar import KOK  # noqa: F401  (repo kokunu sys.path'e ekler)
os.environ.setdefault("DATABASE_URL", "")
import pipeline as P    # noqa: E402

U = "https://ornek.example/haber/1"
P_UZUN = ("Çin Devlet Konseyi, dört ayrı nükleer enerji projesi kapsamında sekiz yeni "
          "reaktörün inşasına onay verdi ve toplam yatırımın 170 milyar yuanı aşması "
          "bekleniyor.")
P_UZUN2 = ("Reuters'ın aktardığına göre projelerin toplam yatırım büyüklüğü yaklaşık "
           "25,2 milyar dolara karşılık geliyor ve inşaat önümüzdeki yıl başlayacak.")

GERCEKCI = f"""<!doctype html><html><head>
<meta property="og:image" content="https://cdn.example/haber-foto-buyuk.jpg">
<meta property="article:published_time" content="2026-07-30T09:00:00Z">
<script>var reklam = "<p>bu paragraf sayilmamali cunku script icinde ve uzun bir metin</p>";</script>
<style>.x{{content:"<p>stil icindeki uzun sahte paragraf metni buraya geldi</p>"}}</style>
</head><body>
<nav><p>Ana Sayfa</p><p>Enerji</p></nav>
<article>
  <p>{P_UZUN}</p>
  <p>Takip Et</p>
  <p>{P_UZUN2}</p>
  <p>Çin yönetimi 2025 yılında da toplam yatırım tutarı yaklaşık 200 milyar yuan olan
     on yeni reaktör projesini <b>onaylamıştı</b> &amp; kapasite artışı sürüyor.</p>
</article>
<footer><p>Telif hakkı 2026 — tüm hakları saklıdır, izinsiz kopyalanamaz burada</p></footer>
</body></html>"""

ARTICLESIZ = ("<html><body><div class='icerik'>"
              f"<p>{P_UZUN}</p><p>kısa</p><p>{P_UZUN2}</p>"
              "</div></body></html>")

k = []


def ek(ad, kosul):
    k.append((ad, bool(kosul)))


g = P._govde_metni(GERCEKCI)
ek("script içeriği alınmadı", "sayilmamali" not in g)
ek("style içeriği alınmadı", "sahte paragraf" not in g)
ek("nav menüsü alınmadı (kısa <p>)", "Ana Sayfa" not in g)
ek("kısa dolgu alınmadı ('Takip Et')", "Takip Et" not in g)
ek("article dışı footer alınmadı", "Telif hakkı" not in g)
ek("gerçek paragraflar alındı", P_UZUN[:40] in g and P_UZUN2[:40] in g)
ek("iç etiketler temizlendi", "<b>" not in g and "onaylamıştı" in g)
ek("HTML varlıkları çözüldü", "&amp;" not in g and "&" in g)
ek("paragraflar boş satırla ayrıldı", "\n\n" in g)

g2 = P._govde_metni(ARTICLESIZ)
ek("article etiketi yoksa da çalışıyor", P_UZUN[:40] in g2 and "kısa" not in g2)

ek("boş girdi güvenli", P._govde_metni("") == "" and P._govde_metni(None) == "")
ek("çıktı üst sınırı uygulanıyor",
   len(P._govde_metni("<p>" + "a" * 99999 + "</p>")) <= P.AYARLAR["exa_metin_karakter"])

# --- entegrasyon: tarih_dogrula ince metni değiştiriyor mu ---
P.sayfa_bilgisi = lambda url: ("2026-07-30", "https://cdn.example/foto.jpg", "X" * 2500)


def olay(metin):
    return {"baslik_ozet": "test", "kaynaklar": [{
        "url": U, "domain": "ornek.example", "name": "ornek.example",
        "published_date": "2026-07-30", "text": metin, "tier": 2,
        "paywall": False, "primary": True}]}


o1 = olay("kısa snippet " * 20)          # ~260 krkt → değişmeli
P.tarih_dogrula([o1], 7)
ek("ince Exa metni sayfa metniyle değişti", len(o1["kaynaklar"][0]["text"]) == 2500)

o2 = olay("Z" * 3000)                     # zaten zengin → korunmalı
P.tarih_dogrula([o2], 7)
ek("zengin Exa metni KORUNDU", o2["kaynaklar"][0]["text"] == "Z" * 3000)

P.sayfa_bilgisi = lambda url: ("2026-07-30", None, "kısa çıkarım")
o3 = olay("Y" * 900)
P.tarih_dogrula([o3], 7)
ek("bozuk/kısa çıkarım metni bozmadı", o3["kaynaklar"][0]["text"] == "Y" * 900)

P.sayfa_bilgisi = lambda url: (None, None, "")
o4 = olay("Y" * 900)
P.tarih_dogrula([o4], 7)
ek("ağ hatasında akış sürüyor", o4["kaynaklar"][0]["text"] == "Y" * 900)

print("--- GÖVDE METNİ BİRİM TESTİ ---")
for ad, ok in k:
    print(f"  {'✓' if ok else '✗'} {ad}")
print(f"\n  örnek çıkarım ({len(g)} krkt):")
for satir in g.split("\n\n"):
    print(f"    · {satir[:78]}")
_gecen = sum(1 for _, o in k if o)
print(f"\n  {_gecen}/{len(k)} geçti")
sys.exit(0 if all(o for _, o in k) else 1)
