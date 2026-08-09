# -*- coding: utf-8 -*-
"""json_ayikla kontrol-karakter onarımı + yazim_eksik denetimi."""
import json
import os
import sys

from yollar import KOK, veri  # noqa: F401  (repo kokunu sys.path'e ekler)
import pipeline as p  # noqa: E402

hata = 0


def kontrol(ad, kosul):
    global hata
    hata += not kosul
    print(f"  {'✓' if kosul else '✗'} {ad}")


print("json_ayikla — kaçışsız kontrol karakteri:")
# Sonnet'in ürettiği tipik bozukluk: dize İÇİNDE ham satır başı
bozuk = '{"stories":[{"id":"a","detail":"Birinci paragraf.\nİkinci paragraf."}]}'
try:
    json.loads(bozuk)
    kontrol("ham JSON gerçekten bozuk (ön koşul)", False)
except json.JSONDecodeError:
    kontrol("ham JSON gerçekten bozuk (ön koşul)", True)

d = p.json_ayikla(bozuk)
kontrol("onarıldı ve TÜM kayıt korundu", len(d["stories"]) == 1)
kontrol("metin kayıpsız", d["stories"][0]["detail"] == "Birinci paragraf.\nİkinci paragraf.")

# Dize DIŞINDAKİ satır başları bozulmamalı
temiz = '{\n  "a": 1,\n  "b": "iki"\n}'
kontrol("geçerli JSON aynen ayrıştırılıyor", p.json_ayikla(temiz) == {"a": 1, "b": "iki"})

# Kaçışlanmış tırnak dize sınırını bozmamalı
kacisli = '{"t":"o \\"dedi\\" ve\nsonra gitti"}'
kontrol("kaçışlı tırnak doğru işleniyor",
        p.json_ayikla(kacisli)["t"] == 'o "dedi" ve\nsonra gitti')

print("\nyazim_eksik — tamlık denetimi:")
derin = [{"event_key": f"o{i}"} for i in range(14)]
radar = [{"event_key": f"r{i}"} for i in range(26)]
tam = {"stories": [{"id": f"o{i}", "title": "x"} for i in range(14)],
       "radar": [{"kume": "k", "maddeler": [{"url": "u"}]}]}

kontrol("tam çıktı temiz geçiyor", p.yazim_eksik(tam, derin, radar) is None)

az = {"stories": tam["stories"][:5], "radar": tam["radar"]}
kontrol("14 olaya 5 haber → yakalanıyor",
        "yalnızca 5 haber" in (p.yazim_eksik(az, derin, radar) or ""))

yt = {"stories": tam["stories"][:12] + [{"id": "__PLACEHOLDER_NOT_USED__"}],
      "radar": tam["radar"]}
kontrol("yer tutucu → yakalanıyor",
        "yer tutucu" in (p.yazim_eksik(yt, derin, radar) or ""))

bos_radar = {"stories": tam["stories"], "radar": []}
kontrol("radar havuzu dolu ama radar boş → yakalanıyor",
        "radar boş" in (p.yazim_eksik(bos_radar, derin, radar) or ""))

kontrol("radar adayı yoksa boş radar sorun değil",
        p.yazim_eksik(bos_radar, derin, []) is None)

print(f"\n{'TÜMÜ GEÇTİ' if not hata else str(hata) + ' TEST BAŞARISIZ'}")
sys.exit(1 if hata else 0)
