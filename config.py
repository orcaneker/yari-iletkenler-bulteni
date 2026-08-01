# -*- coding: utf-8 -*-
"""
YARI İLETKEN BÜLTENİ — YAPILANDIRMA
====================================
Sorgular, kategori taksonomisi, kaynak katmanları ve ayarlar burada.
pipeline.py / publish.py / review_app bunları okur.
Yeni sorgu/kaynak eklemek için sadece bu dosyayı düzenle.
"""

# ============================================================
# GENEL AYARLAR
# ============================================================
AYARLAR = {
    # Takvim: taslak Pazar 12:30 TSİ hazırlanır, yayın Pazartesi 08:00 TSİ.
    # Render cron (UTC): taslak "30 9 * * 0" · yayın "0 5 * * 1"
    # ⚠ 12:30, diğer iki bültenle (biyoekonomi 12:00, nükleer 13:00) aynı
    # Anthropic/Exa anahtarını paylaştığı için bilinçli seçildi —
    # gerekçe render.yaml başındaki notta.
    "taslak_gunu": "pazar",
    "yayim_gunu": "pazartesi",
    "yayim_saati_tsi": 8,            # yayın eşiği (geç onay kontrolünde kullanılır)

    "pencere_gun": 7,                # birincil tarama penceresi
    "pencere_genis_gun": 14,         # yetersiz sonuçta genişletilir

    # Bülten hacim hedefleri
    "manset": 1,
    "brief_madde": 5,                # "Bu Hafta 60 Saniyede"
    "one_cikan_min": 8,
    "one_cikan_max": 10,
    "radar_min": 18,
    "radar_max": 30,

    # LLM — sağlayıcı öneki zorunlu: "anthropic:..." veya "openai:..."
    "model_triyaj": "anthropic:claude-haiku-4-5-20251001",
    "model_yazim": "anthropic:claude-sonnet-5",
    # NOT: temperature parametresi BİLEREK gönderilmiyor (model uyumsuzluk deneyimi).

    # OpenAI reasoning modelleri (gpt-5.6 ailesi) için akıl yürütme seviyesi:
    # none | low | medium | high | xhigh | max
    # Anthropic modellerinde yok sayılır. REASONING_EFFORT ortam değişkeni
    # bu ayarı ezer (deneme yaparken pratik).
    "reasoning_effort": "medium",
    "triyaj_batch": 40,              # tek seferde triyaja giden aday sayısı
    "max_tokens_triyaj": 8000,
    "max_tokens_yazim": 48000,       # 14 haberin TAMAMI yazıldığı için GENİŞ olmalı.
                                     # ⚠ Düşük tutulursa çıktı JSON tamamlanmadan kesilir.
    # Akıl yürüten modellerde (gpt-5.x, Sonnet 5, Opus 4.7+, Fable 5) "düşünme"
    # token'ları da BU bütçeden düşer — görünür metne kalan pay azalır ve JSON
    # ortadan kesilebilir. Bu modeller 128K çıktı desteklediği için rahat pay
    # bırakıldı — kullanılmayan bütçe ücretlendirilmez.
    "max_tokens_yazim_reasoning": 96000,
    "derin_olay_sayisi": 14,         # tam metinle yazıma giden olay — HEPSİ haber olur
    "toplam_olay_sayisi": 40,        # geri kalanı radar adayı (başlık+link)

    # Exa
    "exa_sonuc_sayisi": 20,          # sorgu başına
    "exa_metin_karakter": 4000,      # çekilen makale metni
    "exa_triyaj_karakter": 700,      # triyaja giden kısa parça (ucuz)
    "yazim_birincil_karakter": 3500, # birincil kaynak derin okunur
    "yazim_destek_karakter": 800,    # destekleyici sadece fark için
    "exa_tip": "auto",

    # Site
    "site_url": "https://yari-iletkenler-bulteni.site",
    "cikti_dizini": "docs",          # GitHub Pages sadece / veya /docs kabul eder

    # Sayı numarası: None → otomatik artar (yayınlanan son sayı + 1).
    # Sayaç canlı sitedeki data/state/seen_events.json → issue_no alanında
    # yaşar; publish.py her yayında oraya yazar. Arşiv ve state sıfırlandığı
    # için (bkz. docs/data) ilk gerçek çalıştırma otomatik olarak Sayı 1 olur.
    # Test amacıyla numarayı dondurmak istersen sabit bir sayı ver — ama
    # YAYINA GEÇERKEN None'a geri al, aksi halde her sayı aynı numarayı
    # alır ve arşivde mükerrer görünür.
    "sayi_no_sabit": None,
}

