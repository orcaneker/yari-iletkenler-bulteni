# ============================================================
# YARI İLETKEN BÜLTENİ — SİSTEM PROMPT DOSYASI (v2.0)
# ============================================================
# Bu dosya sistemin BEYNİ ve REFERANS BELGESİDİR.
# Kodda karşılıkları:
#   BÖLÜM 1 (sorgular)       → config.py  → SORGULAR
#   BÖLÜM 2 (taksonomi)      → config.py  → KATEGORILER / OLGUNLUK
#   BÖLÜM 3 (LLM promptları) → prompts.py → TRIYAJ_PROMPT / YAZIM_PROMPT
#   BÖLÜM 4 (kaynaklar)      → config.py  → KAYNAK_TIER1/TIER2/...
#   BÖLÜM 5 (onay akışı)     → db.py / review_app / publish.py
#   BÖLÜM 6-8 (şema, ayar)   → config.py  → AYARLAR
#
# Buradaki bir şeyi değiştirdiğinde İLGİLİ KOD DOSYASINI DA GÜNCELLE.
#
# Biyoekonomi bülteninden (orcaneker/biyoekonomi-bulteni) uyarlanmıştır.
# Eski tek-script + Cloudflare Pages sisteminden (v1) farkları:
#   1. MİMARİ: main.py tek dosya yerine pipeline.py / publish.py ayrımı
#   2. ONAY KATMANI: taslak → hakem incelemesi → onay → yayın (v1'de yoktu)
#   3. Neon Postgres (taslak/onay durumu) + Resend (e-posta)
#   4. Cron Render'da; yayın Cloudflare Pages yerine GitHub Pages (/docs)
#   5. Radar + "Bu Hafta 60 Saniyede" + ElevenLabs sesli özet + hakem takas havuzu
#   6. Yazım modeli Sonnet 4.6 → Sonnet 5 (adaptif düşünme, geniş çıktı bütçesi)
# Alan bilgisi (kategoriler, kaynaklar, sorgular, promptlar) v1'den taşındı.
# ============================================================


# ============================================================
# BÖLÜM 0 — MİMARİ
# ============================================================
#
# CRON 1 — Pazar 12:00 TSİ (Render Cron, UTC "0 9 * * 0")
#   pipeline.py
#   ↓ EXA SEARCH — 12 sorgu × ek sorgu varyasyonları
#   ↓ NORMALİZASYON — UTM/AMP temizliği, başlık hash, görülmüş URL elemesi
#   ↓ DETERMİNİSTİK TARİH FİLTRESİ — pencere dışı/tarihsiz aday LLM'e gitmeden elenir
#   ↓ AŞAMA 1 — triyaj modeli (Haiku): olay kümeleme, eleme, puanlama
#   ↓ AŞAMA 2 — yazım modeli (Sonnet): 14 derin olayın TAMAMI tam haber
#     (8-10 "one_cikan" + kalanı "yedek") + radar + brief
#   ↓ TASLAK → Neon'a kaydet (status=review)
#   ↓ Resend → hakemlere davet e-postası (magic link)
#
# İNCELEME — Render Web Service (FastAPI, sürekli)
#   Hakem linke tıklar → taslağı görür
#   · Haberi çıkar → yedek havuzundan birini yerine koy (takas)
#   · Yedeği doğrudan bültene al / manşeti değiştir / radar maddesi çıkar
#   · "Onayla ve Yayınla" → status=approved  (TEK ONAY YETERLİ)
#   · Onay Pazartesi 08:00 TSİ'den SONRA gelirse yayın ANINDA tetiklenir
#
# CRON 2 — Pazartesi 08:00 TSİ (Render Cron, UTC "0 5 * * 1")
#   publish.py
#   · status=approved → nihai JSON kur (takaslar uygulanmış) → arşiv +
#     state + RSS + ElevenLabs sesli özet → docs/ → GitHub push → Pages
#   · status=review   → Resend hatırlatma e-postası; YAYIN YAPILMAZ
#     (otomatik yayın YOK — onay gelene dek bekler)
#   · Çalışma raporu e-postası (Resend → RAPOR_ALICI)


# ============================================================
# BÖLÜM 1 — EXA ARAMA SORGULARI (12)
# ============================================================
# config.py → SORGULAR. Kısa semantik sorgu + ayrı parametreler
# (tarih, domain, konum). Uzun doğal dil komutu YAZILMAZ.
#
#   politika    ihracat kontrolleri, CHIPS Act, Chips Act 2.0, jeopolitik
#   yatirim     yeni fab yatırımı, kapasite genişlemesi, teşvik onayı
#   ekipman     litografi (ASML/EUV), fotorezist, gaz, metroloji ekipmanı
#   teknoloji   2nm/1.4nm, GAA, CFET, backside power, silikon fotonik
#   paketleme   CoWoS, hybrid bonding, chiplet, cam altlık, HBM paketleme
#   bellek      DRAM/NAND/HBM piyasa gelişmeleri, HBM4 tedarik anlaşmaları
#   ai-cip      AI hızlandırıcı, özel ASIC, veri merkezi silikonu
#   tasarim     EDA araçları, RISC-V/Arm lisanslama, çip IP
#   guc         SiC/GaN güç yarı iletkeni, RF bileşik yarı iletken
#   uygulama    otomotiv MCU/ADAS, savunma elektroniği, radyasyona dayanıklı çip
#   turkiye     Türkiye odaklı gelişmeler (Türkçe + userLocation=tr, 21 gün pencere)
#   rapor       SIA/SEMI/WSTS piyasa verisi, TrendForce/Yole tahminleri
#
# Tarih penceresi: birincil 7 gün; <40 aday kalırsa 14 güne genişler.
# Türkiye sorgusu userLocation="tr" ile yerel sonuç ağırlığı alır ve
# haber akışı seyrek olduğu için 21 günlük pencere kullanır.


