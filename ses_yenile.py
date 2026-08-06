# -*- coding: utf-8 -*-
"""
SESLİ ÖZETİ YENİDEN ÜRET (YARI İLETKEN) — boru hattını çalıştırmadan
==============================================================
Yayınlanmış bir sayının brief metni elle düzeltildiğinde ya da TTS
okuma kuralları değiştiğinde, tüm sistemi yeniden tetiklemeden yalnızca
mp3'ü yeniler. Exa taraması, LLM çağrısı, DB erişimi YOKTUR — sadece
docs/data/latest.json okunur ve ElevenLabs çağrılır.

Kullanım:
    python ses_yenile.py                # metni göster, ses ÜRETME (güvenli)
    python ses_yenile.py --uret         # ElevenLabs'i çağır, mp3'ü yaz
    python ses_yenile.py --uret --hafta 2026-H31

Gereken ortam değişkeni:
    ELEVENLABS_API_KEY      (zorunlu, yalnızca --uret ile)
    ELEVENLABS_VOICE_ID     (opsiyonel — verilmezse sayının kendi sesi
                             latest.json'daki issue.audio.voice'tan alınır)

PowerShell'de:
    $env:ELEVENLABS_API_KEY = "..."
    python ses_yenile.py --uret
"""
import io
import os
import sys
import json
import argparse

from config import AYARLAR
import publish as PUB

OUT = AYARLAR["cikti_dizini"]


def yaz_json(yol, veri):
    with io.open(yol, "w", encoding="utf-8", newline="\n") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uret", action="store_true",
                    help="ElevenLabs'i gerçekten çağır (ücretli)")
    ap.add_argument("--hafta", default=None,
                    help="arşivden bir sayı (ör. 2026-H31); yoksa latest")
    args = ap.parse_args()

    yol = (f"{OUT}/data/arsiv/{args.hafta}.json" if args.hafta
           else f"{OUT}/data/latest.json")
    if not os.path.exists(yol):
        sys.exit(f"HATA: {yol} yok")
    bulten = json.load(io.open(yol, encoding="utf-8"))
    hafta = bulten["issue"]["hafta"]

    metin = PUB.ses_metni(bulten)
    print("=" * 66)
    print(f"SESLENDİRİLECEK METİN — {hafta} · {len(metin)} karakter")
    print("=" * 66)
    print(metin)
    print("=" * 66)

    if not args.uret:
        print("\nSes ÜRETİLMEDİ (kuru çalışma). Gerçekten üretmek için:")
        print("    python ses_yenile.py --uret")
        return

    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("HATA: ELEVENLABS_API_KEY tanımlı değil.\n"
                 '  PowerShell:  $env:ELEVENLABS_API_KEY = "..."')

    # Sayının kendi sesini koru — env verilmemişse mevcut kayıttan al
    onceki = (bulten["issue"].get("audio") or {}).get("voice")
    if not os.environ.get("ELEVENLABS_VOICE_ID") and onceki:
        PUB.ELEVENLABS_VOICE_ID = onceki
        print(f"Ses kimliği önceki üretimden alındı: {onceki}")

    eski_mp3 = f"{OUT}/assets/audio/{hafta}.mp3"
    yedek = eski_mp3 + ".onceki"
    if os.path.exists(eski_mp3):
        if os.path.exists(yedek):
            os.remove(yedek)
        os.rename(eski_mp3, yedek)
        print(f"Önceki ses yedeklendi: {yedek}")

    if not PUB.ses_uret(bulten):
        if os.path.exists(yedek):        # başarısızsa eskiyi geri koy
            os.rename(yedek, eski_mp3)
            print("Üretim başarısız — önceki ses geri alındı.")
        sys.exit("HATA: ses üretilemedi (log yukarıda).")

    # issue.audio hem latest hem arşiv kopyasında güncellenmeli
    for hedef in {yol, f"{OUT}/data/latest.json", f"{OUT}/data/arsiv/{hafta}.json"}:
        if not os.path.exists(hedef):
            continue
        v = json.load(io.open(hedef, encoding="utf-8"))
        if v.get("issue", {}).get("hafta") != hafta:
            continue
        v["issue"]["audio"] = bulten["issue"]["audio"]
        yaz_json(hedef, v)
        print(f"  güncellendi: {hedef}")

    print(f"\nTamam. {os.path.getsize(eski_mp3)//1024} KB · "
          f"~{bulten['issue']['audio']['duration_sec']} sn")
    print("Beğenmezseniz eski dosya duruyor:", yedek)


if __name__ == "__main__":
    main()