# ============================================================
# FİYATLANDIRMA (USD / 1 milyon token) — maliyet TAHMİNİ için
# ⚠ Fiyatlar değişebilir; console.anthropic.com / platform.openai.com'dan doğrula.
# ============================================================
FIYAT = {
    "anthropic:claude-sonnet-4-6":         {"in": 3.00, "out": 15.00, "cache_w": 3.75, "cache_r": 0.30},
    "anthropic:claude-haiku-4-5-20251001": {"in": 1.00, "out":  5.00, "cache_w": 1.25, "cache_r": 0.10},
    "openai:gpt-5-mini":                   {"in": 0.25, "out":  2.00, "cache_w": 0.25, "cache_r": 0.025},
    "openai:gpt-5.1":                      {"in": 1.25, "out": 10.00, "cache_w": 1.25, "cache_r": 0.125},
    "openai:gpt-5.6-luna":                 {"in": 1.00, "out":  6.00, "cache_w": 1.25, "cache_r": 0.10},
    # ⚠ Sonnet 5 liste fiyatı 4.6 ile AYNI ($3/$15) ama 31 Ağustos 2026'ya kadar
    # tanıtım fiyatı $2/$10. Aşağıda LİSTE fiyatı yazılı — maliyet raporu böylece
    # olduğundan düşük görünmez.
    "anthropic:claude-sonnet-5":           {"in": 3.00, "out": 15.00, "cache_w": 3.75, "cache_r": 0.30},
}

# ============================================================
# EXA ARAMA FİYATI (USD) — maliyet TAHMİNİ için
# ⚠ exa.ai/pricing'den doğrula; değişebilir.
# Model: istek başına taban ücret İLK 10 SONUCU kapsar (sayfa içeriği dahil,
# Mart 2026 güncellemesi); 10'un üzerindeki her sonuç ayrıca ücretlenir.
# ============================================================
EXA_FIYAT = {
    "arama": 7.00 / 1000,      # $7 / 1.000 istek (ilk 10 sonuç dahil)
    "ek_sonuc": 1.00 / 1000,   # 10'un üzerindeki her sonuç için $1 / 1.000
}

# ============================================================
# KATEGORİ TAKSONOMİSİ (12)
# Kod → (Görünen ad, Öne Çıkanlar kota hedefi)
# ============================================================
KATEGORILER = {
    "politika":  {"ad": "Politika & Jeopolitik",          "kota": 2},
    "yatirim":   {"ad": "Yatırım & Üretim",               "kota": 2},
    "ekipman":   {"ad": "Ekipman & Malzeme",              "kota": 1},
    "teknoloji": {"ad": "Süreç Teknolojisi",              "kota": 1},
    "paketleme": {"ad": "İleri Paketleme & Test",         "kota": 1},
    "bellek":    {"ad": "Bellek & Depolama",              "kota": 1},
    "ai-cip":    {"ad": "AI Çipleri & Veri Merkezi",      "kota": 1},
    "tasarim":   {"ad": "Tasarım, EDA & IP",              "kota": 0},
    "guc":       {"ad": "Güç & Bileşik Yarı İletkenler",  "kota": 1},
    "uygulama":  {"ad": "Otomotiv, Savunma & Endüstri",   "kota": 0},
    "turkiye":   {"ad": "Türkiye",                        "kota": 1},
    "rapor":     {"ad": "Rapor & Piyasa Verisi",          "kota": 1},
}

# ⚠ KOTA NEDEN VAR: AI çipi/veri merkezi haberleri akışı domine edebilir.
# Kota olmadan bültenin yarısı AI hızlandırıcı duyurusu olur.

# Değer zinciri etiketleri (site navigasyonunun omurgası)
DEGER_ZINCIRI = [
    "tasarim", "eda-ip", "malzeme", "ekipman",
    "wafer-uretim", "paketleme-test", "uygulama",
]

# ============================================================
# OLGUNLUK ÖLÇEĞİ — yarı iletken yatırım/üretim projeleri için
# "Yatırım açıklandı" ile "seri üretime geçildi" arasında yıllar vardır;
# fab inşaatından ekipman kurulumuna, oradan verim eğrisine geçiş bu
# sektörün en büyük sinyal-gürültü sorunudur.
# ============================================================
OLGUNLUK = [
    "research",           # araştırma / laboratuvar kavram kanıtı
    "pilot",               # pilot hat / küçük ölçek
    "qualification",       # süreç/ürün nitelendirme
    "announced",           # niyet/anlaşma duyuruldu
    "funded",               # finansman kapandı / teşvik onaylandı
    "construction",         # fab inşaatı sürüyor
    "equipment_install",    # ekipman kurulumu / devreye alma
    "mass_production",      # seri üretimde
    "delayed",
    "cancelled",
]

