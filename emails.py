# -*- coding: utf-8 -*-
"""
YARI İLETKEN BÜLTENİ — E-POSTALAR (Resend)
=============================================
Dört e-posta türü:
  davet       → taslak hazır, hakemlere inceleme linki (pipeline.py)
  hatirlatma  → Pazartesi 08:00'de onay yoksa (publish.py)
  yayinlandi  → bülten yayına girince hakemlere bilgi
  rapor       → çalışma raporu (sadece RAPOR_ALICI'ya)

Resend ücretsiz katmanda doğrulanmamış alan adıyla gönderim
'onboarding@resend.dev' üzerinden yapılır; kendi alan adı doğrulanınca
MAIL_FROM değiştirilir.
"""

import os
import requests

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "Yarı İletken Bülteni <onboarding@resend.dev>")
RESEND_URL = "https://api.resend.com/emails"

# Site tasarımıyla uyumlu minimal e-posta stili
_STIL = """
  body{font-family:Georgia,'Times New Roman',serif;background:#F7F5F0;color:#0B2239;
       margin:0;padding:24px}
  .kutu{max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid #D8D3C8;
        border-top:3px solid #B5651D;padding:32px}
  .ust{font-family:'Courier New',monospace;font-size:11px;letter-spacing:.12em;
       text-transform:uppercase;color:#B5651D;margin-bottom:16px}
  h1{font-size:22px;line-height:1.25;margin:0 0 14px}
  p{font-size:15px;line-height:1.6;margin:0 0 14px}
  .btn{display:inline-block;background:#0B2239;color:#FFFFFF !important;
       text-decoration:none;padding:12px 24px;font-size:15px;margin:8px 0 16px}
  .kucuk{font-size:12px;color:#6B7280;border-top:1px solid #E5E1D8;
         padding-top:14px;margin-top:20px}
"""


def _gonder(alicilar, konu, html, metin=None):
    """Resend ile gönder. Hata olursa False döner — akışı durdurmaz."""
    if not RESEND_API_KEY:
        print("  E-posta atlandı (RESEND_API_KEY yok)")
        return False
    if isinstance(alicilar, str):
        alicilar = [alicilar]
    try:
        r = requests.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                     "Content-Type": "application/json"},
            json={"from": MAIL_FROM, "to": alicilar, "subject": konu,
                  "html": html, **({"text": metin} if metin else {})},
            timeout=30,
        )
        if r.status_code in (200, 201):
            return True
        print(f"  Resend {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  Resend hatası: {e}")
    return False


def _sablon(ust, baslik, govde_html):
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{_STIL}</style></head><body><div class='kutu'>"
            f"<div class='ust'>{ust}</div><h1>{baslik}</h1>{govde_html}"
            f"<div class='kucuk'>Yarı İletken Bülteni — otomatik bildirim. "
            f"Bu e-postadaki inceleme linki kişiseldir, paylaşmayın.</div>"
            f"</div></body></html>")


def davet_gonder(hakem, link, sayi_no, hafta, lead_baslik, haber_sayisi):
    """Taslak hazır → hakeme inceleme daveti."""
    html = _sablon(
        f"Sayı {sayi_no} · {hafta} · TASLAK",
        "Bülten taslağı incelemenizi bekliyor",
        f"<p>Merhaba {hakem['ad']},</p>"
        f"<p>Bu haftanın yarı iletken bülteni taslağı hazırlandı: "
        f"<b>{haber_sayisi} haber</b> seçildi. Manşet adayı:</p>"
        f"<p><i>&ldquo;{lead_baslik}&rdquo;</i></p>"
        f"<p>Haberleri inceleyebilir, beğenmediklerinizi yedek havuzundaki "
        f"haberlerle değiştirebilir ve bülteni onaylayabilirsiniz. "
        f"Yayın <b>Pazartesi 08:00</b>'de yapılır; onay gelmezse bülten "
        f"yayınlanmaz.</p>"
        f"<a class='btn' href='{link}'>Taslağı İncele</a>",
    )
    return _gonder(hakem["email"], f"[İnceleme] Yarı İletken Bülteni — Sayı {sayi_no} taslağı hazır", html)


