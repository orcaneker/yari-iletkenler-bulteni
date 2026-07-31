# Yarı İletken Bülteni

Haftalık otomatik yarı iletken sektörü, teknoloji ve sanayi politikası izleme
bülteni — **hakem onaylı yayın akışıyla**.

```
Exa → triyaj (Haiku) → yazım (Sonnet) → Neon taslak → hakem incelemesi (web)
                                            ↓ onay (tek hakem yeterli)
                         Pazartesi 08:00 → docs/ → GitHub Pages
```

Eski tek-script + Cloudflare Pages tabanlı sistemin yerini alan yeni mimari:
arama motoru **Exa AI**, triyaj **Claude Haiku 4.5**, yazım **Claude Sonnet 5**,
yayın öncesi **onay katmanı** (Neon + Resend + FastAPI inceleme arayüzü), tüm
derin olayların yazılması (**hakem takası için yedek havuz**), sağlayıcı-bağımsız
LLM katmanı, cron **Render**'da, yayın **GitHub Pages** üzerinden.

## Dosyalar

```
config.py            Sorgular (12), kategori taksonomisi (12), kaynaklar, ayarlar
prompts.py           LLM promptları — triyaj + yazım
llm.py               Sağlayıcı soyutlama (anthropic:… / openai:…)
pipeline.py          CRON 1 (Pazar 12:00 TSİ): tarama → taslak → Neon → davet
publish.py           CRON 2 (Pazartesi 08:00 TSİ): yayın veya hatırlatma
db.py                Neon Postgres şeması + CRUD + hakem yönetimi
emails.py            Resend şablonları (davet, hatırlatma, yayın, rapor)
review_app/          FastAPI inceleme servisi (magic link, takas, onay)
site/                Bülten sayfaları (index + arşiv) — "fab temiz odası" tasarımı
docs/                GitHub Pages çıktısı (publish.py üretir)
assets/              Hero video/görselleri (hero-loop-pingpong.mp4, hero*.avif/webp)
render.yaml          Render blueprint: 2 cron + 1 web service
sistem-prompt-yariiletken.md   Sistemin beyni/referans belgesi
```

## Kurulum

### 1. GitHub deposu
Bu depo `orcaneker/yari-iletkenler-bulteni`.
GitHub → Settings → Pages → Source: **main / docs** seçin.
Site adresi: `https://orcaneker.github.io/yari-iletkenler-bulteni`
(`config.py → AYARLAR["site_url"]` ile aynı olmalı — farklıysa güncelleyin.)

### 2. Neon (veritabanı)
Neon projenizden bağlantı dizesini alın (`postgresql://...`), sonra:

```bash
set DATABASE_URL=postgresql://...        # PowerShell: $env:DATABASE_URL="..."
python db.py --init                      # tabloları oluşturur
python db.py --seed "Ad Soyad" mail@ornek.com   # hakem ekler, linkini basar
python db.py --reviewers                 # hakemleri ve linklerini listeler
```

### 3. Render
Repo'yu Render'a bağlayın — `render.yaml` otomatik algılanır (Blueprint).
Üç servis kurulur; ortak env grubuna anahtarları girin:

| Anahtar | Zorunlu | Not |
|---|---|---|
| `EXA_API_KEY` | ✅ (cron 1) | exa.ai |
| `ANTHROPIC_API_KEY` | ✅ (cron 1) | |
| `OPENAI_API_KEY` | — | sadece `openai:` modeli denenirse |
| `DATABASE_URL` | ✅ (hepsi) | Neon |
| `RESEND_API_KEY` | ✅ (hepsi) | resend.com |
| `MAIL_FROM` | — | vars. `onboarding@resend.dev`; alan adı doğrulayınca değiştirin |
| `GITHUB_REPO` | ✅ (cron 2 + web) | `orcaneker/yari-iletkenler-bulteni` |
| `GITHUB_TOKEN` | ✅ (cron 2 + web) | PAT — Contents: Read & Write |
| `REVIEW_BASE_URL` | ✅ (cron 1-2) | inceleme servisinin URL'i (ör. `https://yari-iletken-bulten-inceleme.onrender.com`) |
| `RAPOR_ALICI` | — | çalışma raporu e-postası |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | — | sesli bülten; yoksa sessiz yayınlanır |

