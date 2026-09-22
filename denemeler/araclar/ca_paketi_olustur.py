# -*- coding: utf-8 -*-
"""
YEREL CA PAKETİ ÜRETİCİ — "CERTIFICATE_VERIFY_FAILED" çözümü
==================================================================
BELİRTİ:
    SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]
    unable to get local issuer certificate'))
  · Tarayıcıda aynı adres sorunsuz açılıyor
  · Bazen çalışıp bazen patlıyor (VPN / ağ değişince)

SEBEP:
    Kurum güvenlik duvarı ya da antivirüs "HTTPS taraması" yapıyor: trafiği
    çözüp KENDİ kök sertifikasıyla yeniden imzalıyor. O kök Windows sertifika
    deposunda var — tarayıcı bu yüzden şikâyet etmiyor — ama Python'un certifi
    paketinde YOK.

ÇÖZÜM:
    certifi paketi + Windows'un güvendiği kökler birleştirilip repo köküne
    ca-bundle.local.pem olarak yazılır. config.py bu dosya varsa
    REQUESTS_CA_BUNDLE'ı ona ayarlar (dosya .gitignore'da; Render'da
    bulunmadığı için üretim davranışı değişmez).

⚠ DOĞRULAMA KAPATILMIYOR. Sadece güvenilen kök listesi, işletim sisteminin
  zaten güvendiği köklerle genişletiliyor. `verify=False` ASLA kullanılmaz —
  o, araya girme saldırısına kapı açar.

Kullanım:
    python denemeler/araclar/ca_paketi_olustur.py
    python denemeler/araclar/ca_paketi_olustur.py --sil     # geri al
"""

import os
import ssl
import sys
import argparse

KOK = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HEDEF = os.path.join(KOK, "ca-bundle.local.pem")

# Sunucu kimliği doğrulaması amacı — yalnızca bu amaca güvenilen kökleri al.
SUNUCU_KIMLIGI = "1.3.6.1.5.5.7.3.1"


def windows_kokleri():
    """Windows sertifika deposundaki güvenilir kökler (ROOT + CA)."""
    if not hasattr(ssl, "enum_certificates"):
        sys.exit("Bu araç yalnızca Windows'ta çalışır (ssl.enum_certificates yok).")
    pemler, atlanan = [], 0
    for magaza in ("ROOT", "CA"):
        try:
            kayitlar = ssl.enum_certificates(magaza)
        except Exception as e:
            print(f"  ! {magaza} deposu okunamadı: {e}")
            continue
        for der, kodlama, guven in kayitlar:
            if kodlama != "x509_asn":
                continue
            # guven: True (her amaç) veya amaç OID'lerinden oluşan küme
            if guven is not True and SUNUCU_KIMLIGI not in (guven or ()):
                atlanan += 1
                continue
            try:
                pemler.append(ssl.DER_cert_to_PEM_cert(der))
            except Exception:
                atlanan += 1
        print(f"  {magaza} deposu: {len(kayitlar)} kayıt")
    return pemler, atlanan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sil", action="store_true", help="paketi kaldır")
    args = ap.parse_args()

    if args.sil:
        if os.path.exists(HEDEF):
            os.remove(HEDEF)
            print(f"Silindi: {HEDEF}")
            print("Artık Python yalnızca certifi köklerini kullanacak.")
        else:
            print("Zaten yok.")
        return

    try:
        import certifi
    except ImportError:
        sys.exit("certifi bulunamadı — 'pip install certifi' (requests ile gelir).")

    print("Kaynaklar okunuyor…")
    print(f"  certifi: {certifi.where()}")
    with open(certifi.where(), encoding="utf-8") as f:
        temel = f.read()

    pemler, atlanan = windows_kokleri()
    print(f"  Windows'tan alınan kök: {len(pemler)} (atlanan {atlanan})")

    govde = (temel.rstrip() + "\n\n"
             + "# ── Windows sertifika deposundan eklenenler ──\n"
             + "".join(pemler))

    # ⚠ Yazmadan ÖNCE doğrula: bozuk bir paket TÜM HTTPS çağrılarını
    # (Exa, Resend, GitHub dahil) kırar. Geçici dosyada sına, sonra taşı.
    gecici = HEDEF + ".deneme"
    with open(gecici, "w", encoding="utf-8") as f:
        f.write(govde)
    try:
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(gecici)
    except Exception as e:
        os.remove(gecici)
        sys.exit(f"Üretilen paket geçersiz, yazılmadı: {e}")
    sayi = len(ctx.get_ca_certs())
    os.replace(gecici, HEDEF)

    print(f"\nYazıldı: {HEDEF}")
    print(f"  toplam {sayi} kök sertifika yüklenebiliyor")
    print("  (.gitignore'da — git'e girmez, Render'a gitmez)")
    print("\nŞimdi testi tekrar çalıştırın:")
    print("  python denemeler\\araclar\\openrouter_testi.py --hizli")
    print("\nSorun sürerse ağ/VPN durumunu değiştirip tekrar deneyin;")
    print("kurum vekil sunucusu ayrıca kimlik doğrulama istiyor olabilir.")


if __name__ == "__main__":
    main()