# ============================================================
# KAYNAK KATMANLARI
# tier 1 = birincil (resmî kurum, şirket newsroom)
# tier 2 = güvenilir haber ajansı / sektör basını
# ============================================================
KAYNAK_TIER1 = [
    # AB
    "digital-strategy.ec.europa.eu", "ec.europa.eu", "eur-lex.europa.eu",
    "chips-ju.europa.eu", "cordis.europa.eu",
    # ABD
    "commerce.gov", "bis.doc.gov", "nist.gov", "chips.gov", "defense.gov",
    "federalregister.gov",
    # Asya
    "meti.go.jp", "motie.go.kr", "moea.gov.tw", "miit.gov.cn", "meity.gov.in",
    "ismission.gov.in",
    # Uluslararası
    "oecd.org", "worldbank.org", "wto.org",
    # Sektör kuruluşları
    "semi.org", "semiconductors.org", "eusemiconductors.eu", "imec-int.com",
    "leti-cea.com", "fraunhofer.de", "wsts.org", "ieee.org",
    # Şirket newsroom
    "tsmc.com", "samsung.com", "intel.com", "gf.com", "umc.com", "smic.com",
    "rapidus.inc", "st.com", "infineon.com", "nxp.com", "ti.com", "renesas.com",
    "bosch.com", "skhynix.com", "micron.com", "kioxia.com",
    "asml.com", "appliedmaterials.com", "lamresearch.com", "kla.com",
    "tel.com", "asm.com", "siltronic.com", "shinetsu.co.jp", "sumcosi.com",
    "entegris.com", "merckgroup.com", "airliquide.com", "linde.com",
    "nvidia.com", "amd.com", "qualcomm.com", "broadcom.com", "mediatek.com",
    "marvell.com", "arm.com", "synopsys.com", "cadence.com", "sw.siemens.com",
    "aseglobal.com", "amkor.com", "jcetglobal.com", "wolfspeed.com",
    "onsemi.com", "vishay.com", "microchip.com", "analog.com",
]

# ⚠ reuters.com ve bloomberg.com Exa'nın includeDomains filtresinde KABUL EDİLMİYOR
# (lisans kısıtı, 403 döner). Listeye EKLEME. Bu kaynaklar zaten domain filtresi
# olmayan aramalarda ve diğer sitelerin alıntılarında dolaylı olarak yakalanıyor.
KAYNAK_TIER2 = [
    "ft.com", "asia.nikkei.com", "cnbc.com", "wsj.com",
    "eetimes.com", "eetimes.eu", "semiengineering.com", "digitimes.com",
    "trendforce.com", "techinsights.com", "theregister.com",
    "yolegroup.com", "semianalysis.com", "electronicsweekly.com",
    "compoundsemiconductor.net", "3dincites.com", "evertiq.com",
    "spectrum.ieee.org", "anandtech.com", "tomshardware.com",
]

KAYNAK_AKADEMIK = [
    "nature.com", "science.org", "arxiv.org", "ieeexplore.ieee.org",
    "pubs.acs.org", "onlinelibrary.wiley.com", "pubs.aip.org",
]

KAYNAK_TURKIYE = [
    "sanayi.gov.tr", "tubitak.gov.tr", "bilgem.tubitak.gov.tr",
    "ticaret.gov.tr", "cbddo.gov.tr", "kosgeb.gov.tr", "tenmak.gov.tr",
    "ssb.gov.tr", "aselsan.com.tr", "tusas.com", "havelsan.com.tr",
    "roketsan.com.tr", "vestel.com.tr", "arcelikglobal.com",
    "tobb.org.tr", "tusiad.org", "esiad.org.tr", "tim.org.tr",
    "aa.com.tr", "dunya.com", "ekonomim.com", "bloomberght.com",
    "chip.com.tr", "webrazzi.com", "shiftdelete.net", "donanimhaber.com",
]