⚠ `REVIEW_BASE_URL` için önce web servisini deploy edip URL'ini alın,
sonra cron'ların environment'ına yazın.

### 4. LLM modeli değiştirme (opsiyonel)
`config.py`:

```python
"model_triyaj": "anthropic:claude-haiku-4-5-20251001",   # vars.
"model_yazim":  "anthropic:claude-sonnet-5",             # vars.
# OpenAI denemesi: OPENAI_API_KEY tanımlayıp şunları yazın:
# "model_triyaj": "openai:gpt-5-mini",
# "model_yazim":  "openai:gpt-5.1",
```

Yeni model kullanırken `FIYAT` sözlüğüne fiyatını da ekleyin (maliyet raporu için).

## Haftalık akış

1. **Pazar 12:00 TSİ** — cron 1 taslağı üretir, Neon'a `review` durumuyla
   yazar, hakemlere kişisel inceleme linki e-postalanır.
2. **İnceleme** — hakem linke tıklar: haberleri okur, beğenmediğini yedek
   havuzundan takas eder, radar maddesi çıkarabilir, manşeti değiştirebilir.
   **Tek onay yeterli.**
3. **Pazartesi 08:00 TSİ** — cron 2:
   - onaylıysa → nihai bülten + ElevenLabs sesli özet + GitHub push → yayın
   - onaysızsa → hatırlatma e-postası; **otomatik yayın yok**. Onay sonradan
     gelirse inceleme servisi yayını anında tetikler.

## Yerel test (API'siz)

```bash
pip install -r requirements.txt
python pipeline.py --mock --dry-run    # sahte taslak → taslak_preview.json
python publish.py --local-draft        # taslaktan docs/ üretir
python -m http.server 8080 -d docs     # http://localhost:8080 → siteyi gör
```

Gerçek anahtarlarla ama yayınsız: `python pipeline.py --dry-run`.
İnceleme arayüzü (DATABASE_URL gerekir):

```bash
python pipeline.py --mock              # sahte taslağı Neon'a yazar + davet dener
uvicorn review_app.main:app --port 8000
# tarayıcı: http://localhost:8000/r/<hakem-token>
```

## İlk yayın öncesi kontrol listesi

- [ ] `config.py → sayi_no_sabit = None` yapın (test değeri 1'de sabitli)
- [ ] `db.py --seed` ile gerçek hakemleri ekleyin
- [ ] Render'da cron 1'i elle tetikleyip (Manual Run) daveti test edin
- [ ] İnceleme linkinden takas + onay akışını deneyin
- [ ] Cron 2'yi elle tetikleyip yayını doğrulayın

## Notlar

- **State canlı sitede yaşar** (`docs/data/state/seen_events.json`) çünkü
  Render cron diski her çalışmada sıfırlanır. İlk çalıştırmada 404 normaldir.
- **reuters/bloomberg** Exa `includeDomains`'e eklenemez (403) — dolaylı gelir.
- **Hero videosu**: `assets/hero-loop-pingpong.mp4` (sessiz, ileri+ters
  birleştirilmiş pingpong döngü) + `assets/hero.avif/webp` (masaüstü) ve
  `assets/hero-mobile.avif/webp` (mobil) zaten hazır — değiştirmek isterseniz
  aynı dosya adlarıyla üzerine yazın.
- Ayar noktaları: hacim `config.py → AYARLAR`, kota `KATEGORILER[...]["kota"]`,
  kaynak `KAYNAK_TIER1/TIER2/TURKIYE`, sorgu `SORGULAR`.
