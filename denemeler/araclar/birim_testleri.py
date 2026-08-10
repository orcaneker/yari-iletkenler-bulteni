# -*- coding: utf-8 -*-
"""TÜM BİRİM TESTLERİNİ KOŞTUR — ağ yok, API anahtarı yok, ücret yok.

Bu klasördeki *_birim_testi.py betiklerinin tamamını ayrı süreçlerde
çalıştırır ve özet döner. Çıkış kodu: hepsi geçtiyse 0, biri bile
kaldıysa 1 — böylece bir kancaya ya da yayın öncesi denetime bağlanabilir.

⚠ Canlı testler (birlestirme_testi.py, olu_baglanti_testi.py gibi gerçek
LLM/ağ çağrısı yapanlar) BİLEREK dışarıda: onlar ücretli ve yavaş, bunlar
her değişiklikten sonra saniyeler içinde koşulmalı.

Kullanım (bu dizinden):  python birim_testleri.py
"""
import glob
import os
import subprocess
import sys

ARACLAR = os.path.dirname(os.path.abspath(__file__))
DESEN = os.path.join(ARACLAR, "*_birim_testi.py")


def main():
    betikler = sorted(glob.glob(DESEN))
    if not betikler:
        sys.exit("Birim testi bulunamadı.")

    ortam = dict(os.environ, PYTHONIOENCODING="utf-8")
    sonuclar, cikti = [], {}
    for yol in betikler:
        ad = os.path.basename(yol)
        r = subprocess.run([sys.executable, yol], cwd=ARACLAR, env=ortam,
                           capture_output=True, text=True, encoding="utf-8")
        sonuclar.append((ad, r.returncode == 0))
        cikti[ad] = (r.stdout or "") + (r.stderr or "")

    print("=" * 62)
    for ad, ok in sonuclar:
        ozet = ""
        for satir in reversed(cikti[ad].splitlines()):
            if "geçti" in satir or "GECTI" in satir:
                ozet = satir.strip()
                break
        print(f"  {'✓' if ok else '✗'} {ad:38} {ozet}")
    print("=" * 62)

    kalan = [ad for ad, ok in sonuclar if not ok]
    if kalan:
        print(f"{len(kalan)} test KALDI:\n")
        for ad in kalan:
            print(f"─── {ad} " + "─" * max(0, 50 - len(ad)))
            for satir in cikti[ad].splitlines():
                if satir.lstrip().startswith("✗") or "Error" in satir \
                        or "Traceback" in satir or "assert" in satir.lower():
                    print("   ", satir.strip())
            print()
        sys.exit(1)

    print(f"{len(sonuclar)} birim testi de geçti.")


if __name__ == "__main__":
    main()