# ============================================================
# ÖDEME DUVARLI KAYNAKLAR
# ------------------------------------------------------------
# Bu kaynaklar DIŞLANMAZ — haber değerleri yüksek, çoğu zaman bir
# gelişmeyi ilk onlar veriyor. Ama Exa yalnızca teaser paragrafını
# görebiliyor. Bu yüzden:
#   · asla BİRİNCİL kaynak olmazlar (erişilebilir kaynak varsa o birincil olur)
#   · tek kaynak onlarsa olay YAZILMAZ, RADAR'a düşer (başlık + link yeterli)
# Böylece "ödeme duvarı arkasında, detaylandırılmadı" gibi içi boş
# cümleler bülten metnine hiç girmez.
# ============================================================
KAYNAK_ODEME_DUVARI = [
    "digitimes.com", "ft.com", "wsj.com", "asia.nikkei.com",
    "theinformation.com", "economist.com", "semianalysis.com",
    "techinsights.com", "yolegroup.com", "trendforce.com",
    "gartner.com", "idc.com", "counterpointresearch.com",
]

# Metinde bunlardan biri geçiyorsa → ödeme duvarı (alan adına bakmaksızın)
ODEME_DUVARI_IZLERI = [
    "subscribe to read", "subscribers only", "members only",
    "sign in to continue", "log in to read", "register to continue",
    "this content is for", "paywall", "premium content",
    "abone olun", "üyelere özel", "içeriğin tamamını okumak",
]
ODEME_DUVARI_MIN_KARAKTER = 500   # bundan kısa metin → içi boş, duvarlı say

# ── TEYİT ARAMASI (corroboration search) ──────────────────
# Tüm kaynakları ödeme duvarlı olan bir olayı doğrudan çöpe atmıyoruz.
# DigiTimes gibi kaynakların haberleri genellikle saatler içinde açık
# sitelerde (Tom's Hardware, TrendForce, DonanımHaber, Reuters…) yankılanır.
# Olayın başlığıyla İKİNCİ bir Exa araması yapıp erişilebilir bir kaynak
# bulmaya çalışıyoruz. Bulursak olay yazılabilir hale gelir.
# ⚠ Bulunan kaynak ikinci elden aktarımdır → "bildirildi" diliyle yazılır.
TEYIT = {
    "aktif": True,
    "max_olay": 12,          # en yüksek puanlı N duvarlı olay için ara (maliyet sınırı)
    "sonuc": 6,              # arama başına sonuç
    "min_benzerlik": 0.20,   # başlık örtüşme eşiği (Jaccard)
    "min_ortak_kelime": 2,   # en az bu kadar anlamlı kelime ortak olmalı
    "min_metin": 700,        # teyit kaynağının metni bundan uzun olmalı
    "gun_toleransi": 3,      # olay tarihinden ± bu kadar gün
}

# Başlık karşılaştırmasında yok sayılacak kelimeler
DURAK_KELIMELER = {
    "the", "and", "for", "with", "from", "that", "this", "will", "have", "has",
    "into", "over", "amid", "says", "said", "new", "its", "not", "but", "are",
    "was", "were", "been", "more", "than", "after", "before", "report", "reports",
    "reportedly", "according", "sources", "source", "chip", "chips", "semiconductor",
    "ile", "için", "olarak", "yeni", "bir", "bu", "de", "da", "ve",
}

# Asla kullanılmayacak / sponsorlu-SEO ağırlıklı kaynaklar
KAYNAK_DISLA = [
    "linkedin.com", "facebook.com", "x.com", "twitter.com", "reddit.com",
    "medium.com", "quora.com", "youtube.com", "pinterest.com",
    "prnewswire.com", "globenewswire.com", "businesswire.com",  # ham PR dağıtım
    "marketresearchfuture.com", "marketsandmarkets.com",
    "researchandmarkets.com", "verifiedmarketresearch.com",
    "grandviewresearch.com", "fortunebusinessinsights.com",
    "openpr.com", "einpresswire.com", "issuewire.com",
]

