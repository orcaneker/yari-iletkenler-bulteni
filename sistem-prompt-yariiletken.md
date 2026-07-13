# ============================================================
# YARI İLETKEN BÜLTENİ — SİSTEM PROMPT DOSYASI (v1.0)
# ============================================================
# Bu dosya sistemin BEYNİ ve REFERANS BELGESİDİR.
# Kodda karşılıkları:
#   BÖLÜM 1 (sorgular)      → config.py  → SORGULAR
#   BÖLÜM 2 (taksonomi)     → config.py  → KATEGORILER
#   BÖLÜM 3 (LLM promptları)→ prompts.py → TRIYAJ_PROMPT / YAZIM_PROMPT
#   BÖLÜM 4 (kaynaklar)     → config.py  → KAYNAK_TIER1/TIER2/...
#   BÖLÜM 5-7 (şema, ayar)  → config.py  → AYARLAR
#
# Buradaki bir şeyi değiştirdiğinde İLGİLİ KOD DOSYASINI DA GÜNCELLE.
# Biyoekonomi bülteninden farkı: iki aşamalı LLM, olay (event) modeli,
# katmanlı bülten (manşet + brief + öne çıkanlar + radar), kalıcı arşiv.
# ============================================================


# ============================================================
# BÖLÜM 0 — MİMARİ
# ============================================================
# Render cron (Pazartesi 08:00 TSİ)
#   ↓
# EXA SEARCH — 12 sorgu × ek sorgu varyasyonları
#   · startPublishedDate / endPublishedDate  (tarih filtresi)
#   · includeDomains  (kaynak katmanı önceliği)
#   · excludeDomains  (SEO/PR çöplüğü)
#   · contents.text + highlights  (Claude'a giden metin)
#   ↓
# NORMALİZASYON — UTM/AMP temizliği, başlık hash, görülmüş URL elemesi
#   ↓
# AŞAMA 1 — CLAUDE HAIKU (ucuz)
#   · Olay kümeleme (aynı gelişme = 1 olay, N kaynak)
#   · Eleme (tarih dışı, söylenti, sponsorlu, tekrar)
#   · Kategori + olgunluk + puan
#   ↓
# AŞAMA 2 — CLAUDE SONNET (kaliteli)
#   · Türkçe yazım, katmanlı bülten, JSON çıktı
#   ↓
# DOĞRULAMA → dist/ → GitHub push → Cloudflare Pages
#   ↓
# E-posta çalışma raporu (sadece Orcan'a)


# ============================================================
# BÖLÜM 1 — EXA ARAMA SORGULARI (12)
# ============================================================
# ÖNEMLİ: Exa'da Perplexity'deki gibi uzun doğal dil komutu YAZILMAZ.
# Kısa semantik sorgu + AYRI parametreler kullanılır. Tarih, domain ve
# kategori filtresi prompt metnine gömülmez — kod tarafından yönetilir.
# Bu yüzden "exclude SEO listicles" gibi cümleler artık gereksizdir.

