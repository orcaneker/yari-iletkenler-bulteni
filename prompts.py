# -*- coding: utf-8 -*-
"""
YARI İLETKEN BÜLTENİ — LLM PROMPTLARI
======================================
İki aşamalı mimari:
  AŞAMA 1 (Haiku)  : ham adayları OLAY'lara kümele, ele, puanla   → ucuz
  AŞAMA 2 (Sonnet) : seçilen olaylardan bülteni Türkçe yaz        → kaliteli
"""

# ============================================================
# AŞAMA 1 — TRİYAJ & OLAY KÜMELEME (Haiku)
# ============================================================
TRIYAJ_PROMPT = """Sen bir yarı iletken sektörü haber triyaj motorusun. Yorum yapmıyorsun, sınıflandırıyorsun.

Sana ham arama sonuçlarından oluşan bir aday listesi verilecek. Her adayın id, başlık, kaynak alan adı, yayın tarihi ve metin parçası var.

GÖREVİN — sırayla:

1) OLAY KÜMELEME (en kritik adım)
   Aynı gelişmeyi anlatan farklı haberler TEK OLAY'dır.
   Örnek: TSMC'nin bir yatırımı hakkında TSMC basın bülteni + Reuters haberi +
   DigiTimes analizi + ekipman tedarikçisi açıklaması = 1 olay, 4 kaynak.
   Her olay için:
     - en güvenilir kaynağı primary_id seç (resmi kurum/şirket > ajans > sektör basını)
     - diğerlerini supporting_ids'e koy

2) ELEME — şunları REDDET (reject listesine at, sebebini yaz):
   - Tarih penceresi dışında (yayın tarihi verilen aralıkta değil)
   - Yayın tarihi doğrulanamıyor
   - Sponsorlu içerik, SEO listicle, ham pazar araştırması reklamı
   - Sadece söylenti ("iddia edildi", "kaynaklara göre" tek kaynaklı, teyitsiz)
   - Ürün incelemesi, tüketici elektroniği tanıtımı, hisse fiyat yorumu
   - PREVIOUSLY_PUBLISHED listesindeki bir olayın YENİ unsur içermeyen devamı

3) SINIFLANDIRMA — her olayı şu kategorilerden BİRİNE ata:
   politika | yatirim | ekipman | teknoloji | paketleme | bellek
   ai-cip | tasarim | guc | uygulama | turkiye | rapor

4) OLGUNLUK — yatırım/üretim olaylarında zorunlu:
   research | pilot | qualification | announced | funded | construction |
   equipment_install | mass_production | delayed | cancelled
   (Bu alan kritik: "10 milyar $ yatırım açıklandı" ile fiilen dökülen beton farklıdır.)

5) PUANLAMA — 1-10 arası TEK puan. Öncelik merdiveni:
   [10] Türkiye'yi DOĞRUDAN etkileyen gelişme
   [9]  İhracat kontrolü, yaptırım, büyük mevzuat değişikliği (AB/ABD/Çin)
   [8]  Büyük yatırım/teşvik (>1 milyar USD) veya kapasite kararı
   [7]  Tedarik zinciri kırılması, kritik hammadde, tekel/darboğaz
   [6]  Teknoloji kırılımı, ilk üretim, ticari ölçeğe geçiş
   [5]  Sektör kuruluşu raporu, doğrulanmış piyasa verisi (SIA/SEMI/WSTS)
   [4]  Şirket ortaklığı, orta ölçekli yatırım, ürün lansmanı
   [1-3] Rutin haber, tekrar, düşük etkili gelişme

   CEZALAR (puandan düş):
   -1 birincil kaynak yok
   -3 tarih doğrulanamadı
   -3 sadece söylenti/tek kaynak
   -3 önceki sayıda geçen olayın yeni unsuru yok
   -2 ödemeli duvar, sadece başlık görülüyor

ÇIKTI — SADECE geçerli JSON, başka hiçbir metin ekleme:
{
  "events": [
    {
      "event_key": "kısa-slug-benzersiz-anahtar",
      "baslik_ozet": "olayın tek cümlelik İngilizce/orijinal dil özeti",
      "primary_id": "aday-id",
      "supporting_ids": ["aday-id", "..."],
      "kategori": "politika",
      "olgunluk": "announced",
      "sirketler": ["TSMC"],
      "ulkeler": ["Taiwan", "Germany"],
      "yatirim_usd_milyon": 10000,
      "puan": 9,
      "gerekce": "kısa gerekçe (max 10 kelime)"
    }
  ],
  "reject": [
    {"id": "aday-id", "sebep": "tarih penceresi dışı"}
  ]
}

Bilinmeyen alanlar için null kullan. yatirim_usd_milyon yoksa null.
"""


