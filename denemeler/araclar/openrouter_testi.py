# -*- coding: utf-8 -*-
"""
OPENROUTER GEÇİDİ — UÇTAN UCA TEST
==================================================================
OpenRouter'a geçiş sonrası sistemin GERÇEKTEN çalıştığını, yayımlanmış
bülteni hiç riske atmadan doğrular.

NE YAPMAZ (kasıtlı):
  · Neon'a yazmaz / okumaz        · e-posta göndermez
  · docs/ altına dokunmaz         · taslak_preview.json'u ezmez
  · Exa'yı çağırmaz (para yakmaz) · sayı numarasını ilerletmez
Sahte ama GERÇEK BİÇİMDE veri kullanır; yalnızca LLM çağrısı yapar.

NE YAPAR:
  0. Anahtar var mı (değeri EKRANA BASILMAZ)
  1. effort kapısı — ağsız birim testi (OpenRouter slug normalizasyonu)
  2. Ham HTTP sondası — isteği hangi sağlayıcı karşıladı, maliyet geldi mi
  2b. Yetenek sondası — o sağlayıcı effort ve prompt cache'i kabul ediyor mu
  3. Triyaj yolu  — Haiku 4.5, prompt cache açık, gerçek TRIYAJ_PROMPT
  4. Yazım yolu   — Sonnet 5, akışlı, effort'lu, gerçek YAZIM_PROMPT
  5. Maliyet raporu (llm.py'nin kendi muhasebesi)

Çalıştırma:
  python denemeler/araclar/openrouter_testi.py            # tam test  (~$0.05)
  python denemeler/araclar/openrouter_testi.py --hizli    # yazım hariç (~$0.01)
  python denemeler/araclar/openrouter_testi.py --dogrudan # aynı testi
                                    doğrudan Anthropic üzerinden koşar (kıyas)
"""

import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

import requests

from config import AYARLAR                    # .env'i ortama yükler (sıra önemli)
import prompts
import llm
import pipeline                               # json_ayikla + yazim_eksik için
                                               # (db/emails yalnızca main içinde
                                               #  import edilir → yan etki yok)

GECER, KALIR = [], []


def bas(baslik):
    print("\n" + "─" * 62)
    print(baslik)
    print("─" * 62)


def sonuc(ad, tamam, not_=""):
    (GECER if tamam else KALIR).append(ad)
    print(f"  {'✓' if tamam else '✗'} {ad}" + (f" — {not_}" if not_ else ""))


# ============================================================
# 0) ANAHTAR
# ============================================================
def test_anahtar(gecit):
    bas("0) ANAHTAR")
    ad = "OPENROUTER_API_KEY" if gecit == "openrouter" else "ANTHROPIC_API_KEY"
    v = os.environ.get(ad, "")
    if not v or v == "BURAYA_YAPISTIR":
        sonuc(ad, False, "tanımlı değil — .env'e ekleyin veya ortama verin")
        return False
    # Değer ASLA basılmaz; yalnızca uzunluk ve önek biçimi.
    onek = v[:8] + "…" if len(v) > 12 else "(kısa)"
    sonuc(ad, True, f"{len(v)} karakter, {onek}")
    return True


# ============================================================
# 1) EFFORT KAPISI — ağ gerektirmez
# ============================================================
def test_effort_kapisi():
    """OpenRouter slug'ı noktalı ve org önekli geliyor. Normalizasyon
    bozulursa effort SESSİZCE gönderilmez (maliyet ve davranış değişir),
    ya da Haiku'ya gönderilip istek 400 döner. İkisi de sessiz hatadır.
    """
    bas("1) EFFORT KAPISI (ağsız)")
    beklenen = {
        "anthropic/claude-sonnet-5": True,
        "anthropic/claude-sonnet-4.6": True,
        "anthropic/claude-opus-4.8": True,
        "anthropic/claude-haiku-4.5": False,      # effort göndermek 400 verir
        "anthropic/claude-sonnet-4.5": False,
        "claude-sonnet-5": True,                   # doğrudan Anthropic yolu
        "claude-haiku-4-5-20251001": False,
    }
    hepsi = True
    for slug, bekle in beklenen.items():
        var = llm._effort_destekler(slug)
        if var != bekle:
            hepsi = False
            print(f"    ! {slug}: beklenen {bekle}, dönen {var}")
    sonuc("slug normalizasyonu", hepsi,
          f"{len(beklenen)} model adı denendi")
    return hepsi