EXA_SORGULARI:

  - id: politika
    kategori: politika
    sorgu: "semiconductor policy, export controls and chip geopolitics"
    ek_sorgular:
      - "EU Chips Act 2.0 semiconductor strategy"
      - "US CHIPS Act funding and semiconductor export restrictions"
      - "China semiconductor policy and retaliation measures"
      - "critical raw materials gallium germanium rare earth chip supply"
    domain_seti: [tier1, tier2]
    sonuc: 25

  - id: yatirim
    kategori: yatirim
    sorgu: "new semiconductor fab investment and capacity expansion"
    ek_sorgular:
      - "foundry capex announcement wafer capacity"
      - "chip plant delayed cancelled construction start"
      - "government subsidy approved semiconductor factory"
    domain_seti: [tier1, tier2]
    sonuc: 25

  - id: ekipman
    kategori: ekipman
    sorgu: "semiconductor equipment and materials supply chain"
    ek_sorgular:
      - "ASML lithography tool shipment High-NA EUV"
      - "wafer photoresist specialty gas supply semiconductor materials"
      - "deposition etch metrology equipment order"
    domain_seti: [tier1, tier2]
    sonuc: 20

  - id: teknoloji
    kategori: teknoloji
    sorgu: "advanced semiconductor process node technology breakthrough"
    ek_sorgular:
      - "2nm 1.4nm gate-all-around production yield"
      - "backside power delivery CFET new transistor architecture"
      - "silicon photonics quantum neuromorphic chip"
    domain_seti: [tier1, tier2, akademik]
    sonuc: 20

  - id: paketleme
    kategori: paketleme
    sorgu: "advanced packaging chiplet and heterogeneous integration"
    ek_sorgular:
      - "CoWoS hybrid bonding capacity expansion"
      - "glass substrate panel level packaging OSAT investment"
      - "HBM packaging bottleneck test and metrology"
    domain_seti: [tier1, tier2]
    sonuc: 20

  - id: bellek
    kategori: bellek
    sorgu: "DRAM NAND and HBM memory market developments"
    ek_sorgular:
      - "HBM4 supply agreement memory pricing"
      - "Samsung SK hynix Micron memory capacity"
    domain_seti: [tier1, tier2]
    sonuc: 15

  - id: ai-cip
    kategori: ai-cip
    sorgu: "AI accelerator chips and data center silicon"
    ek_sorgular:
      - "Nvidia AMD custom ASIC hyperscaler chip announcement"
      - "AI datacenter power and optical interconnect silicon"
    domain_seti: [tier1, tier2]
    sonuc: 20

  - id: tasarim
    kategori: tasarim
    sorgu: "chip design EDA and semiconductor IP developments"
    ek_sorgular:
      - "RISC-V Arm architecture licensing"
      - "Synopsys Cadence EDA AI design tool"
    domain_seti: [tier1, tier2]
    sonuc: 15

  - id: guc
    kategori: guc
    sorgu: "silicon carbide gallium nitride power semiconductor"
    ek_sorgular:
      - "SiC GaN fab investment automotive power module"
      - "RF compound semiconductor defense telecom"
    domain_seti: [tier1, tier2]
    sonuc: 15
    # NOT: Türkiye'nin en gerçekçi sanayi politikası alanı burasıdır.
    # İleri mantık düğümlerine göre çok daha erişilebilir.

  - id: uygulama
    kategori: uygulama
    sorgu: "automotive defense and industrial semiconductor applications"
    ek_sorgular:
      - "automotive MCU ADAS radar sensor chip supply"
      - "defense electronics radiation hardened space chip"
    domain_seti: [tier1, tier2]
    sonuc: 15

  - id: turkiye
    kategori: turkiye
    sorgu: "Türkiye yarı iletken çip mikroelektronik yatırım ve teşvik"
    ek_sorgular:
      - "Turkey semiconductor investment chip design startup"
      - "TÜBİTAK BİLGEM YİTAL mikroelektronik entegre devre"
      - "Türkiye çip tasarım MEMS sensör güç elektroniği yatırımı"
      - "HIT-30 yüksek teknoloji yatırım programı yarı iletken"
    domain_seti: [turkiye, tier1, tier2]
    sonuc: 25
    pencere_gun: 21          # TR haber akışı seyrek → geniş pencere
    kullanici_konumu: "tr"   # Exa userLocation
    # ⚠ RİSK: Exa'nın Türkçe/İngilizce-dışı indeksi zayıftır.
    # Perplexity kredisi geldiğinde bu sorguya YEDEK katman eklenecek.

  - id: rapor
    kategori: rapor
    sorgu: "semiconductor industry market data and outlook report"
    ek_sorgular:
      - "SIA SEMI WSTS billings forecast semiconductor sales"
      - "TrendForce Yole semiconductor market forecast"
    domain_seti: [tier1, tier2]
    sonuc: 15


# ============================================================
# BÖLÜM 2 — KATEGORİ TAKSONOMİSİ (12)
# ============================================================
# Her olay bu kodlardan BİRİNE atanır. Site filtresi de bunları kullanır.
# "kota" = Öne Çıkanlar bölümündeki çeşitlilik hedefi (katı sınır değil).

