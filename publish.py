# -*- coding: utf-8 -*-
"""
YARI İLETKEN BÜLTENİ — YAYIN (CRON 2 — Pazartesi 08:00 TSİ)
==============================================================
Akış:
  · Neon'dan bekleyen sayıyı oku (approved > review önceliğiyle)
  · status=approved → nihai bülteni kur (hakem takasları uygulanmış) →
    arşiv + state + RSS + ElevenLabs sesli özet → docs/ → GitHub push
    → status=published → "yayınlandı" e-postası + çalışma raporu
  · status=review   → hakemlere HATIRLATMA e-postası; yayın YAPILMAZ.
    (Onay sonradan gelirse review_app bu modüldeki yayinla()'yı çağırır.)

Çalıştırma:
  python publish.py                 # tam akış (cron bunu çağırır)
  python publish.py --dry-run       # push/e-posta/DB değişikliği yok, docs/ üretir
  python publish.py --local-draft   # DB yerine taslak_preview.json (çevrimdışı test)
"""

import os
import re
import sys
import json
import time
import argparse
from datetime import datetime, timezone

import requests

from config import AYARLAR, KATEGORILER
from pipeline import url_normalize, iso_hafta, log, LOG

OUT = AYARLAR["cikti_dizini"]
SITE_URL = AYARLAR["site_url"].rstrip("/")