# ============================================================
# 2) HAM HTTP SONDASI — hangi sağlayıcı karşıladı?
# ============================================================
def test_sonda(gecit):
    """llm.py'yi ATLAYARAK tek istek atar. Amaç: yanıtın üst verisini
    görmek — model adı, isteği karşılayan altyapı (provider) ve gerçek
    maliyet. llm.py bu alanları kullanmadığı için ayrıca bakılıyor.
    """
    bas("2) HAM HTTP SONDASI")
    if gecit == "openrouter":
        url = llm.OPENROUTER_URL
        basliklar = {"Authorization": f"Bearer {llm.OPENROUTER_API_KEY}",
                     "Content-Type": "application/json"}
        model = "anthropic/claude-haiku-4.5"
        govde = {"model": model, "max_tokens": 32,
                 "messages": [{"role": "user", "content": "Tek kelime yaz: hazir"}]}
        sag = llm._openrouter_saglayici()
        if sag:
            govde["provider"] = sag
        print(f"    sağlayıcı ayarı : {sag or '(serbest — seçimi OpenRouter yapar)'}")
    else:
        url = llm.ANTHROPIC_URL
        basliklar = {"x-api-key": llm.ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"}
        model = "claude-haiku-4-5-20251001"
        govde = {"model": model, "max_tokens": 32,
                 "messages": [{"role": "user", "content": "Tek kelime yaz: hazir"}]}

    t0 = time.time()
    try:
        r = requests.post(url, headers=basliklar, json=govde, timeout=60)
    except Exception as e:
        sonuc("bağlantı", False, str(e)[:160])
        return False
    if r.status_code != 200:
        sonuc("bağlantı", False, f"HTTP {r.status_code}")
        # ⚠ Hata gövdesini KISALTMADAN bas: OpenRouter 404'lerinde
        # metadata.routing_funnel hangi filtrenin uçları elediğini adım adım
        # söylüyor — teşhis tamamen bu listede.
        print("    ── ham hata gövdesi ──")
        try:
            print("    " + json.dumps(r.json(), ensure_ascii=False, indent=2)
                  .replace("\n", "\n    "))
        except Exception:
            print("    " + r.text[:2000])
        if govde.get("provider"):
            # Sağlayıcı sabitlemesi mi eledi? Aynı isteği bloksuz dene.
            print("    ── aynı istek sağlayıcı sabitlemesi OLMADAN ──")
            govde2 = {k: v for k, v in govde.items() if k != "provider"}
            try:
                r2 = requests.post(url, headers=basliklar, json=govde2, timeout=60)
            except Exception as e:
                print(f"    bağlanılamadı: {str(e)[:160]}")
                return False
            if r2.status_code == 200:
                d2 = r2.json()
                print(f"    ✓ ÇALIŞTI — isteği karşılayan sağlayıcı: "
                      f"{d2.get('provider')}")
                print("    → Suç sağlayıcı sabitlemesinde. config.py'de")
                print("      \"openrouter_saglayici\" değerini bu sağlayıcıya")
                print("      göre düzeltin ya da None yapın.")
            else:
                print(f"    ✗ o da olmadı — HTTP {r2.status_code}: {r2.text[:400]}")
        return False

    d = r.json()
    metin = "".join(b.get("text", "") for b in d.get("content", [])
                    if b.get("type") == "text")
    u = d.get("usage") or {}
    sonuc("bağlantı", True, f"HTTP 200, {time.time() - t0:.1f} sn")
    print(f"    yanıt model : {d.get('model')}")
    print(f"    sağlayıcı   : {d.get('provider') or '(bildirilmedi)'}")
    print(f"    stop_reason : {d.get('stop_reason')}")
    print(f"    usage       : girdi {u.get('input_tokens')} / "
          f"çıktı {u.get('output_tokens')}")
    print(f"    usage.cost  : {u.get('cost') if u.get('cost') is not None else '(yok → FIYAT tahmini kullanılır)'}")
    print(f"    metin       : {metin.strip()[:60]!r}")
    # Anthropic şemasının birebir döndüğünü kanıtla: content blokları + usage
    sema = bool(d.get("content")) and "input_tokens" in u
    sonuc("Anthropic yanıt şeması", sema,
          "content blokları + usage.input_tokens geldi" if sema
          else "şema beklenenden farklı — llm.py çözümleyicisi kırılır")
    return sema


# ============================================================
# 2b) YETENEK SONDASI — sağlayıcı ne kabul ediyor?
# ============================================================
# İsteği Anthropic yerine Bedrock/Vertex/Azure karşılıyorsa model aynı olsa
# da parametre desteği farklı olabilir. Sistemin dayandığı İKİ davranış:
#   · output_config.effort  → yazımda akıl yürütme seviyesi (maliyet + kalite)
#   · cache_control         → triyajda sistem bloğu cache'i (maliyet)
# Bunlar 400 veriyorsa pipeline haftalık çalışmada patlar; sessizce yok
# sayılıyorsa fatura beklenenden yüksek gelir. İkisini de burada ölçüyoruz.
def test_yetenek(gecit):
    bas("2b) YETENEK SONDASI")
    if gecit != "openrouter":
        print("    (yalnızca openrouter geçidinde anlamlı — atlandı)")
        return True

    basliklar = {"Authorization": f"Bearer {llm.OPENROUTER_API_KEY}",
                 "Content-Type": "application/json"}
    sag = llm._openrouter_saglayici()

    def istek(govde):
        if sag:
            govde = dict(govde, provider=sag)
        try:
            r = requests.post(llm.OPENROUTER_URL, headers=basliklar,
                              json=govde, timeout=120)
        except Exception as e:
            return None, str(e)[:200]
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:300]}"
        return r.json(), None

    # ── a) output_config.effort ──
    d, hata = istek({
        "model": "anthropic/claude-sonnet-5", "max_tokens": 64,
        "output_config": {"effort": AYARLAR.get("reasoning_effort") or "medium"},
        "messages": [{"role": "user", "content": "Tek kelime yaz: hazir"}],
    })
    if hata:
        sonuc("output_config.effort kabul edildi", False, hata)
        print("    → Bu sağlayıcı effort'u reddediyor. config.py'de")
        print("      \"reasoning_effort\": None yapın (Sonnet 5 kendi")
        print("      varsayılanıyla çalışır) ya da başka sağlayıcı seçin.")
    else:
        sonuc("output_config.effort kabul edildi", True,
              f"sağlayıcı: {d.get('provider')}")

    # ── b) prompt cache (cache_control) ──
    # Anthropic'te asgari cache'lenebilir önek 1024 token. Dolgu metni bunu
    # rahatça aşsın diye tekrarlı; triyaj sistem bloğu da bu boyuttadır.
    dolgu = ("Bülten triyaj sistem bloğu için dolgu metni; "
             "bu satır yalnızca prompt cache eşiğini aşmak içindir. ") * 200
    d, hata = istek({
        "model": "anthropic/claude-haiku-4.5", "max_tokens": 16,
        "system": [{"type": "text", "text": dolgu,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "Tek kelime yaz: hazir"}],
    })
    if hata:
        sonuc("cache_control kabul edildi", False, hata)
        print("    → Triyaj cache=True ile çağrılıyor; bu sağlayıcı kabul")
        print("      etmiyorsa pipeline HER PARTİDE hata alır.")
        return False
    u = d.get("usage") or {}
    yazilan = u.get("cache_creation_input_tokens") or 0
    sonuc("cache_control kabul edildi", True, f"sağlayıcı: {d.get('provider')}")
    if yazilan:
        sonuc("prompt cache gerçekten yazıldı", True, f"{yazilan:,} token")
    else:
        # Hata değil ama maliyet farkı: sessizce yok sayılıyor olabilir.
        sonuc("prompt cache gerçekten yazıldı", False,
              "cache_creation_input_tokens 0 — bu sağlayıcıda cache sessizce "
              "yok sayılıyor olabilir; triyaj çalışır ama daha pahalıya gelir")
    return True