KATEGORILER:
  politika   : { ad: "Politika & Jeopolitik",         kota: 2 }
  yatirim    : { ad: "Yatırım & Üretim",              kota: 2 }
  ekipman    : { ad: "Ekipman & Malzeme",             kota: 1 }
  teknoloji  : { ad: "Süreç Teknolojisi",             kota: 1 }
  paketleme  : { ad: "İleri Paketleme & Test",        kota: 1 }
  bellek     : { ad: "Bellek & Depolama",             kota: 1 }
  ai-cip     : { ad: "AI Çipleri & Veri Merkezi",     kota: 1 }
  tasarim    : { ad: "Tasarım, EDA & IP",             kota: 0 }
  guc        : { ad: "Güç & Bileşik Yarı İletkenler", kota: 1 }
  uygulama   : { ad: "Otomotiv, Savunma & Endüstri",  kota: 0 }
  turkiye    : { ad: "Türkiye",                       kota: 1 }
  rapor      : { ad: "Rapor & Piyasa Verisi",         kota: 1 }

# ⚠ KOTA NEDEN VAR: Yarı iletken haber akışının doğası gereği AI çipleri
# ve veri merkezi haberleri bülteni tek başına domine eder. Kota olmazsa
# bültenin yarısı Nvidia haberi olur. Öne Çıkanlar'a en fazla 2 ai-cip
# haberi girebilir; gerisi Radar'a düşer.

# DEĞER ZİNCİRİ ETİKETLERİ (sitenin imza navigasyonu)
DEGER_ZINCIRI:
  - tasarim
  - eda-ip
  - malzeme
  - ekipman
  - wafer-uretim
  - paketleme-test
  - uygulama


# ============================================================
# BÖLÜM 3 — CLAUDE TALİMATLARI (İKİ AŞAMA)
# ============================================================

# ─────────────────────────────────────────────────────────
# AŞAMA 1 — TRİYAJ MOTORU (Haiku, ucuz, 40'lık partiler)
# ─────────────────────────────────────────────────────────
TRIYAJ_PROMPTU: >
  Sen bir yarı iletken sektörü haber triyaj motorusun. Yorum yapmıyorsun,
  sınıflandırıyorsun.

  ── ADIM 1: OLAY KÜMELEME (en kritik adım) ──
  Aynı gelişmeyi anlatan farklı haberler TEK OLAY'dır.
  Örnek: TSMC basın bülteni + Reuters haberi + DigiTimes analizi +
  ekipman tedarikçisi açıklaması = 1 olay, 4 kaynak.
  Her olay için en güvenilir kaynağı primary_id seç
  (resmî kurum/şirket > haber ajansı > sektör basını),
  diğerlerini supporting_ids'e koy.

  ── ADIM 2: ELEME ──
  REDDET:
    · Tarih penceresi dışı
    · Yayın tarihi doğrulanamıyor
    · Sponsorlu içerik, SEO listicle, ham pazar araştırması reklamı
    · Sadece söylenti (teyitsiz tek kaynak)
    · Ürün incelemesi, tüketici elektroniği tanıtımı, hisse yorumu
    · Önceki sayıda geçmiş olayın YENİ unsur içermeyen devamı

  ── ADIM 3: SINIFLANDIRMA ──
  12 kategoriden birine ata (BÖLÜM 2).

  ── ADIM 4: OLGUNLUK (yatırım/üretim olaylarında ZORUNLU) ──
  research | pilot | qualification | announced | funded | construction |
  equipment_install | mass_production | delayed | cancelled

  ⚠ Bu alan kritik: "10 milyar $ yatırım açıklandı" ile fiilen dökülen
  beton arasında uçurum vardır. Yarı iletken haberlerinin en büyük
  sinyal-gürültü sorunu budur.

  ── ADIM 5: PUANLAMA (1-10, kullanıcıya gösterilmez) ──
  ÖNCELİK MERDİVENİ:
    [10] Türkiye'yi DOĞRUDAN etkileyen gelişme
    [9]  İhracat kontrolü, yaptırım, büyük mevzuat (AB/ABD/Çin)
    [8]  Büyük yatırım/teşvik (>1 mlr USD) veya kapasite kararı
    [7]  Tedarik zinciri kırılması, kritik hammadde, darboğaz
    [6]  Teknoloji kırılımı, ilk üretim, ticari ölçeğe geçiş
    [5]  Sektör kuruluşu raporu, doğrulanmış piyasa verisi
    [4]  Şirket ortaklığı, orta ölçekli yatırım, ürün lansmanı
    [1-3] Rutin haber, tekrar, düşük etkili gelişme

  CEZALAR:
    -1  birincil kaynak yok
    -3  tarih doğrulanamadı
    -3  sadece söylenti / teyitsiz tek kaynak
    -3  önceki sayıda geçen olayın yeni unsuru yok
    -2  ödemeli duvar, sadece başlık görülüyor
    dışla  sponsorlu içerik

  ÇIKTI: sadece geçerli JSON
  {"events":[{event_key, baslik_ozet, primary_id, supporting_ids[],
              kategori, olgunluk, sirketler[], ulkeler[],
              yatirim_usd_milyon, puan, gerekce}],
   "reject":[{id, sebep}]}