# ============================================================
# BÖLÜM 2 — KATEGORİ TAKSONOMİSİ (12) ve KOTALAR
# ============================================================
# config.py → KATEGORILER. "kota" = Öne Çıkanlar'da hedef sayı (katı değil).
# Kota olmadan AI çipi/veri merkezi haberleri akışı domine eder.
#
#   politika (2) · yatirim (2) · ekipman (1) · teknoloji (1) ·
#   paketleme (1) · bellek (1) · ai-cip (1) · tasarim (0) ·
#   guc (1) · uygulama (0) · turkiye (1) · rapor (1)
#
# OLGUNLUK (config.py → OLGUNLUK) — yatırım/üretim olaylarında ZORUNLU:
#   research → pilot → qualification → announced → funded →
#   construction → equipment_install → mass_production (+ delayed/cancelled)
# "10 milyar $ yatırım açıklandı" ile fiilen dökülen beton arasında yıllar
# var — en büyük sinyal-gürültü sorunu budur, aşama net belirtilir.
#
# DEĞER ZİNCİRİ (config.py → DEGER_ZINCIRI):
#   tasarim → eda-ip → malzeme → ekipman → wafer-uretim →
#   paketleme-test → uygulama


# ============================================================
# BÖLÜM 3 — LLM PROMPTLARI
# ============================================================
# prompts.py → TRIYAJ_PROMPT (Haiku) + YAZIM_PROMPT (Sonnet).
#
# TRİYAJ: sınıflandırır, YORUM YAPMAZ. Olay kümeler (aynı gelişmenin farklı
#   haberleri = 1 olay), eler (tarih dışı, söylenti, SEO, ürün incelemesi), 1-10 puanlar.
# YAZIM: Türkçeleştirir, SOMUT VERİYİ (tutar, kapasite/wafer-ay, teknoloji
#   düğümü, takvim, yer, program) eksiksiz çıkarır. ANALİZ/YORUM YASAK.
#   Kaynağın durumunu ASLA anlatmaz. Derin olayların TAMAMINI yazar
#   (hakem takası için) — İKİ MUTLAK KURAL: kaynakta olmayanı ekleme,
#   sayısal verileri eksiksiz/birebir koru.


# ============================================================
# BÖLÜM 4 — KAYNAK KATMANLARI
# ============================================================
# config.py → KAYNAK_TIER1 (birincil: resmî kurum/şirket newsroom —
#   TSMC, Samsung, Intel, ASML, Applied Materials, SEMI, imec...),
#   KAYNAK_TIER2 (sektör basını/ajans — EE Times, DigiTimes, TrendForce,
#   TechInsights, SemiAnalysis...), KAYNAK_AKADEMIK, KAYNAK_TURKIYE
#   (sanayi.gov.tr, TÜBİTAK/BİLGEM, ASELSAN, chip.com.tr...).
# ÖDEME DUVARI: KAYNAK_ODEME_DUVARI'ndaki kaynaklar (DigiTimes, FT, WSJ,
#   Nikkei, SemiAnalysis, TechInsights, Yole, TrendForce, Gartner, IDC...)
#   asla birincil olmaz; tek kaynak duvarlıysa olay Radar'a düşer, teyit
#   araması erişilebilir kaynak bulmaya çalışır. DIŞLANANLAR: sosyal medya,
#   PR wire, SEO pazar araştırma siteleri (config.py → KAYNAK_DISLA).
# ⚠ reuters.com / bloomberg.com Exa includeDomains'e EKLENMEZ (403).


# ============================================================
# BÖLÜM 5 — ONAY AKIŞI
# ============================================================
# db.py (Neon) issue durumları: review → approved → published.
# TEK hakem onayı yeterli. Onay Pazartesi 08:00'den önceyse cron 2 yayınlar;
# sonraysa inceleme servisi publish.yayinla()'yı anında çağırır.
# Hakem ekleme: python db.py --seed "Ad Soyad" mail@ornek.com


# ============================================================
# BÖLÜM 6 — GENEL AYARLAR (config.py → AYARLAR)
# ============================================================
#   haber (Öne Çıkanlar) : 8-10  ·  derin olay: 14  ·  radar: 18-30
#   pencere: 7 gün (yetersizse 14) ·  brief: 5 madde
#   yayım: Pazartesi 08:00 TSİ  ·  taslak: Pazar 12:00 TSİ
#   model_triyaj: anthropic:claude-haiku-4-5-20251001
#   model_yazim:  anthropic:claude-sonnet-5
#   site_url: https://orcaneker.github.io/yari-iletkenler-bulteni
#
# ⚠ İlk yayın öncesi: AYARLAR["sayi_no_sabit"] = None yapın
#   (test için 1'de sabitli; None → sayı otomatik artar).


# ============================================================
# BÖLÜM 7 — SİTE TASARIMI
# ============================================================
# site/index.html + arsiv.html — biyoekonomi bülteninin YAPISI birebir
# aynı (koyu video+partikül hero → açık editoryal gövde → kart şeritleri
# → modal), yalnızca RENK PALETİ değişti: biyoekonomi'nin yeşil/toprak
# "biyofilm" teması yerine bakır/kehribar "fab temiz odası" teması.
# Bilinçli olarak MAVİ/YEŞİL yok — fotorezist maviye duyarlı olduğu için
# temiz odalar sarı/kehribar ışıkla aydınlatılır (v1'den kalıtılan kural).
# Hero görseli: robotik kol + wafer, assets/hero-loop-pingpong.mp4
#   (sessiz, ileri+ters birleştirilmiş döngü) + hero*.avif/webp stiller.