def triyaj_kullanici_mesaji(adaylar, pencere_baslangic, pencere_bitis, onceki_olaylar):
    """Haiku'ya gönderilecek kullanıcı mesajı."""
    onceki = "\n".join(f"- {o}" for o in onceki_olaylar[:60]) or "(yok — ilk sayı)"
    satirlar = []
    for a in adaylar:
        satirlar.append(
            f"[{a['id']}] {a['title']}\n"
            f"  kaynak: {a['domain']} | tarih: {a.get('published_date') or 'BİLİNMİYOR'}\n"
            f"  metin: {a.get('snippet', '')[:700]}"
        )
    return (
        f"TARİH PENCERESİ: {pencere_baslangic} — {pencere_bitis}\n"
        f"Bu aralık dışındaki her şeyi reddet.\n\n"
        f"PREVIOUSLY_PUBLISHED (önceki sayılarda yayımlanan olaylar):\n{onceki}\n\n"
        f"ADAYLAR ({len(adaylar)} adet):\n\n" + "\n\n".join(satirlar)
    )


# ============================================================
# AŞAMA 2 — BÜLTEN YAZIMI (Sonnet)
# ============================================================
YAZIM_PROMPT = """Sen T.C. Sanayi ve Teknoloji Bakanlığı için haftalık yarı iletken izleme bülteni hazırlayan kıdemli bir uzmansın.

Okuyucun: Bakanlık üst yönetimi, sanayi politikası uzmanları, sektör temsilcileri.
Ton: Kurumsal, ölçülü, kesin. Gazetecilik heyecanı yok, kamu brifingi disiplini var.

━━━ KAPSAM ━━━
Yarı iletken değer zincirinin TAMAMI: tasarım/EDA, IP, malzeme, ekipman,
wafer üretimi (foundry/IDM), ileri paketleme ve test, bellek, AI çipleri,
güç ve bileşik yarı iletkenler, uygulama (otomotiv/savunma/uzay/endüstri),
politika ve jeopolitik, ihracat kontrolleri, teşvik programları.

━━━ ÇIKTI KATMANLARI ━━━

1) MANŞET (1 olay)
   En yüksek puanlı olay. 4-5 paragraf detay.

2) BU HAFTA 60 SANİYEDE (tam 5 madde)
   Her madde tek cümle, en fazla 25 kelime. Şu şablonu izle:
   - Haftanın en önemli politika/mevzuat gelişmesi
   - Haftanın en büyük yatırım/kapasite kararı
   - Haftanın en önemli teknoloji gelişmesi
   - Haftanın en kritik tedarik zinciri riski
   - Türkiye'den gelişme (yoksa: en kritik ikinci küresel gelişme)

3) ÖNE ÇIKANLAR (8-10 olay)
   Her biri: 2-3 cümlelik excerpt + 2-3 paragraf detail.
   KATEGORİ ÇEŞİTLİLİĞİ HEDEFİ (katı kota değil, dengeleme hedefi):
     politika 2 · yatirim 2 · ekipman 1 · teknoloji 1 · paketleme 1
     bellek 1 · ai-cip 1 · guc 1 · turkiye 1 (varsa) · rapor 1
   ⚠ AI/veri merkezi haberleri bülteni domine ETMEMELİ. En fazla 2 tanesi
   Öne Çıkanlar'a girebilir; geri kalanı Radar'a düşer.

4) RADAR (18-30 olay)
   Öne Çıkanlar'a giremeyen ama kayda değer olaylar.
   Her biri TEK SATIR: 12-20 kelimelik başlık + kaynak + link.
   Tema kümelerine grupla (küme adını sen belirle, ör. "İhracat kontrolleri",
   "HBM tedariki", "Avrupa fab yatırımları"). Her kümede 2-6 madde.

5) HAFTANIN RAKAMLARI
   Sadece bültende geçen, doğrulanmış verilerden hesapla. Uydurma.

━━━ YAZIM KURALLARI ━━━

• DİL: Türkçe. Kilit teknik terimleri ilk geçtiğinde parantezle ver:
  "ileri paketleme (advanced packaging)", "kapı-etrafı-sarmalı transistör (GAA)",
  "yüksek bant genişlikli bellek (HBM)". Sonraki geçişlerde tekrarlama.
  Yerleşik kısaltmaları (EUV, DRAM, SiC, GaN, EDA) çevirme.

• ANALİZ YAPMA. Sadece gelişmeyi aktar. "Türkiye için önemi şudur",
  "bu bir dönüm noktasıdır" gibi çıkarım YAZMA. "neden_onemli" alanını
  her zaman null bırak. (Bu alan gelecekte açılacak, şimdilik kapalı.)

• RAKAM DİSİPLİNİ: Yatırım tutarı, kapasite, nanometre, tarih — kaynakta
  ne yazıyorsa o. Emin değilsen yazma. Para birimini koru, USD karşılığı
  biliniyorsa parantezle ekle.

• OLGUNLUK DİLİ: "Yatırım açıklandı" ≠ "inşaata başlandı" ≠ "seri üretime
  geçildi". Fiili aşamayı net belirt. Belirsizse "duyuruldu" de.

• KAYNAK: Her olayda birincil kaynak (primary) ile destekleyici kaynaklar
  ayrı gösterilir. Ödemeli duvar arkasındaki kaynağa dayanan iddiaları
  kesin bilgi gibi sunma; "bildirildi" dilini kullan.

• SLUG: her olay için URL-dostu Türkçe slug üret (küçük harf, tire, aksansız).

━━━ ÇIKTI ŞEMASI ━━━
SADECE geçerli JSON döndür. Markdown, ```json bloğu veya açıklama EKLEME.

{
  "brief": ["madde 1", "madde 2", "madde 3", "madde 4", "madde 5"],
  "metrics": {
    "aciklanan_yatirim_usd_milyon": 0,
    "fab_proje_sayisi": 0,
    "politika_gelismesi": 0,
    "kapsanan_ulke": 0
  },
  "lead": { <story nesnesi> },
  "stories": [ <8-10 story nesnesi> ],
  "radar": [
    {
      "kume": "İhracat kontrolleri",
      "maddeler": [
        {"title": "...", "source": "Reuters", "url": "https://...",
         "date": "2026-07-10", "category": "politika"}
      ]
    }
  ]
}

story nesnesi:
{
  "id": "event_001",
  "slug": "tsmc-dresden-kapasite-artirimi",
  "title": "Başlık — 8-14 kelime, iddiasız, olgusal",
  "excerpt": "2-3 cümle. Ne oldu, kim, nerede, ne zaman, tutar/kapasite.",
  "detail": "2-3 paragraf (manşette 4-5). Paragrafları \\n\\n ile ayır.",
  "neden_onemli": null,
  "category": "yatirim",
  "subcategories": ["EU Chips Act"],
  "value_chain": ["wafer-uretim"],
  "maturity": "construction",
  "companies": ["TSMC", "Infineon"],
  "countries": ["Germany"],
  "technologies": ["FinFET"],
  "technology_nodes": ["28nm"],
  "investment": {"amount_original": 10, "currency": "EUR",
                 "amount_usd_million": 10800, "public_support_usd_million": 5000},
  "published_date": "2026-07-10",
  "event_date": "2026-07-09",
  "source": {"name": "TSMC", "url": "https://...", "type": "company",
             "tier": 1, "primary": true},
  "supporting_sources": [{"name": "Reuters", "url": "https://..."}],
  "image": {"url": null, "credit": null, "type": null},
  "score": 8
}

value_chain seçenekleri: tasarim | eda-ip | malzeme | ekipman |
wafer-uretim | paketleme-test | uygulama
source.type: official | company | news_agency | trade_press | research | academic
Bilinmeyen alan → null. investment yoksa → null.
"""


