# Yarı İletken Bülteni

Haftalık otomatik yarı iletken sektörü ve sanayi politikası izleme bülteni.
`Exa → Claude (2 aşama) → JSON → statik site`

## Dosyalar

```
config.py        Sorgular (12), kategori taksonomisi (12), kaynak katmanları, ayarlar
prompts.py       LLM promptları — Aşama 1 (triyaj) + Aşama 2 (yazım)
main.py          Pipeline
site/index.html  Bülten
site/arsiv.html  Arşiv
demo/            Örnek veriyle çalışan önizleme (gerçek haber içermez)
```

## Kurulum

```bash
pip install -r requirements.txt
```

Ortam değişkenleri (Render → Environment):

| Anahtar | Zorunlu | Not |
|---|---|---|
| `EXA_API_KEY` | ✅ | exa.ai → Dashboard |
| `ANTHROPIC_API_KEY` | ✅ | |
| `GITHUB_REPO` | ✅ | `kullanici/repo-adi` |
| `GITHUB_TOKEN` | ✅ | GitHub PAT — Contents: Read & Write |
| `GITHUB_BRANCH` | — | varsayılan `main` |
| `SMTP_USER`, `SMTP_PASS`, `RAPOR_ALICI` | — | Haftalık çalışma raporu e-postası |

`config.py → AYARLAR["site_url"]` değerini deploy ettiğiniz adrese göre **mutlaka güncelleyin.**
Durum dosyası (`seen_events.json`) bu adresten okunuyor.

## Çalıştırma

```bash
python main.py --dry-run    # deploy ve e-posta yok, sadece dist/ üretir
python main.py              # tam akış
```

Render cron: `0 5 * * 1` (UTC 05:00 = TSİ 08:00, pazartesi)

## Önizleme (API'siz)

```bash
cd demo && python3 -m http.server 8080
```
`demo/data/latest.json` içeriği **örnek/yer tutucudur, gerçek haber değildir.**

---

## ⚠ Kritik: Render diski geçicidir

Render cron job her çalışmada temiz diskle başlar. Bu yüzden **"görülmüş olaylar" hafızası
diskte tutulamaz.** Çözüm: state, deploy edilen sitenin içinde yaşar.

```
main.py başlarken  →  GET {site_url}/data/state/seen_events.json
main.py biterken   →  güncel state'i dist/ içine yazar, deploy'a dahil eder
```

Bu sayede 2. hafta 1. haftanın haberlerini tekrar yayımlamaz. **İlk çalıştırmada
404 alması normaldir** — sıfırdan başlar.

---

## Barındırma — Cloudflare Pages

Render `dist/` klasörünü GitHub'a push eder → Cloudflare Pages push'u görüp
otomatik yayınlar. Netlify'a ihtiyaç yok.

- Cloudflare Pages ayarı: Build command **boş**, Output directory **`dist`**
- Adres: `<proje>.pages.dev`

### Alan adı
Blok `netlify.app` / `pages.dev` gibi **paylaşımlı** alan adlarında oluşuyor —
içerikte değil. Kendi alan adınız (~15 $/yıl) bu sorun sınıfını tamamen bitirir.

---

## v2 kancaları (bugün hazır, sonra açılacak)

| Özellik | Nasıl açılır |
|---|---|
| **Editoryal analiz** ("Neden önemli?") | `prompts.py` → `neden_onemli: null` talimatını kaldır · `main.py → dogrula()` içindeki `s["neden_onemli"]=None` satırını sil. Site zaten `.why.on` ile render ediyor. |
| **Sesli bülten** (ElevenLabs) | Pipeline sonunda `brief` metnini TTS'e gönder → `dist/assets/audio/{hafta}.mp3` · `issue.audio = {"url": "...", "duration_sec": N}`. Site oynatıcıyı otomatik gösterir. |
| **Hero videosu** (Higgsfield vb.) | `assets/video/hero.webm` + `hero.mp4` + `hero.jpg` ekle · `index.html` sonundaki yorumlu CSS bloğunu aç · masthead altına `<div class="hero-media">` koy. **Çalışma zamanı bağımlılığı yok — statik dosya.** Hedef: ≤1.5 MB, 6-8 sn, sessiz, mobilde kapalı. |
| **Perplexity katmanı** | Kredi geldiğinde: `turkiye` sorgusu için yedek arama katmanı. Exa'nın TR/İngilizce-dışı indeksi zayıf. |

## Ayar noktaları

- Hacim: `config.py → AYARLAR` (`one_cikan_max`, `radar_max`)
- Kategori kotası: `config.py → KATEGORILER[...]["kota"]` + `prompts.py → YAZIM_PROMPT`
- Kaynak ekleme: `config.py → KAYNAK_TIER1/TIER2/TURKIYE`
- Yeni sorgu: `config.py → SORGULAR` listesine ekle