# ─────────────────────────────────────────────────────────
# AŞAMA 2 — BÜLTEN YAZIMI (Sonnet, kaliteli)
# ─────────────────────────────────────────────────────────
YAZIM_PROMPTU: >
  Sen T.C. Sanayi ve Teknoloji Bakanlığı için haftalık yarı iletken
  izleme bülteni hazırlayan kıdemli bir uzmansın.

  Okuyucun: Bakanlık üst yönetimi, sanayi politikası uzmanları, sektör.
  Ton: Kurumsal, ölçülü, kesin. Gazetecilik heyecanı yok; kamu brifingi
  disiplini var.

  ── KAPSAM ──
  Yarı iletken değer zincirinin TAMAMI: tasarım/EDA, IP, malzeme,
  ekipman, wafer üretimi (foundry/IDM), ileri paketleme ve test, bellek,
  AI çipleri, güç ve bileşik yarı iletkenler, uygulama alanları
  (otomotiv/savunma/uzay/endüstri), politika ve jeopolitik, ihracat
  kontrolleri, teşvik programları.

  ── ÇIKTI KATMANLARI ──
  Haftada 40-60 kayda değer gelişme olur. Düz liste bunu taşımaz.
  Katmanlı yapı:

    1. MANŞET               1 olay    → 4-5 paragraf
    2. BU HAFTA 60 SANİYEDE 5 madde   → tek cümle, ≤25 kelime
    3. ÖNE ÇIKANLAR         8-10 olay → 2-3 cümle özet + 2-3 paragraf
    4. RADAR                18-30 olay→ tek satır, tema kümelerine gruplu
    5. HAFTANIN RAKAMLARI   4 gösterge

  "60 Saniyede" şablonu:
    · en önemli politika/mevzuat gelişmesi
    · en büyük yatırım/kapasite kararı
    · en önemli teknoloji gelişmesi
    · en kritik tedarik zinciri riski
    · Türkiye'den gelişme (yoksa: 2. kritik küresel gelişme)

  ── YAZIM KURALLARI ──

  DİL: Türkçe. Kilit teknik terimi İLK geçtiğinde parantezle ver:
    "ileri paketleme (advanced packaging)"
    "kapı-etrafı-sarmalı transistör (GAA)"
    "yüksek bant genişlikli bellek (HBM)"
  Sonraki geçişlerde tekrarlama. Yerleşik kısaltmaları (EUV, DRAM, SiC,
  GaN, EDA, ASIC) ÇEVİRME.

  ANALİZ YAPMA. Sadece gelişmeyi aktar. "Türkiye için önemi şudur",
  "bu bir dönüm noktasıdır" gibi çıkarım YAZMA.
  → "neden_onemli" alanı HER ZAMAN null.
  → (Bu alan v2'de açılacak; şema bugünden hazır bekliyor.)

  RAKAM DİSİPLİNİ: Tutar, kapasite, nanometre, tarih — kaynakta ne
  yazıyorsa o. Emin değilsen yazma. Para birimini koru, USD karşılığı
  biliniyorsa parantezle ekle.

  OLGUNLUK DİLİ: "Yatırım açıklandı" ≠ "inşaata başlandı" ≠ "seri
  üretime geçildi". Fiili aşamayı net belirt. Belirsizse "duyuruldu".

  KAYNAK: Birincil kaynak ile destekleyici kaynaklar AYRI gösterilir.
  Ödemeli duvar arkasındaki iddiaları kesin bilgi gibi sunma;
  "bildirildi" dilini kullan.

  SLUG: her olay için URL-dostu, aksansız, küçük harfli Türkçe slug.

  ÇIKTI: sadece geçerli JSON (BÖLÜM 5'teki şema).


# ============================================================
# BÖLÜM 4 — KAYNAK KATMANLARI
# ============================================================
# tier 1 = BİRİNCİL (resmî kurum, şirket newsroom) → önceliklidir
# tier 2 = güvenilir haber ajansı / sektör basını
# tier 3 = ikincil, dikkatli kullan

TIER_1_RESMI_KURUMLAR:
  ab:
    - digital-strategy.ec.europa.eu
    - ec.europa.eu
    - eur-lex.europa.eu
    - chips-ju.europa.eu          # Chips Joint Undertaking
    - cordis.europa.eu
  abd:
    - commerce.gov
    - bis.doc.gov                 # ihracat kontrolleri
    - nist.gov
    - chips.gov
    - defense.gov
    - federalregister.gov
  asya:
    - meti.go.jp                  # Japonya
    - motie.go.kr                 # Güney Kore
    - moea.gov.tw                 # Tayvan
    - miit.gov.cn                 # Çin
    - meity.gov.in                # Hindistan
    - ismission.gov.in            # India Semiconductor Mission
  uluslararasi:
    - oecd.org
    - worldbank.org
    - wto.org

TIER_1_SEKTOR_KURULUSLARI:
  - semi.org                      # SEMI
  - semiconductors.org            # SIA
  - eusemiconductors.eu           # ESIA
  - imec-int.com
  - leti-cea.com
  - fraunhofer.de
  - wsts.org
  - ieee.org

TIER_1_SIRKETLER:
  foundry_idm:
    - tsmc.com, samsung.com, intel.com, gf.com, umc.com, smic.com
    - rapidus.inc, st.com, infineon.com, nxp.com, ti.com, renesas.com, bosch.com
  bellek:
    - skhynix.com, micron.com, kioxia.com
  ekipman:
    - asml.com, appliedmaterials.com, lamresearch.com, kla.com, tel.com, asm.com
  malzeme:
    - siltronic.com, shinetsu.co.jp, sumcosi.com, entegris.com
    - merckgroup.com, airliquide.com, linde.com
  tasarim_ai:
    - nvidia.com, amd.com, qualcomm.com, broadcom.com, mediatek.com
    - marvell.com, arm.com, synopsys.com, cadence.com, sw.siemens.com
  paketleme:
    - aseglobal.com, amkor.com, jcetglobal.com
  guc:
    - wolfspeed.com, onsemi.com, vishay.com, microchip.com, analog.com

TIER_2_HABER_VE_SEKTOR:
  - reuters.com, bloomberg.com, ft.com, asia.nikkei.com
  - eetimes.com, eetimes.eu, semiengineering.com, digitimes.com
  - trendforce.com, techinsights.com, theregister.com
  - yolegroup.com, semianalysis.com, electronicsweekly.com
  - compoundsemiconductor.net, 3dincites.com, evertiq.com
  - spectrum.ieee.org
  # ⚠ DIGITIMES ve TrendForce hızlıdır ama söylenti oranı yüksektir.
  #   Teyitsiz iddiaları "bildirildi" diliyle aktar, kesin bilgi sayma.

AKADEMIK:
  - nature.com, science.org, arxiv.org, ieeexplore.ieee.org
  - pubs.acs.org, onlinelibrary.wiley.com, pubs.aip.org
  # ⚠ Haftalık tüm makaleler ALINMAZ. Sadece şu eşikten geçenler:
  #   prototip gösterimi · performans rekoru · ölçeklenebilir üretim ·
  #   ticari uygulama potansiyeli · yeni malzeme veya süreç

TURKIYE:
  kamu:
    - sanayi.gov.tr, tubitak.gov.tr, bilgem.tubitak.gov.tr
    - ticaret.gov.tr, cbddo.gov.tr, kosgeb.gov.tr, tenmak.gov.tr, ssb.gov.tr
  sanayi:
    - aselsan.com.tr, tusas.com, havelsan.com.tr, roketsan.com.tr
    - vestel.com.tr, arcelikglobal.com
  sivil_toplum:
    - tobb.org.tr, tusiad.org, esiad.org.tr, tim.org.tr
  basin:
    - aa.com.tr, dunya.com, ekonomim.com, bloomberght.com
    - chip.com.tr, webrazzi.com, shiftdelete.net, donanimhaber.com

DISLA (asla kullanılmaz):
  sosyal:  linkedin.com, facebook.com, x.com, twitter.com, reddit.com
           medium.com, quora.com, youtube.com, pinterest.com
  ham_pr:  prnewswire.com, globenewswire.com, businesswire.com
  seo:     marketresearchfuture.com, marketsandmarkets.com
           researchandmarkets.com, verifiedmarketresearch.com
           openpr.com, einpresswire.com, issuewire.com


# ============================================================
# BÖLÜM 5 — ÇIKTI ŞEMASI
# ============================================================
# dist/data/latest.json ve dist/data/arsiv/YYYY-Www.json

{
  "issue": {
    "number": 1,
    "hafta": "2026-W29",
    "publication_date": "2026-07-13",
    "coverage_start": "2026-07-06",
    "coverage_end": "2026-07-13",
    "window_days": 7,
    "audio": null              # ← v2: sesli bülten (ElevenLabs)
  },
  "brief": ["...", "...", "...", "...", "..."],       # tam 5 madde
  "metrics": {
    "aciklanan_yatirim_usd_milyon": 0,
    "fab_proje_sayisi": 0,
    "politika_gelismesi": 0,
    "kapsanan_ulke": 0
  },
  "lead": { <story> },
  "stories": [ <8-10 story> ],
  "radar": [
    { "kume": "İhracat kontrolleri",
      "maddeler": [{ title, source, url, date, category }] }
  ]
}

# story nesnesi:
{
  "id": "event_001",
  "slug": "tsmc-dresden-kapasite-artirimi",
  "title": "8-14 kelime, iddiasız, olgusal",
  "excerpt": "2-3 cümle: ne, kim, nerede, ne zaman, tutar/kapasite",
  "detail": "2-3 paragraf (manşette 4-5), \n\n ile ayrılmış",
  "neden_onemli": null,                 # ← v2 analiz katmanı
  "category": "yatirim",                # 12 kategoriden biri
  "subcategories": ["EU Chips Act"],
  "value_chain": ["wafer-uretim"],      # site imza navigasyonu
  "maturity": "construction",           # 10 olgunluk seviyesinden biri
  "companies": ["TSMC"],
  "countries": ["Almanya"],
  "technologies": ["FinFET"],
  "technology_nodes": ["28nm"],
  "investment": {
    "amount_original": 10, "currency": "EUR",
    "amount_usd_million": 10800, "public_support_usd_million": 5000
  },
  "published_date": "2026-07-10",
  "event_date": "2026-07-09",
  "source": { "name": "...", "url": "...", "type": "official",
              "tier": 1, "primary": true },
  "supporting_sources": [{ "name": "Reuters", "url": "..." }],
  "image": { "url": null, "credit": null, "type": null },
  "score": 8
}

# source.type: official | company | news_agency | trade_press | research | academic
# value_chain: tasarim | eda-ip | malzeme | ekipman | wafer-uretim |
#              paketleme-test | uygulama


# ============================================================
# BÖLÜM 6 — KALICI HAFIZA (STATE)
# ============================================================
# ⚠ Render'ın diski her çalışmada SIFIRLANIR. Bu yüzden "görülmüş olay"
# hafızası diskte tutulamaz. Çözüm: state, deploy edilen sitenin içinde
# yaşar ve her çalışmada oradan okunur.
#
#   main.py başlarken  →  GET {site_url}/data/state/seen_events.json
#   main.py biterken   →  güncel state'i dist/ içine yazar
#
# Bu olmadan 2. hafta 1. haftanın haberlerini yeniden yayımlar.
# İlk çalıştırmada 404 alması NORMALDİR — sıfırdan başlar.

STATE_SEMASI:
  issue_no: 12                    # son yayımlanan sayı numarası
  events:   [{baslik_ozet, hafta}]  # son ~400 olay
  urls:     ["https://..."]         # son ~3000 normalize URL


# ============================================================
# BÖLÜM 7 — GENEL AYARLAR
# ============================================================
AYARLAR:
  yayim_gunu:            pazartesi
  yayim_saati:           "08:00"        # TSİ  (Render cron: 0 5 * * 1 UTC)
  pencere_gun:           7
  pencere_genis_gun:     14             # <40 aday çıkarsa genişler
  turkiye_pencere_gun:   21

  manset:                1
  brief_madde:           5
  one_cikan_min:         8
  one_cikan_max:         10
  radar_min:             18
  radar_max:             30

  model_triyaj:          claude-haiku-4-5-20251001
  model_yazim:           claude-sonnet-4-6
  # ⚠ temperature parametresi BİLEREK GÖNDERİLMİYOR.
  #   (Biyoekonomi bülteninde temperature=0 ile yaşanan uyumsuzluk.)

  triyaj_batch:          40
  exa_sonuc_sayisi:      20
  exa_highlight_karakter: 1200
  cikti_dili:            tr


# ============================================================
# BÖLÜM 8 — BİLDİRİM (SADECE ORCAN'A)
# ============================================================
# Bülten herkese açıktır. Çalışma raporu sadece e-posta ile gelir.

BILDIRIM:
  aktif: true
  yontem: email
  icerik:
    - Sayı numarası, kapsam, pencere
    - Sorgu sayısı / ham sonuç / elenen / olay / reddedilen / yayımlanan
    - Radar madde sayısı
    - BAŞARISIZ SORGULAR listesi        ← sorgu kalitesi kalibrasyonu için kritik
    - Şema hataları
    - En yüksek puanlı 3 haber
    - Deploy sonucu
    - Son 40 satır log


# ============================================================
# BÖLÜM 9 — v2 YOL HARİTASI (kancalar bugünden hazır)
# ============================================================
# 1. EDİTORYAL ANALİZ ("Neden önemli?")
#    prompts.py → "neden_onemli null" talimatını kaldır
#    main.py → dogrula() içindeki s["neden_onemli"]=None satırını sil
#    Site zaten .why.on ile render ediyor. Şema alanı bugün rezerve.
#
# 2. SESLİ BÜLTEN (ElevenLabs)
#    brief metnini TTS'e gönder → dist/assets/audio/{hafta}.mp3
#    issue.audio = {url, duration_sec, voice, generated_at}
#    Site oynatıcıyı otomatik gösterir. Sayfa YAVAŞLAMAZ (lazy load).
#
# 3. HERO VİDEOSU (Higgsfield vb.)
#    assets/video/hero.webm + hero.mp4 + hero.jpg
#    index.html sonundaki yorumlu CSS bloğunu aç.
#    ⚠ ÇALIŞMA ZAMANI BAĞIMLILIĞI YOK — statik dosya, MCP gerekmez.
#    Hedef: ≤1.5 MB, 6-8 sn, sessiz, mobilde kapalı.
#
# 4. PERPLEXITY YEDEK KATMANI
#    Sadece 'turkiye' sorgusu için. Exa'nın TR indeksi zayıf.
#
# 5. İLERİSİ: şirket/ülke sayfaları · olay zaman çizelgesi ·
#    yatırım veri tabanı · aylık eğilim raporu · e-posta aboneliği
