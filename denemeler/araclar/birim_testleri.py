# -*- coding: utf-8 -*-
"""TÜM ÇEVRİMDIŞI TESTLERİ KOŞTUR — ağ yok, API anahtarı yok, ücret yok.

Bu klasördeki *_testi.py betiklerinin tamamını ayrı süreçlerde çalıştırır
ve özet döner. Çıkış kodu: hepsi geçtiyse 0, biri bile kaldıysa 1 — böylece
bir kancaya ya da yayın öncesi denetime bağlanabilir.

⚠ CANLI testler açık listeyle dışarıda tutulur (aşağıdaki CANLI kümesi).
Adlandırmaya güvenilmez: `olu_baglanti_testi.py`, `supheli_testi.py` ve
`yazim_denetimi_testi.py` "birim" eki taşımadıkları hâlde ÇEVRİMDIŞIDIR —
sahte yanıt nesneleri kullanır, iddia üretir, çıkış kodu döner. Bir dönem
bu betikler yalnızca ada bakıldığı için koşulmuyordu. Yeni bir test
eklerken: gerçek ağ/LLM çağrısı yapıyorsa CANLI'ya ekle, yapmıyorsa
hiçbir şey yapma — kendiliğinden koşulur.

Kullanım (bu dizinden):  python birim_testleri.py
"""
import glob
import os
import subprocess
import sys

ARACLAR = os.path.dirname(os.path.abspath(__file__))
DESEN = os.path.join(ARACLAR, "*_testi.py")

# Gerçek LLM / ağ çağrısı yapanlar — ücretli ve yavaş, elle koşulur.
CANLI = {
    "birlestirme_testi.py",      # gerçek sayı verisiyle gerçek LLM çağrısı
}


def main():
    betikler = sorted(y for y in glob.glob(DESEN)
                      if os.path.basename(y) not in CANLI)
    if not betikler:
        sys.exit("Çevrimdışı test bulunamadı.")

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

    print(f"{len(sonuclar)} çevrimdışı test de geçti.")


if __name__ == "__main__":
    main()
