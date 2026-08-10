# denemeler/

Ölçüm araçları. Model/prompt değişikliklerinin etkisini rakamla görmek için.

Bu iyileştirmeler önce **biyoekonomi bülteninde** geliştirilip ölçüldü, sonra
buraya taşındı. Kararın gerekçesi ve ham ölçümler orada:
`biyoekonomi-bulteni/denemeler/model-kiyasi-2026-08/README.md`

Özeti: Sonnet 5 ↔ GPT-5.6 Terra kıyaslandı, **Sonnet 5'te kalındı**. Terra
ucuz ve eksiksiz ama aynı bilgiyi çok daha fazla ve kısa cümleye bölüyor;
Türkçede tekdüze bir tempo çıkıyor. Deneme üç kalıcı iyileştirme üretti ve
üçü de bu repoya uygulandı:

1. **Türkçeleştirme kuralları** (`prompts.py`) — sayı biçimi, para birimi,
   ay adı, kurum adı, yer adlarının çevrilmemesi, birim sözlüğü, markdown
   yasağı. Ölçülen etki: 126 → 0 ihlal.
2. **Tamlık denetimi** (`pipeline.py` → `yazim_eksik`) — model haberlerin
   bir kısmını yazmayı atlarsa yeniden dener, düzelmezse raporun başına
   kırmızı bayrak koyar.
3. **JSON kontrol karakteri onarımı** (`pipeline.py` → `_kontrol_kacir`) —
   kayıplı `json_repair` kurtarmasına düşmeden önce deterministik onarım.

Ayrıca mükerrer olay birleştirmesindeki eşik kapısı kaldırıldı, görsel
seçimi logo/stok görsellerini geri plana atıyor ve inceleme sayfasında
görseller görünüyor (değiştir/kaldır düğmeleriyle).

## araclar/

Repo kökünden çalıştırılır:

| betik | ne ölçer |
|---|---|
| `dil_denetimi.py` | Türkçeleştirme ihlalleri (İngilizce ay adı, `$1.52`, `700,000`, markdown…) |
| `uslup_denetimi.py` | akıcılık: cümle uzunluğu çeşitliliği, ardışık "-yor", dolgu cümlesi |
| `yazim_denetimi_testi.py` | `json_ayikla` onarımı + `yazim_eksik` tamlık denetimi |
| `supheli_testi.py` | `gorsel_supheli()` — logo/stok görseli ayırt ediyor mu |
| `olu_baglanti_testi.py` | `_olu_baglanti()` — ölü bağlantıyı bot engelinden ayırt ediyor mu (çevrimdışı) |

```bash
python denemeler/araclar/yazim_denetimi_testi.py
```

Model denemek için (Exa araması ve triyaj tekrar çalışmaz):

```bash
python yeniden_yaz.py --girdi kiyas/taslak.json --model openai:gpt-5.6-terra --effort high --cikti kiyas/deneme
```

## Çevrimdışı testler

Aşağıdaki betikler **ağ, API anahtarı ve ücret gerektirmez** — ağ
çağrıları taklit edilir. İddia üretir ve çıkış kodu dönerler, dolayısıyla
her kod değişikliğinden sonra saniyeler içinde koşulabilirler.

Hepsini birden koşturmak için:

    cd denemeler/araclar
    python birim_testleri.py

| betik | neyi doğrular | iddia |
|---|---|---|
| `birlestirme_birim_testi.py` | üç katmanlı mükerrer birleştirmenin karar mantığı; sayı parmak izi, ortak sinyal emniyeti, grup boyutu sınırı | 38 |
| `govde_metni_birim_testi.py` | `_govde_metni()` çıkarımı; script/menü/footer sızdırmıyor, zengin metni bozmuyor | 16 |
| `tarih_okuma_birim_testi.py` | `_tarih_ayikla()` katman sırası; görünür tarih okunuyor, "ilgili haberler" tarihine atlanmıyor | 11 |
| `gorsel_denetim_birim_testi.py` | `gorsel_erisilebilir()`; hotlink engelli görsel elenip sıradaki adaya düşülüyor | 10 |
| `kaynak_sabitleme_birim_testi.py` | `kaynaklari_sabitle()`; yanlış URL düzeltiliyor, kaynaksız haber yayına girmiyor | 6 |
| `tarih_raporu_birim_testi.py` | tarihi doğrulanamayan haber sayacı; elenmiyor ama raporda görünüyor | 6 |
| `olu_baglanti_testi.py` | `_olu_baglanti()`; 404/410 ölü sayılıyor, 403/503 bot engeli ölü SAYILMIYOR | 9 |
| `supheli_testi.py` | `gorsel_supheli()`; logo ve stok görseli geri plana atılıyor | 8 |
| `yazim_denetimi_testi.py` | `json_ayikla` kontrol-karakter onarımı + `yazim_eksik` tamlık denetimi | 10 |

⚠ Adlandırmaya güvenilmez: `olu_baglanti_testi.py`, `supheli_testi.py` ve
`yazim_denetimi_testi.py` "birim" eki taşımadıkları hâlde ÇEVRİMDIŞIDIR —
sahte yanıt nesneleri kullanır, iddia üretir, çıkış kodu döner. Bir dönem
yalnızca ada bakıldığı için bunlar hiç koşulmuyordu; artık koşuluyorlar.

CANLI test, `birim_testleri.py` içindeki açık listeyle dışarıda tutulur.
Şu an tek canlı betik `birlestirme_testi.py` (gerçek sayı verisiyle gerçek
LLM çağrısı — ücretli, sonucunu insan okur). Yeni test eklerken: gerçek
ağ/LLM çağrısı yapıyorsa o listeye ekleyin, yapmıyorsa bir şey yapmanız
gerekmez, kendiliğinden koşulur.