# ============================================================
# 3) TRİYAJ YOLU — Haiku 4.5 + prompt cache
# ============================================================
SAHTE_ADAYLAR = [
    {"id": "t1", "title": "TSMC to add third Arizona fab with $12 billion investment",
     "domain": "reuters.com", "published_date": "2026-09-18",
     "snippet": ("TSMC said it will build a third wafer fabrication plant in "
                 "Phoenix, Arizona, with an investment of about 12 billion "
                 "dollars, targeting 2nm production from 2029 and creating "
                 "2,300 direct jobs.")},
    {"id": "t2", "title": "EU proposes Chips Act 2.0 with focus on advanced packaging",
     "domain": "ec.europa.eu", "published_date": "2026-09-17",
     "snippet": ("The European Commission presented a revised European Chips "
                 "Act, allocating 4.8 billion euro to advanced packaging and "
                 "heterogeneous integration pilot lines, and setting a 20 "
                 "percent global production share target for 2030.")},
    {"id": "t3", "title": "New gaming laptop launched with faster GPU",
     "domain": "example-gadget-blog.com", "published_date": "2026-09-16",
     "snippet": ("A consumer laptop refresh brings a new graphics card and "
                 "a brighter screen.")},   # REDDEDİLMELİ
]

def test_triyaj(model):
    bas(f"3) TRİYAJ YOLU — {model}")
    sistem = prompts.TRIYAJ_PROMPT + prompts.onceki_olaylar_bloku([])
    try:
        cikti = llm.llm_cagri(
            model, sistem,
            prompts.triyaj_kullanici_mesaji(SAHTE_ADAYLAR, "2026-09-15", "2026-09-22"),
            AYARLAR["max_tokens_triyaj"],
            cache=True,          # pipeline da böyle çağırıyor
        )
    except Exception as e:
        sonuc("triyaj çağrısı", False, str(e)[:200])
        return None
    try:
        d = pipeline.json_ayikla(cikti)
    except Exception as e:
        sonuc("triyaj JSON", False, str(e)[:200])
        return None

    olaylar = d.get("events") or []
    sonuc("triyaj çağrısı + JSON", True,
          f"{len(olaylar)} olay, {len(d.get('reject') or [])} red")
    for o in olaylar[:4]:
        print(f"    · [{o.get('kategori')}] {str(o.get('baslik_ozet'))[:70]}")
    # Prompt cache gerçekten yazıldı mı? (aynı sistem bloğu ikinci partide
    # okunur; tek partide yalnızca YAZMA görülür)
    k = llm.KULLANIM.get(model) or {}
    if k.get("cache_w"):
        sonuc("prompt cache yazımı", True, f"{k['cache_w']:,} token cache'e yazıldı")
    else:
        # BİLGİ satırı, hata değil: Haiku 4.5'in asgari cache eşiği 4096
        # token, triyaj sistem bloğu ~2.000 → cache zaten oluşmuyor (bkz.
        # pipeline.triyaj). Testin çıkış kodunu kirletmesin diye sonuc() ile
        # sayılmıyor.
        print("  ℹ prompt cache yazılmadı — BEKLENEN: Haiku 4.5'in asgari "
              "cache eşiği 4096 token,")
        print("    triyaj sistem bloğu ~2.000. Sistem çalışır, yalnızca "
              "cache tasarrufu oluşmaz.")
    return olaylar


