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

```bash
python denemeler/araclar/yazim_denetimi_testi.py
```

Model denemek için (Exa araması ve triyaj tekrar çalışmaz):

```bash
python yeniden_yaz.py --girdi kiyas/taslak.json --model openai:gpt-5.6-terra --effort high --cikti kiyas/deneme
```