GITHUB_REPO = os.environ.get("GITHUB_REPO", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")

REVIEW_BASE_URL = os.environ.get("REVIEW_BASE_URL", "").rstrip("/")
RAPOR_ALICI = os.environ.get("RAPOR_ALICI", "")


# ============================================================
# NİHAİ BÜLTEN KURULUMU — taslak + hakem kararları → yayın JSON'u
# ============================================================
def nihai_kur(taslak):
    """secim=one_cikan haberlerden nihai bülteni kur.
    Metrikler burada, NİHAİ seçim üzerinden deterministik hesaplanır."""
    stories = taslak.get("stories") or []
    secili = [s for s in stories if s.get("secim") == "one_cikan"]
    lead = next((s for s in secili if s.get("id") == taslak.get("lead_id")), None)
    if not lead and secili:
        lead = max(secili, key=lambda s: s.get("score") or 0)
    digerleri = [s for s in secili if s is not lead]

    # brief ref (story id) → slug; çıkarılan habere işaret ediyorsa null
    id2slug = {s.get("id"): s.get("slug") for s in secili}
    brief = [{"text": m.get("text", ""), "slug": id2slug.get(m.get("ref"))}
             for m in (taslak.get("brief") or [])]

    # --- metrikler ---
    # ⚠ Yarı iletkende kapasite birimleri heterojendir (wafer/ay, çip/yıl,
    # MW...) — toplanamaz. Bu yüzden "capacity" serbest dizedir ve metrikte
    # toplanmaz; sadece proje sayısı ile yatırım/ülke toplanır.
    yatirim = 0
    ulkeler = set()
    for s in secili:
        inv = (s.get("investment") or {}).get("amount_usd_million")
        if isinstance(inv, (int, float)):
            yatirim += inv
        ulkeler.update(s.get("countries") or [])

    bugun = datetime.now(timezone.utc)
    i = taslak.get("issue", {})
    return {
        "issue": {
            "number": i.get("number"),
            "hafta": i.get("hafta"),
            "publication_date": bugun.strftime("%Y-%m-%d"),
            "coverage_start": i.get("coverage_start"),
            "coverage_end": i.get("coverage_end"),
            "window_days": i.get("window_days"),
            "audio": None,     # ← ses üretilirse doldurulur
        },
        "brief": brief,
        "metrics": {
            "aciklanan_yatirim_usd_milyon": round(yatirim) or None,
            "proje_sayisi": len(secili) or None,
            "politika_gelismesi": sum(
                1 for s in secili if s.get("category") == "politika") or None,
            "kapsanan_ulke": len(ulkeler) or None,
        },
        "lead": lead,
        "stories": digerleri,
        "radar": taslak.get("radar") or [],
    }


# ============================================================
# SESLİ BÜLTEN — "Bu Hafta 60 Saniyede" (ElevenLabs)
# ============================================================
AY_TR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
         "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
SIRA = ["Bir", "İki", "Üç", "Dört", "Beş", "Altı", "Yedi"]

# TTS birim/kısaltma açılımları — seslendirici "GW", "TWh" gibi birimleri
# telaffuz edemiyor; ses metninde açık yazılır. Uzun birimler önce
# (TWh, GW'den önce eşleşmeli). Sadece SES metnini etkiler, bülteni değil.
_BIRLER = ("", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz")
_ONLAR = ("", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş",
          "seksen", "doksan")
_BASAMAK = ("", " bin", " milyon", " milyar", " trilyon")


def _uc_hane(n):
    p = []
    yuz, kalan = divmod(n, 100)
    if yuz:
        p.append("yüz" if yuz == 1 else _BIRLER[yuz] + " yüz")
    on, bir = divmod(kalan, 10)
    if on:
        p.append(_ONLAR[on])
    if bir:
        p.append(_BIRLER[bir])
    return " ".join(p)


def sayi_yaziyla(n):
    """1223 → "bin iki yüz yirmi üç". Seslendirici dört ve daha çok haneli
    sayıları ondalık gibi ya da rakam rakam okuyor; ses metninde yazıya
    çeviriyoruz. Bülten metnine dokunulmaz, orada rakam kalır."""
    if n == 0:
        return "sıfır"
    if n >= 1000 ** len(_BASAMAK):
        return str(n)                    # okunamayacak kadar büyük — dokunma
    gruplar = []
    while n:
        n, g = divmod(n, 1000)
        gruplar.append(g)
    parcalar = []
    for i in range(len(gruplar) - 1, -1, -1):
        if not gruplar[i]:
            continue
        if i == 1 and gruplar[i] == 1:   # "bin", "bir bin" değil
            parcalar.append("bin")
        else:
            parcalar.append(_uc_hane(gruplar[i]) + _BASAMAK[i])
    return " ".join(parcalar)


_OLCEK = {"bin": 1000, "milyon": 10 ** 6, "milyar": 10 ** 9, "trilyon": 10 ** 12}


def _yaziya(m):
    return sayi_yaziyla(int(m.group(0).replace(".", "")))


def _olcekli_ondalik(m):
    """"19,1 milyon" → "on dokuz milyon yüz bin". Virgül seslendiricinin en
    çok takıldığı işaret; büyüklük sözcüğü varsa ondalığı hiç okutmuyoruz."""
    tam, kesir, olcek = m.group(1).replace(".", ""), m.group(2), m.group(3)
    carpan = _OLCEK[olcek]
    return sayi_yaziyla(int(tam) * carpan + int(kesir) * carpan // 10 ** len(kesir))


def _ondalik(m):
    """Büyüklük sözcüğü olmayan ondalık: "3,5 puan" → "üç virgül beş puan"."""
    kesir = m.group(2)
    if kesir.startswith("0"):            # "3,05" → "üç virgül sıfır beş"
        okunan = " ".join(sayi_yaziyla(int(r)) for r in kesir)
    else:
        okunan = sayi_yaziyla(int(kesir))
    return f"{sayi_yaziyla(int(m.group(1).replace('.', '')))} virgül {okunan}"


def _yaziya_yil_haric(m):
    s = m.group(0)
    if len(s) == 4 and 1900 <= int(s) <= 2099:
        return s                         # yıl doğru okunuyor, bozma
    return sayi_yaziyla(int(s))

# TTS birim/kısaltma açılımları — seslendirici "GW", "TWh" gibi birimleri
# telaffuz edemiyor; ses metninde açık yazılır. Uzun birimler önce
# (TWh, GW'den önce eşleşmeli). Sadece SES metnini etkiler, bülteni değil.
TTS_ACILIMLAR = [
    # ⚠ Yüzde işareti sayı kurallarından ÖNCE açılmalı: sayı yazıya
    # çevrildikten sonra "%" kendinden sonra rakam bulamaz.
    (r"%\s*(?=\d)", "yüzde "),
    # --- ARALIK VE SAYI BİÇİMLERİ (birimlerden ÖNCE çalışmalı) ---
    # ⚠ Tire, seslendiricide en sık yanlış okunan işaret. "2026-28 dönemi"
    # iki ayrı sayı gibi ya da çıkarma işlemi gibi okunuyor. Tireyi hiç
    # bırakmadan "ila" ile açıyoruz: kısa yıl da 4 haneye tamamlanır.
    (r"\b(19|20)(\d{2})\s*[-–—]\s*((?:19|20)\d{2})\b", r"\1\2 ila \3"),
    (r"\b((?:19|20)\d{2})\s*[-–—]\s*(\d{2})\b", r"\1 ila 20\2"),
    # sayı aralığı: "50-60 bin ton" → "50 ila 60 bin ton"
    (r"(?<=\d)\s*[-–—]\s*(?=\d)", " ila "),
    # ondalık + büyüklük: "19,1 milyon avro" → "on dokuz milyon yüz bin avro"
    (r"\b(\d[\d.]*),(\d+)\s*(bin|milyon|milyar|trilyon)\b", _olcekli_ondalik),
    # binlik ayıraçlı sayı: "1.223 dolar" ondalık gibi okunuyor → yazıyla
    (r"\b\d{1,3}(?:\.\d{3})+\b", _yaziya),
    # kalan ondalık: "3,5 puan" → "üç virgül beş puan"
    (r"\b(\d[\d.]*),(\d+)\b", _ondalik),
    # ayıraçsız uzun sayı da rakam rakam okunuyor; yıllar dokunulmadan kalır
    (r"\b\d{4,}\b", _yaziya_yil_haric),
    # --- BİRİMLER ---
    # "110MW" bitişik yazılınca rakamla harf arasında \b yok, birim açılmıyor;
    # önce araya boşluk koyuyoruz ki aşağıdaki kurallar eşleşsin.
    (r"(?<=\d)(?=(?:TWh|GWh|MWh|kWh|GWe|MWe|GWt|MWt|GW|MW|kW)\b)", " "),
    (r"\bTWh\b", "teravat saat"),
    (r"\bGWh\b", "gigavat saat"),
    (r"\bMWh\b", "megavat saat"),
    (r"\bkWh\b", "kilovat saat"),
    (r"\bGWe\b", "gigavat"),
    (r"\bMWe\b", "megavat"),
    (r"\bGWt\b", "gigavat termal"),
    (r"\bMWt\b", "megavat termal"),
    (r"\bGW\b", "gigavat"),
    (r"\bMW\b", "megavat"),
    (r"\bkW\b", "kilovat"),
]


def _tts_acilim(t):
    for kalip, yerine in TTS_ACILIMLAR:
        t = re.sub(kalip, yerine, t)
    return t


def ses_metni(bulten):
    """TTS için okunabilir metin. Parantez içi İngilizce terimler ayıklanır,
    birimler açık yazılır (GW → gigavat)."""
    i = bulten["issue"]
    d = datetime.strptime(i["publication_date"], "%Y-%m-%d")
    satirlar = [
        f"Yarı İletken Bülteni. {d.day} {AY_TR[d.month - 1]} {d.year}, sayı {i['number']}.",
        "Bu hafta altmış saniyede.",
    ]
    for n, m in enumerate(bulten.get("brief", [])):
        t = m.get("text", "") if isinstance(m, dict) else str(m)
        t = re.sub(r"\s*\([^)]*\)", "", t).strip()   # "(SMR)" → sil
        t = _tts_acilim(t)
        t = re.sub(r"\s{2,}", " ", t)
        if t:
            satirlar.append(f"{SIRA[n] if n < len(SIRA) else n + 1}. {t}")
    satirlar.append("Ayrıntılar bültende.")
    return "\n".join(satirlar)


def ses_uret(bulten):
    """Anahtar yoksa/hata olursa None döner — bülten sessiz yayınlanır."""
    if not ELEVENLABS_API_KEY:
        log("Ses atlandı (ELEVENLABS_API_KEY yok)")
        return None

    metin = ses_metni(bulten)
    hafta = bulten["issue"]["hafta"]
    log(f"Ses üretiliyor — {len(metin)} karakter")

    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
            f"?output_format=mp3_44100_128",
            headers={"xi-api-key": ELEVENLABS_API_KEY,
                     "Content-Type": "application/json"},
            json={
                "text": metin,
                "model_id": ELEVENLABS_MODEL,
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.75,
                                   "style": 0.0, "use_speaker_boost": True},
            },
            timeout=180,
        )
        if r.status_code != 200:
            log(f"ElevenLabs {r.status_code}: {r.text[:200]}")
            return None

        os.makedirs(f"{OUT}/assets/audio", exist_ok=True)
        yol = f"{OUT}/assets/audio/{hafta}.mp3"
        with open(yol, "wb") as f:
            f.write(r.content)

        sure = round(len(r.content) / 16000)   # 128 kbps ≈ 16 KB/sn
        bulten["issue"]["audio"] = {
            "url": f"assets/audio/{hafta}.mp3",
            "duration_sec": sure,
            "voice": ELEVENLABS_VOICE_ID,
            "chars": len(metin),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        log(f"Ses hazır: {yol} (~{sure} sn, {len(r.content)//1024} KB)")
        return yol
    except Exception as e:
        log(f"Ses hatası: {e}")
        return None


# ============================================================
# İNŞA — docs/
# ============================================================
def yaz_json(yol, veri):
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)


def rss_uret(son):
    def esc(s):
        return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))
    ogeler = []
    for s in [son.get("lead")] + (son.get("stories") or []):
        if not s:
            continue
        ogeler.append(f"""  <item>
    <title>{esc(s['title'])}</title>
    <link>{SITE_URL}/#/haber/{esc(s['slug'])}</link>
    <guid isPermaLink="false">{esc(s['slug'])}</guid>
    <pubDate>{esc(s.get('published_date'))}</pubDate>
    <category>{esc(KATEGORILER.get(s['category'], {}).get('ad'))}</category>
    <description>{esc(s['excerpt'])}</description>
  </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Yarı İletken Bülteni</title>
  <link>{SITE_URL}</link>
  <description>Haftalık yarı iletken sektörü ve sanayi politikası izleme bülteni</description>
  <language>tr</language>
  <lastBuildDate>{datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>
{chr(10).join(ogeler)}
</channel></rss>"""


def state_yukle_canli():
    try:
        r = requests.get(f"{SITE_URL}/data/state/seen_events.json", timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"issue_no": 0, "events": [], "urls": []}


def state_guncelle(state, taslak, bulten):
    """Son ~8 haftalık hafızayı tut. Yedekler de 'görülmüş' sayılır —
    yayınlanmadılar ama değerlendirilip elendiler; gelecek hafta yeni
    unsur yoksa tekrar aday olmasınlar."""
    yeni_urller = []
    for s in taslak.get("stories") or []:
        if (s.get("source") or {}).get("url"):
            yeni_urller.append(s["source"]["url"])
        yeni_urller += [k.get("url") for k in (s.get("supporting_sources") or [])
                        if k.get("url")]
    for k in bulten.get("radar", []):
        yeni_urller += [m["url"] for m in k.get("maddeler", []) if m.get("url")]

    yayimlanan = [bulten.get("lead")] + (bulten.get("stories") or [])
    yeni_olaylar = [{"baslik_ozet": s["title"], "hafta": bulten["issue"]["hafta"]}
                    for s in yayimlanan if s]

    state["events"] = (state.get("events", []) + yeni_olaylar)[-400:]
    state["urls"] = list(dict.fromkeys(
        state.get("urls", []) + [url_normalize(u) for u in yeni_urller]))[-3000:]
    state["issue_no"] = bulten["issue"]["number"]
    return state


def _indeks_satiri(b):
    """Tam bülten JSON'undan arşiv indeksi satırı üretir."""
    i = b["issue"]
    return {
        "number": i["number"],
        "hafta": i["hafta"],
        "publication_date": i.get("publication_date"),
        "coverage_start": i.get("coverage_start"),
        "coverage_end": i.get("coverage_end"),
        "lead_title": b["lead"]["title"] if b.get("lead") else "?",
        "story_count": len(b.get("stories", [])),
        "radar_count": sum(len(k.get("maddeler", [])) for k in b.get("radar", [])),
        "file": f"data/arsiv/{i['hafta']}.json",
    }


def _indeks_kur(arsiv_dizini, yeni_bulten=None):
    """Verilen arşiv klasöründeki tüm sayı dosyalarından indeks listesi kurar.

    yeni_bulten verilirse (henüz diske yazılmamış sayı) listeye eklenir;
    aynı haftanın önceki kaydının üzerine yazar.
    """
    kayitlar = {}
    if os.path.isdir(arsiv_dizini):
        for ad in sorted(os.listdir(arsiv_dizini)):
            if not ad.endswith(".json"):
                continue
            try:
                with open(os.path.join(arsiv_dizini, ad), encoding="utf-8") as f:
                    b = json.load(f)
                kayitlar[b["issue"]["hafta"]] = _indeks_satiri(b)
            except Exception as e:
                log(f"  ⚠ arşiv dosyası okunamadı, atlandı ({ad}): {e}")
    if yeni_bulten:
        kayitlar[yeni_bulten["issue"]["hafta"]] = _indeks_satiri(yeni_bulten)
    return sorted(kayitlar.values(),
                  key=lambda s: (s["number"] or 0, s["hafta"]), reverse=True)


def arsiv_indeksi(bulten):
    """Arşiv indeksini YEREL arşiv dosyalarından yeniden kurar.

    ⚠ NEDEN YERELDEN: Önceki sürüm index.json'u canlı siteden HTTP ile
    çekiyordu; tek bir ağ hatasında liste boş ([]) kabul edilip TÜM ARŞİV
    GEÇMİŞİ siliniyordu (dosyalar diskte kalsa bile arşiv sayfası boşalırdı).

    docs/data/arsiv/*.json git'te tutulduğu için Render cron'u her çalışmada
    depoyu klonladığında yayınlanmış tüm sayılar zaten yerelde hazır olur —
    bu, ağa bağımlı olmayan otoriter kaynaktır. İndeks bozulsa/silinse bile
    arşiv dosyalarından kendini onarır.
    """
    liste = _indeks_kur(f"{OUT}/data/arsiv", bulten)
    log(f"Arşiv indeksi: {len(liste)} sayı "
        f"({', '.join(str(s['number']) for s in liste[:8])}"
        f"{'…' if len(liste) > 8 else ''})")
    return liste


def insa_et(bulten, state, sayilar):
    os.makedirs(f"{OUT}/data/arsiv", exist_ok=True)
    os.makedirs(f"{OUT}/data/state", exist_ok=True)

    hafta = bulten["issue"]["hafta"]
    yaz_json(f"{OUT}/data/latest.json", bulten)
    yaz_json(f"{OUT}/data/arsiv/{hafta}.json", bulten)
    yaz_json(f"{OUT}/data/index.json", sayilar)
    yaz_json(f"{OUT}/data/state/seen_events.json", state)

    with open(f"{OUT}/feed.xml", "w", encoding="utf-8") as f:
        f.write(rss_uret(bulten))

    open(f"{OUT}/.nojekyll", "w").close()   # Jekyll işlemesini kapat

    for dosya in ("index.html", "arsiv.html"):
        if os.path.exists(f"site/{dosya}"):
            with open(f"site/{dosya}", encoding="utf-8") as src, \
                 open(f"{OUT}/{dosya}", "w", encoding="utf-8") as dst:
                dst.write(src.read())

    if os.path.isdir("assets"):
        import shutil
        shutil.copytree("assets", f"{OUT}/assets", dirs_exist_ok=True)

    log(f"{OUT}/ hazır — sayı {bulten['issue']['number']} ({hafta})")


# ============================================================
# DEPLOY — docs/ klasörünü GitHub'a push et (GitHub Pages yayınlar)
# ============================================================
def deploy(sayi_no):
    if not (GITHUB_REPO and GITHUB_TOKEN):
        log("Deploy atlandı (GITHUB_REPO / GITHUB_TOKEN yok)")
        return None

    import shutil
    import tempfile
    import subprocess

    tmp = tempfile.mkdtemp()
    uzak = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"

    def git(*args, kontrol=True):
        r = subprocess.run(["git", "-C", tmp, *args],
                           capture_output=True, text=True)
        if kontrol and r.returncode != 0:
            raise RuntimeError(f"git {args[0]}: {r.stderr[:200]}")
        return r

    try:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "-b", GITHUB_BRANCH, uzak, tmp],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"clone: {r.stderr[:200]}")

        hedef = os.path.join(tmp, OUT)
        shutil.rmtree(hedef, ignore_errors=True)
        shutil.copytree(OUT, hedef)

        git("config", "user.email", "bulten-bot@users.noreply.github.com")
        git("config", "user.name", "Bulten Bot")
        git("add", "-A")

        c = git("commit", "-m", f"Sayı {sayi_no} — onaylı yayın", kontrol=False)
        if c.returncode != 0 and "nothing to commit" in (c.stdout + c.stderr):
            log("Değişiklik yok — push atlandı")
            return SITE_URL

        git("push", "origin", GITHUB_BRANCH)
        log("GitHub push başarılı → Pages 1-2 dk içinde yayına alır")
        return SITE_URL
    except Exception as e:
        log(f"Deploy hatası: {e}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================
# YAYIN — review_app geç onayda da bunu çağırır
# ============================================================
def yayinla(issue_row, dry_run=False):
    """Onaylı sayıyı yayınlar. issue_row: db.issue_getir() satırı.
    Dönen değer: yayın URL'i veya None."""
    import db
    import emails

    taslak = issue_row["draft_json"]
    if isinstance(taslak, str):
        taslak = json.loads(taslak)

    bulten = nihai_kur(taslak)
    log(f"Nihai bülten kuruldu: manşet + {len(bulten['stories'])} haber, "
        f"{sum(len(k.get('maddeler', [])) for k in bulten['radar'])} radar maddesi")

    if not dry_run:
        ses_uret(bulten)          # issue.audio doldurur (hata olursa sessiz)

    state = state_yukle_canli()
    state = state_guncelle(state, taslak, bulten)
    sayilar = arsiv_indeksi(bulten)
    insa_et(bulten, state, sayilar)

    if dry_run:
        log("DRY RUN — push/e-posta/DB atlandı")
        return None

    url = deploy(bulten["issue"]["number"])
    if not url:
        # Push başarısızsa sayı 'approved' durumunda KALIR — sorun (örn.
        # GITHUB_TOKEN izni) giderilince yayın cron'u yeniden tetiklenebilir.
        db.logla(issue_row["id"], issue_row.get("approved_by"), "yayin_hatasi", {})
        raise RuntimeError(
            "Deploy başarısız (yukarıdaki 'Deploy hatası' satırına bakın) — "
            "sayı onaylı durumda bırakıldı; sorunu giderip yayını yeniden tetikleyin")
    db.yayinlandi(issue_row["id"], bulten)
    db.logla(issue_row["id"], issue_row.get("approved_by"), "yayin",
             {"url": url})

    alicilar = [h["email"] for h in db.hakemler()]
    if RAPOR_ALICI and RAPOR_ALICI not in alicilar:
        alicilar.append(RAPOR_ALICI)
    if alicilar:
        emails.yayinlandi_gonder(alicilar, bulten["issue"]["number"],
                                 bulten["issue"]["hafta"], SITE_URL,
                                 issue_row.get("approved_by") or "?")
    return url


# ============================================================
# DÜZELTME YAYINI — yayınlanmış sayıdaki metin hatasını siteye gönder
# ------------------------------------------------------------
# Tam yayından (yayinla) farkları:
#   · Ses YENİDEN ÜRETİLMEZ — ElevenLabs kotası harcanmaz. (Sesli özet
#     düzeltilen metni okumaya devam eder; kabul edilen ödünç budur.)
#   · state/sayaç DEĞİŞMEZ — bu yeni bir sayı değil, mevcut sayının düzeltmesi.
#   · Depo TAZE klonlanır ve yalnızca ilgili dosyalar değiştirilir. Yerel
#     docs/ kopyasına güvenilmez: web servisinin çalışma dizini son cron
#     yayınına göre bayat olabilir ve tüm docs/ üzerine yazmak yayınlanmış
#     sayıları silebilirdi.
# ============================================================
def duzeltme_yayinla(bulten):
    """Düzeltilmiş bülteni siteye gönderir. Dönen: site URL'i.

    Değiştirilen dosyalar: data/arsiv/<hafta>.json, (sayı en günceli ise)
    data/latest.json ve feed.xml, ve her durumda data/index.json.
    """
    if not (GITHUB_REPO and GITHUB_TOKEN):
        raise RuntimeError("GITHUB_REPO / GITHUB_TOKEN tanımlı değil")

    import shutil
    import tempfile
    import subprocess

    hafta = bulten["issue"]["hafta"]
    tmp = tempfile.mkdtemp()
    uzak = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"

    def git(*a, kontrol=True):
        r = subprocess.run(["git", "-C", tmp, *a], capture_output=True, text=True)
        if kontrol and r.returncode != 0:
            raise RuntimeError(f"git {a[0]}: {r.stderr[:200]}")
        return r

    try:
        r = subprocess.run(["git", "clone", "--depth", "1", "-b", GITHUB_BRANCH, uzak, tmp],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"clone: {r.stderr[:200]}")

        kok = os.path.join(tmp, OUT)
        arsiv_dizini = os.path.join(kok, "data", "arsiv")
        os.makedirs(arsiv_dizini, exist_ok=True)

        # 1) sayının arşiv dosyası
        yaz_json(os.path.join(arsiv_dizini, f"{hafta}.json"), bulten)

        # 2) en güncel sayı ise ana sayfa verisi + RSS
        latest_yolu = os.path.join(kok, "data", "latest.json")
        guncel_mi = False
        if os.path.exists(latest_yolu):
            try:
                with open(latest_yolu, encoding="utf-8") as f:
                    guncel_mi = (json.load(f).get("issue", {}).get("hafta") == hafta)
            except Exception:
                guncel_mi = False
        if guncel_mi:
            yaz_json(latest_yolu, bulten)
            with open(os.path.join(kok, "feed.xml"), "w", encoding="utf-8") as f:
                f.write(rss_uret(bulten))

        # 3) indeksi arşiv dosyalarından yeniden kur (başlık değişmiş olabilir)
        yaz_json(os.path.join(kok, "data", "index.json"), _indeks_kur(arsiv_dizini))

        git("config", "user.email", "bulten-bot@users.noreply.github.com")
        git("config", "user.name", "Bulten Bot")
        git("add", "-A")
        c = git("commit", "-m", f"Sayı {bulten['issue']['number']} — metin düzeltmesi",
                kontrol=False)
        if c.returncode != 0 and "nothing to commit" in (c.stdout + c.stderr):
            log("Düzeltme: değişiklik yok — push atlandı")
            return SITE_URL
        git("push", "origin", GITHUB_BRANCH)
        log(f"Düzeltme yayınlandı ({hafta}"
            f"{', ana sayfa dahil' if guncel_mi else ', yalnızca arşiv'})")
        return SITE_URL
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================
# ANA AKIŞ (cron)
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="push/e-posta/DB değişikliği yok; docs/ üretir")
    ap.add_argument("--local-draft", action="store_true",
                    help="DB yerine taslak_preview.json kullan (dry-run zorunlu)")
    args = ap.parse_args()

    t0 = time.time()
    log("═" * 46)
    log(f"YARI İLETKEN BÜLTENİ — YAYIN — "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")

    if args.local_draft:
        with open("taslak_preview.json", encoding="utf-8") as f:
            taslak = json.load(f)
        bulten = nihai_kur(taslak)
        state = state_guncelle({"issue_no": 0, "events": [], "urls": []},
                               taslak, bulten)
        insa_et(bulten, state, arsiv_indeksi(bulten))
        log(f"LOCAL DRAFT — docs/ üretildi ({time.time()-t0:.0f} sn)")
        return

    import db
    import emails

    # ISO hafta Pazartesi değişir: taslak Pazar'ın haftasını taşır.
    # Bu yüzden haftaya değil DURUMA göre çek: approved > review.
    sayi = db.issue_getir(status="approved") or db.issue_getir(status="review")
    if not sayi:
        log("Bekleyen sayı yok — çıkılıyor")
        return

    if sayi["status"] == "approved":
        url = yayinla(sayi, dry_run=args.dry_run)
        log(f"Yayın: {url or '(dry-run / hata)'}")
    else:
        # Onay yok → hatırlatma; OTOMATİK YAYIN YOK
        log(f"Sayı {sayi['sayi_no']} onay bekliyor — hatırlatma gönderiliyor")
        if not args.dry_run:
            n = 0
            for h in db.hakemler():
                link = (f"{REVIEW_BASE_URL}/r/{h['token']}"
                        if REVIEW_BASE_URL else "(REVIEW_BASE_URL yok)")
                if emails.hatirlatma_gonder(h, link, sayi["sayi_no"], sayi["hafta"]):
                    n += 1
            db.logla(sayi["id"], None, "hatirlatma", {"gonderilen": n})
            log(f"Hatırlatma: {n} hakeme gönderildi")

    log(f"Tamamlandı — {time.time() - t0:.0f} sn")
    log("═" * 46)


if __name__ == "__main__":
    main()