# ============================================================
# 4) YAZIM YOLU — Sonnet 5, akışlı, effort'lu
# ============================================================
SAHTE_DERIN = [{
    "event_key": "ab-cips-yasasi-2-ileri-paketleme",
    "kategori": "politika",
    "puan": 88,
    "olgunluk": "announced",
    "baslik_ozet": "AB, ileri paketlemeye odaklı Chips Act 2.0 önerisini açıkladı",
    "sirketler": [],
    "ulkeler": ["AB"],
    "kaynaklar": [{
        "name": "European Commission", "domain": "ec.europa.eu",
        "url": "https://ec.europa.eu/example-chips-act-2",
        "published_date": "2026-09-17", "primary": True, "paywall": False,
        "text": ("The European Commission presented the revised European Chips "
                 "Act on 17 September 2026. The proposal allocates 4.8 billion "
                 "euro to advanced packaging and heterogeneous integration "
                 "pilot lines, and a further 1.3 billion euro to a design "
                 "infrastructure network for fabless start-ups. It sets a "
                 "target of 20 percent of global semiconductor production "
                 "value in the EU by 2030, up from an estimated 9 percent in "
                 "2025. Member states must notify national implementation "
                 "plans within 18 months. The Commission estimates the "
                 "European semiconductor sector employs 430,000 people and "
                 "generates 62 billion euro in annual turnover."),
    }],
}]