# ============================================================
# EXA SORGULARI (12)
# ------------------------------------------------------------
# Exa'da uzun doğal dil komutu YAZILMAZ. Kısa semantik sorgu + ayrı
# parametreler (domain, tarih, kategori) kullanılır.
# 'ek_sorgular' aynı temanın farklı yüzlerini yakalar.
# 'domain_seti' → hangi kaynak katmanına öncelik verileceği.
# ============================================================
SORGULAR = [
    {
        "id": "politika",
        "kategori": "politika",
        "sorgu": "semiconductor policy, export controls and chip geopolitics",
        "ek_sorgular": [
            "EU Chips Act 2.0 semiconductor strategy",
            "US CHIPS Act funding and semiconductor export restrictions",
            "China semiconductor policy and retaliation measures",
            "critical raw materials gallium germanium rare earth chip supply",
        ],
        "domain_seti": ["tier1", "tier2"],
        "sonuc": 25,
    },
    {
        "id": "yatirim",
        "kategori": "yatirim",
        "sorgu": "new semiconductor fab investment and capacity expansion",
        "ek_sorgular": [
            "foundry capex announcement wafer capacity",
            "chip plant delayed cancelled construction start",
            "government subsidy approved semiconductor factory",
        ],
        "domain_seti": ["tier1", "tier2"],
        "sonuc": 25,
    },
    {
        "id": "ekipman",
        "kategori": "ekipman",
        "sorgu": "semiconductor equipment and materials supply chain",
        "ek_sorgular": [
            "ASML lithography tool shipment High-NA EUV",
            "wafer photoresist specialty gas supply semiconductor materials",
            "deposition etch metrology equipment order",
        ],
        "domain_seti": ["tier1", "tier2"],
        "sonuc": 20,
    },
    {
        "id": "teknoloji",
        "kategori": "teknoloji",
        "sorgu": "advanced semiconductor process node technology breakthrough",
        "ek_sorgular": [
            "2nm 1.4nm gate-all-around production yield",
            "backside power delivery CFET new transistor architecture",
            "silicon photonics quantum neuromorphic chip",
        ],
        "domain_seti": ["tier1", "tier2", "akademik"],
        "sonuc": 20,
    },
    {
        "id": "paketleme",
        "kategori": "paketleme",
        "sorgu": "advanced packaging chiplet and heterogeneous integration",
        "ek_sorgular": [
            "CoWoS hybrid bonding capacity expansion",
            "glass substrate panel level packaging OSAT investment",
            "HBM packaging bottleneck test and metrology",
        ],
        "domain_seti": ["tier1", "tier2"],
        "sonuc": 20,
    },
    {
        "id": "bellek",
        "kategori": "bellek",
        "sorgu": "DRAM NAND and HBM memory market developments",
        "ek_sorgular": [
            "HBM4 supply agreement memory pricing",
            "Samsung SK hynix Micron memory capacity",
        ],
        "domain_seti": ["tier1", "tier2"],
        "sonuc": 15,
    },
    {
        "id": "ai-cip",
        "kategori": "ai-cip",
        "sorgu": "AI accelerator chips and data center silicon",
        "ek_sorgular": [
            "Nvidia AMD custom ASIC hyperscaler chip announcement",
            "AI datacenter power and optical interconnect silicon",
        ],
        "domain_seti": ["tier1", "tier2"],
        "sonuc": 20,
    },
    {
        "id": "tasarim",
        "kategori": "tasarim",
        "sorgu": "chip design EDA and semiconductor IP developments",
        "ek_sorgular": [
            "RISC-V Arm architecture licensing",
            "Synopsys Cadence EDA AI design tool",
        ],
        "domain_seti": ["tier1", "tier2"],
        "sonuc": 15,
    },
    {
        "id": "guc",
        "kategori": "guc",
        "sorgu": "silicon carbide gallium nitride power semiconductor",
        "ek_sorgular": [
            "SiC GaN fab investment automotive power module",
            "RF compound semiconductor defense telecom",
        ],
        "domain_seti": ["tier1", "tier2"],
        "sonuc": 15,
    },
    {
        "id": "uygulama",
        "kategori": "uygulama",
        "sorgu": "automotive defense and industrial semiconductor applications",
        "ek_sorgular": [
            "automotive MCU ADAS radar sensor chip supply",
            "defense electronics radiation hardened space chip",
        ],
        "domain_seti": ["tier1", "tier2"],
        "sonuc": 15,
    },
    {
        "id": "turkiye",
        "kategori": "turkiye",
        "sorgu": "Türkiye yarı iletken çip mikroelektronik yatırım ve teşvik",
        "ek_sorgular": [
            "Turkey semiconductor investment chip design startup",
            "TÜBİTAK BİLGEM YİTAL mikroelektronik entegre devre",
            "Türkiye çip tasarım MEMS sensör güç elektroniği yatırımı",
            "HIT-30 yüksek teknoloji yatırım programı yarı iletken",
        ],
        "domain_seti": ["turkiye", "tier1", "tier2"],
        "sonuc": 25,
        "pencere_gun": 21,        # TR için geniş pencere — haber akışı seyrek
        "kullanici_konumu": "tr",
    },
    {
        "id": "rapor",
        "kategori": "rapor",
        "sorgu": "semiconductor industry market data and outlook report",
        "ek_sorgular": [
            "SIA SEMI WSTS billings forecast semiconductor sales",
            "TrendForce Yole semiconductor market forecast",
        ],
        "domain_seti": ["tier1", "tier2"],
        "sonuc": 15,
    },
]