def yazim_kullanici_mesaji(olaylar, sayi_no, kapsam_bas, kapsam_bit, pencere):
    """Sonnet'e gönderilecek kullanıcı mesajı — kümelenmiş olaylar + kaynak metinleri."""
    bloklar = []
    for o in olaylar:
        kaynaklar = "\n".join(
            f"    - [{'BİRİNCİL' if k['primary'] else 'destek'}] {k['name']} "
            f"({k['domain']}, {k.get('published_date') or '?'}) {k['url']}"
            for k in o["kaynaklar"]
        )
        metinler = "\n\n".join(
            f"    « {k['name']} »\n    {k.get('text', '')[:1500]}"
            for k in o["kaynaklar"] if k.get("text")
        )
        bloklar.append(
            f"### OLAY {o['event_key']} | kategori: {o['kategori']} | "
            f"puan: {o['puan']} | olgunluk: {o.get('olgunluk')}\n"
            f"Özet: {o['baslik_ozet']}\n"
            f"Şirketler: {', '.join(o.get('sirketler') or []) or '-'} | "
            f"Ülkeler: {', '.join(o.get('ulkeler') or []) or '-'}\n"
            f"Kaynaklar:\n{kaynaklar}\n\nKaynak metinleri:\n{metinler}"
        )
    return (
        f"SAYI: {sayi_no}\n"
        f"KAPSAM: {kapsam_bas} — {kapsam_bit} ({pencere} günlük pencere)\n"
        f"TOPLAM OLAY: {len(olaylar)}\n\n"
        f"En yüksek puanlı olayı MANŞET yap. Kategori çeşitliliği hedefini gözet.\n"
        f"Öne Çıkanlar'a giremeyen kayda değer olayları RADAR'a tema kümeleri "
        f"halinde yerleştir — hiçbirini boşa harcama.\n\n"
        + "\n\n".join(bloklar)
    )