SAHTE_RADAR = [
    {"event_key": "asml-high-na-siparis", "kategori": "ekipman",
     "baslik_ozet": "ASML, High-NA EUV sistemleri için yeni sipariş açıkladı",
     "kaynaklar": [{"name": "Reuters", "domain": "reuters.com",
                    "url": "https://reuters.com/example-asml",
                    "published_date": "2026-09-18", "primary": True}]},
    {"event_key": "samsung-hbm4-uretim", "kategori": "bellek",
     "baslik_ozet": "Samsung HBM4 üretimine başladığını duyurdu",
     "kaynaklar": [{"name": "Bloomberg", "domain": "bloomberg.com",
                    "url": "https://bloomberg.com/example-hbm4",
                    "published_date": "2026-09-19", "primary": True}]},
]

def test_yazim(model):
    bas(f"4) YAZIM YOLU — {model} (akışlı)")
    # ⚠ pipeline'ın kendi limit mantığını KOPYALAMIYORUZ, ÇAĞIRIYORUZ:
    # AKIL_YURUTEN listesi eksik kalırsa bu test de onu görür.
    t0 = time.time()
    try:
        b = pipeline.yaz(SAHTE_DERIN, SAHTE_RADAR, 999,
                         "2026-09-15", "2026-09-22", AYARLAR["pencere_gun"],
                         model=model)
    except Exception as e:
        sonuc("yazım çağrısı", False, str(e)[:250])
        return None

    eksik = pipeline.yazim_eksik(b, SAHTE_DERIN, SAHTE_RADAR)
    sonuc("yazım çağrısı + JSON", True, f"{time.time() - t0:.0f} sn")
    sonuc("yazım bütünlük denetimi", not eksik, eksik or "eksik yok")

    st = (b.get("stories") or [])
    print(f"    stories : {len(st)}")
    for s in st[:2]:
        print(f"    · id={s.get('id')} | {str(s.get('title'))[:70]}")
        # ⚠ şema alanı "category" (İngilizce); "kategori" diye okumak
        # her zaman None döndürüyordu.
        print(f"      secim={s.get('secim')} | category={s.get('category')}")
    radar_madde = sum(len(k.get("maddeler") or []) for k in (b.get("radar") or []))
    print(f"    radar maddeleri : {radar_madde}")
    print(f"    brief maddeleri : {len(b.get('brief') or [])}")
    # id eşleşmesi: model uydurmasın, verilen event_key'i kullansın
    idler = {s.get("id") for s in st}
    sonuc("story id = event_key", "ab-cips-yasasi-2-ileri-paketleme" in idler,
          f"dönen id'ler: {sorted(x for x in idler if x)}")
    return b


# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hizli", action="store_true",
                    help="yazım testini atla (ucuz ve hızlı)")
    ap.add_argument("--dogrudan", action="store_true",
                    help="OpenRouter yerine doğrudan Anthropic'i dene (kıyas)")
    args = ap.parse_args()

    llm.set_logger(lambda m: print("   " + m.strip()))
    gecit = "anthropic" if args.dogrudan else "openrouter"

    if args.dogrudan:
        triyaj_model = "anthropic:claude-haiku-4-5-20251001"
        yazim_model = "anthropic:claude-sonnet-5"
    else:
        triyaj_model = AYARLAR["model_triyaj"]
        yazim_model = AYARLAR["model_yazim"]

    print("═" * 62)
    print(f"OPENROUTER TESTİ — geçit: {gecit}")
    print(f"  triyaj : {triyaj_model}")
    print(f"  yazım  : {yazim_model}")
    print(f"  effort : {AYARLAR.get('reasoning_effort')}")
    print("  ⚠ Bu betik DB'ye yazmaz, e-posta atmaz, bülteni değiştirmez.")
    print("═" * 62)

    if not test_anahtar(gecit):
        sys.exit(1)
    test_effort_kapisi()
    if not test_sonda(gecit):
        print("\nSonda başarısız — sonraki testler anlamsız, duruluyor.")
        sys.exit(1)
    test_yetenek(gecit)
    test_triyaj(triyaj_model)
    if not args.hizli:
        test_yazim(yazim_model)
    else:
        print("\n(yazım testi --hizli ile atlandı)")

    bas("5) MALİYET (llm.py muhasebesi)")
    rapor, toplam = llm.maliyet_raporu()
    print(rapor)

    bas("SONUÇ")
    print(f"  geçen : {len(GECER)}")
    print(f"  kalan : {len(KALIR)}" + (f" → {', '.join(KALIR)}" if KALIR else ""))
    print(f"  bu testin maliyeti ≈ ${toplam:.3f}")
    sys.exit(1 if KALIR else 0)


if __name__ == "__main__":
    main()
