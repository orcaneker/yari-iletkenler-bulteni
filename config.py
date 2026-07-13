# -*- coding: utf-8 -*-
"""
YARI İLETKEN BÜLTENİ — YAPILANDIRMA
====================================
Sorgular, kaynak katmanları ve ayarlar burada. main.py bunları okur.
Yeni sorgu/kaynak eklemek için sadece bu dosyayı düzenle.
"""

# ============================================================
# GENEL AYARLAR
# ============================================================
AYARLAR = {
    "yayim_gunu": "pazartesi",
    "pencere_gun": 7,                # birincil tarama penceresi
    "pencere_genis_gun": 14,         # yetersiz sonuçta genişletilir
    "turkiye_pencere_gun": 21,       # TR haber akışı seyrek — daha geniş pencere

    # Bülten hacim hedefleri
    "manset": 1,
    "brief_madde": 5,                # "Bu Hafta 60 Saniyede"
    "one_cikan_min": 8,
    "one_cikan_max": 10,
    "radar_min": 18,
    "radar_max": 30,

    # LLM
    "model_triyaj": "claude-haiku-4-5-20251001",   # ucuz: eleme + kümeleme
    "model_yazim": "claude-sonnet-4-6",            # kaliteli: nihai yazım
    # NOT: temperature parametresi BİLEREK gönderilmiyor.
    # (Biyoekonomi bülteninde temperature=0 ile yaşanan uyumsuzluk sorunu.)
    "triyaj_batch": 40,              # Haiku'ya tek seferde gönderilen aday sayısı
    "max_tokens_triyaj": 8000,
    "max_tokens_yazim": 16000,

    # Exa
    "exa_sonuc_sayisi": 20,          # sorgu başına
    "exa_highlight_karakter": 1200,  # Claude'a giden metin miktarı (token kontrolü)
    "exa_tip": "auto",

    # Site
    "site_url": "https://orcaneker.github.io/yari-iletkenler-bulteni",
    "cikti_dizini": "docs",   # GitHub Pages sadece / veya /docs kabul eder
}

# ============================================================
# KATEGORİ TAKSONOMİSİ (12)
# Kod → (Görünen ad, Öne Çıkanlar kotası hedefi)
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

# Değer zinciri etiketleri (site navigasyonunun omurgası)
DEGER_ZINCIRI = [
    "tasarim", "eda-ip", "malzeme", "ekipman",
    "wafer-uretim", "paketleme-test", "uygulama",
]

# ============================================================
# KAYNAK KATMANLARI
# tier 1 = birincil (resmi kurum, şirket newsroom)
# tier 2 = güvenilir haber ajansı / sektör basını
# tier 3 = ikincil, dikkatli kullan
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

# Asla kullanılmayacak / sponsorlu-SEO ağırlıklı kaynaklar
KAYNAK_DISLA = [
    "linkedin.com", "facebook.com", "x.com", "twitter.com", "reddit.com",
    "medium.com", "quora.com", "youtube.com", "pinterest.com",
    "prnewswire.com", "globenewswire.com", "businesswire.com",  # ham PR dağıtım
    "marketresearchfuture.com", "marketsandmarkets.com",
    "researchandmarkets.com", "verifiedmarketresearch.com",
    "openpr.com", "einpresswire.com", "issuewire.com",
]

# ============================================================
# EXA SORGULARI (11)
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
        "pencere_gun": 21,        # TR için geniş pencere
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