def hatirlatma_gonder(hakem, link, sayi_no, hafta):
    """Pazartesi 08:00 geçti, onay yok → hatırlatma."""
    html = _sablon(
        f"Sayı {sayi_no} · {hafta} · ONAY BEKLİYOR",
        "Bülten onay bekliyor — yayın gecikiyor",
        f"<p>Merhaba {hakem['ad']},</p>"
        f"<p>Yayın saati (Pazartesi 08:00) geçti ancak bülten henüz "
        f"onaylanmadı. Onay verdiğiniz anda bülten otomatik yayınlanacak.</p>"
        f"<a class='btn' href='{link}'>İncele ve Onayla</a>",
    )
    return _gonder(hakem["email"], f"[Hatırlatma] Sayı {sayi_no} onay bekliyor", html)


def yayinlandi_gonder(alicilar, sayi_no, hafta, site_url, onaylayan):
    html = _sablon(
        f"Sayı {sayi_no} · {hafta} · YAYINDA",
        "Bülten yayınlandı",
        f"<p>Sayı {sayi_no} ({onaylayan} onayıyla) yayına alındı.</p>"
        f"<a class='btn' href='{site_url}'>Bülteni Görüntüle</a>",
    )
    return _gonder(alicilar, f"Yarı İletken Bülteni — Sayı {sayi_no} yayında", html)


def rapor_gonder(alici, konu, duz_metin):
    """Çalışma raporu — düz metin (log ağırlıklı)."""
    html = (f"<!doctype html><html><head><meta charset='utf-8'></head>"
            f"<body><pre style='font-family:monospace;font-size:12px;"
            f"white-space:pre-wrap'>{duz_metin}</pre></body></html>")
    return _gonder(alici, konu, html, metin=duz_metin)


# ============================================================
# CLI — E-POSTA AYARI TESTİ
# ============================================================
# Exa/LLM çalıştırmadan (yani maliyetsiz) gönderim ayarını doğrular.
# Alan adı doğrulanmadan MAIL_FROM 'onboarding@resend.dev' kalırsa Resend
# yalnızca hesap sahibine gönderir; diğer hakemler sessizce düşer. Bu test
# tam olarak o durumu Pazar'ı beklemeden ortaya çıkarır.
#
#   python emails.py --test                 # DB'deki TÜM hakemlere
#   python emails.py --test mail@ornek.com  # tek adrese
# ============================================================
def test_gonder(alici):
    """Tek adrese deneme e-postası. Dönen: True/False."""
    html = _sablon(
        "SİSTEM TESTİ",
        "E-posta ayarı çalışıyor",
        "<p>Bu bir <b>deneme</b> e-postasıdır — bülten taslağı değildir.</p>"
        "<p>Bu mesajı aldıysanız, haftalık bülten davetleri de size "
        "ulaşacak demektir. Bir şey yapmanıza gerek yok.</p>"
        f"<p style='font-size:12px;color:#6B7280'>Gönderen: {MAIL_FROM}</p>",
    )
    return _gonder(alici, "[TEST] Yarı İletken Bülteni — e-posta ayarı denemesi", html)


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if not args or args[0] != "--test":
        print(__doc__)
        sys.exit("Kullanım: python emails.py --test [mail@ornek.com]")

    print(f"MAIL_FROM   : {MAIL_FROM}")
    print(f"RESEND_API_KEY: {'tanımlı' if RESEND_API_KEY else 'YOK — gönderim yapılamaz'}")
    if "onboarding@resend.dev" in MAIL_FROM:
        print("⚠ UYARI: MAIL_FROM hâlâ Resend'in paylaşımlı test adresi.\n"
              "  Bu adresle SADECE hesap sahibinin kendi e-postasına gönderim yapılır;\n"
              "  diğer hakemler davet ALAMAZ. Render'da MAIL_FROM'u kendi doğrulanmış\n"
              "  alan adınızla değiştirin.")
    print("-" * 52)

    if len(args) > 1:
        alicilar = args[1:]
    else:
        import db
        alicilar = [h["email"] for h in db.hakemler()]
        if not alicilar:
            sys.exit("Kayıtlı hakem yok (python db.py --seed ... ile ekleyin)")

    basarili = 0
    for a in alicilar:
        ok = test_gonder(a)
        print(f"  {'✓ gönderildi' if ok else '✗ BAŞARISIZ  '} → {a}")
        basarili += bool(ok)

    print("-" * 52)
    print(f"{basarili}/{len(alicilar)} gönderim kabul edildi.")
    print("Not: 'gönderildi' = Resend isteği kabul etti. Kutuya DÜŞTÜĞÜNÜ\n"
          "     resend.com → Emails ekranından (delivered/bounced) doğrulayın.")
