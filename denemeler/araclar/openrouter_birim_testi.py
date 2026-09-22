# -*- coding: utf-8 -*-
"""OPENROUTER GEÇİDİ — ÇEVRİMDIŞI BİRİM TESTİ (ağ yok, ücret yok)

OpenRouter'a geçişte sessiz kalabilecek hataları yakalar. Hepsi gerçek
vakalara dayanıyor:

  1. effort kapısı — OpenRouter slug'ı noktalı ve org önekli gelir
     ("anthropic/claude-sonnet-4.6"). Normalizasyon bozulursa effort
     sessizce HİÇ gönderilmez ya da Haiku'ya gönderilip istek 400 döner.
  2. Geçit seçimi — openrouter isteği Bearer + /api/v1/messages ile,
     Anthropic isteği x-api-key + api.anthropic.com ile gitmeli; başlıklar
     karışırsa 401 alınır.
  3. Sağlayıcı sabitleme — provider bloğu düşerse istek Bedrock/Vertex'e
     kayabilir ve orada output_config reddedilir.
  4. Model adı biçimi — tarihli Anthropic kimliği OpenRouter'da 404 verir.
  5. AKIL_YURUTEN listesi — yazım modeli bu listede yoksa dar bütçe
     kullanılır, düşünme token'ları payı yer ve JSON ORTADAN KESİLİR.
  6. Gerçek maliyet — OpenRouter usage.cost'u raporda "gerçek" görünmeli.

Kullanım: python openrouter_birim_testi.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

from config import AYARLAR, FIYAT
import llm
import pipeline

GECEN, KALAN = 0, []


def dogrula(ad, kosul, not_=""):
    global GECEN
    if kosul:
        GECEN += 1
    else:
        KALAN.append(f"{ad}" + (f" — {not_}" if not_ else ""))


# ============================================================
# 1) effort kapısı — slug normalizasyonu
# ============================================================
for slug, bekle in {
    "anthropic/claude-sonnet-5": True,
    "anthropic/claude-sonnet-4.6": True,
    "anthropic/claude-opus-4.8": True,
    "anthropic/claude-fable-5.1": True,
    "anthropic/claude-haiku-4.5": False,        # gönderilirse 400
    "anthropic/claude-sonnet-4.5": False,
    "claude-sonnet-5": True,                     # doğrudan Anthropic yolu
    "claude-haiku-4-5-20251001": False,
}.items():
    dogrula(f"effort kapısı: {slug}", llm._effort_destekler(slug) == bekle,
            f"beklenen {bekle}")


# ============================================================
# 2-3) Geçit seçimi + sağlayıcı sabitleme (requests.post taklit edilir)
# ============================================================
class _SahteYanit:
    status_code = 200

    def __init__(self, cost=None):
        self._cost = cost

    def json(self):
        u = {"input_tokens": 100, "output_tokens": 20,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        if self._cost is not None:
            u["cost"] = self._cost
        return {"content": [{"type": "text", "text": "tamam"}], "usage": u}


def _yakala(cost=None):
    """llm.requests.post'u değiştirir, gönderilen isteği kaydeder."""
    kayit = {}

    def sahte_post(url, headers=None, json=None, timeout=None, **kw):
        kayit["url"] = url
        kayit["headers"] = headers or {}
        kayit["body"] = json or {}
        return _SahteYanit(cost)

    llm.requests.post = sahte_post
    return kayit


_gercek_post = llm.requests.post
llm.KULLANIM.clear()

# ── OpenRouter geçidi ──
llm.OPENROUTER_API_KEY = "sk-or-v1-test"
k = _yakala(cost=0.0042)
llm.llm_cagri("openrouter:anthropic/claude-sonnet-5", "SİSTEM", "KULLANICI", 1000)

dogrula("openrouter URL", k["url"] == "https://openrouter.ai/api/v1/messages",
        k["url"])
dogrula("openrouter Bearer başlığı",
        k["headers"].get("Authorization") == "Bearer sk-or-v1-test")
dogrula("openrouter'da x-api-key YOK", "x-api-key" not in k["headers"])
dogrula("openrouter'da anthropic-version YOK",
        "anthropic-version" not in k["headers"])
dogrula("sağlayıcı bloğu config'ten geldi",
        k["body"].get("provider") == AYARLAR.get("openrouter_saglayici"),
        str(k["body"].get("provider")))
dogrula("model adı org önekli gönderildi",
        k["body"].get("model") == "anthropic/claude-sonnet-5",
        str(k["body"].get("model")))
dogrula("Sonnet 5'e effort gönderildi",
        (k["body"].get("output_config") or {}).get("effort")
        == AYARLAR.get("reasoning_effort"),
        str(k["body"].get("output_config")))
dogrula("gövde Anthropic şemasında (system + messages)",
        "system" in k["body"] and "messages" in k["body"]
        and "max_tokens" in k["body"])

# ── Haiku: effort GÖNDERİLMEMELİ ──
k = _yakala()
llm.llm_cagri("openrouter:anthropic/claude-haiku-4.5", "SİSTEM", "KULLANICI",
              1000, cache=True)
dogrula("Haiku'ya effort gönderilmedi", "output_config" not in k["body"],
        str(k["body"].get("output_config")))
dogrula("cache=True → system bloğu cache_control ile",
        isinstance(k["body"].get("system"), list)
        and k["body"]["system"][0].get("cache_control") == {"type": "ephemeral"})

# ── OPENROUTER_SAGLAYICI ortam değişkeni: config'i ezer ──
os.environ["OPENROUTER_SAGLAYICI"] = "serbest"
k = _yakala()
llm.llm_cagri("openrouter:anthropic/claude-sonnet-5", "S", "K", 1000)
dogrula("OPENROUTER_SAGLAYICI=serbest → provider bloğu YOK",
        "provider" not in k["body"], str(k["body"].get("provider")))

os.environ["OPENROUTER_SAGLAYICI"] = "amazon-bedrock,google-vertex"
k = _yakala()
llm.llm_cagri("openrouter:anthropic/claude-sonnet-5", "S", "K", 1000)
dogrula("OPENROUTER_SAGLAYICI listesi tercih sırası (yedeğe izinli)",
        k["body"].get("provider") == {"order": ["amazon-bedrock",
                                                "google-vertex"],
                                      "allow_fallbacks": True},
        str(k["body"].get("provider")))

# "sadece:" katı sabitleme — 404 riskini bilerek alan kullanım
os.environ["OPENROUTER_SAGLAYICI"] = "sadece:anthropic"
k = _yakala()
llm.llm_cagri("openrouter:anthropic/claude-sonnet-5", "S", "K", 1000)
dogrula("sadece: öneki → allow_fallbacks False",
        k["body"].get("provider") == {"order": ["anthropic"],
                                      "allow_fallbacks": False},
        str(k["body"].get("provider")))
del os.environ["OPENROUTER_SAGLAYICI"]

# Yapılandırılmış sağlayıcı kilitli OLMAMALI — 22 Eylül 404'ünün dersi
_yap = AYARLAR.get("openrouter_saglayici")
dogrula("config sağlayıcısı yedeğe izinli",
        _yap is None or _yap.get("allow_fallbacks") is True, str(_yap))

# ── Doğrudan Anthropic geçidi (yedek yol bozulmamış olmalı) ──
llm.ANTHROPIC_API_KEY = "sk-ant-test"
k = _yakala()
llm.llm_cagri("anthropic:claude-sonnet-5", "SİSTEM", "KULLANICI", 1000)
dogrula("anthropic URL", k["url"] == "https://api.anthropic.com/v1/messages",
        k["url"])
dogrula("anthropic x-api-key başlığı",
        k["headers"].get("x-api-key") == "sk-ant-test")
dogrula("anthropic'te provider bloğu YOK", "provider" not in k["body"])

# ── Anahtar yoksa anlaşılır hata ──
llm.OPENROUTER_API_KEY = ""
try:
    llm.llm_cagri("openrouter:anthropic/claude-sonnet-5", "S", "K", 100)
    dogrula("anahtar yoksa hata", False, "hata yükseltilmedi")
except RuntimeError as e:
    dogrula("anahtar yoksa hata", "OPENROUTER_API_KEY" in str(e), str(e))
llm.OPENROUTER_API_KEY = "sk-or-v1-test"

# ── Bilinmeyen sağlayıcı reddedilir ──
try:
    llm.llm_cagri("baskabir:model", "S", "K", 100)
    dogrula("bilinmeyen sağlayıcı reddi", False, "hata yükseltilmedi")
except ValueError:
    dogrula("bilinmeyen sağlayıcı reddi", True)


# ============================================================
# 4) config.py model adları
# ============================================================
for anahtar in ("model_triyaj", "model_yazim", "model_birlestirme"):
    ad = AYARLAR[anahtar]
    dogrula(f"{anahtar} sağlayıcı öneki var", ":" in ad, ad)
    dogrula(f"{anahtar} FIYAT tablosunda", ad in FIYAT, ad)
    if ad.startswith("openrouter:"):
        slug = ad.split(":", 1)[1]
        dogrula(f"{anahtar} org önekli", "/" in slug, slug)
        # Tarihli kimlik OpenRouter'da YOK → 404. En sık yapılan hata.
        dogrula(f"{anahtar} tarihsiz", not any(
            p in slug for p in ("-2024", "-2025", "-2026")), slug)

dogrula("triyaj modeli Haiku 4.5 (değişmedi)",
        AYARLAR["model_triyaj"].endswith("claude-haiku-4.5"),
        AYARLAR["model_triyaj"])
dogrula("yazım modeli Sonnet 5 (değişmedi)",
        AYARLAR["model_yazim"].endswith("claude-sonnet-5"),
        AYARLAR["model_yazim"])


# ============================================================
# 5) AKIL_YURUTEN — yazım bütçesi geniş limiti seçiyor mu?
# ============================================================
# pipeline.yaz içindeki liste güncellenmezse yazım dar bütçeyle çalışır ve
# uzun JSON ortadan kesilir. Bunu ADI geçen listeyi kopyalayarak değil,
# gerçek yaz() çağrısındaki max_tokens'ı yakalayarak sınıyoruz.
_gercek_cagri = llm.llm_cagri
yakalanan = {}


def _sahte_cagri(model, sistem, kullanici, max_tokens, stream=False, cache=False):
    yakalanan["model"] = model
    yakalanan["max_tokens"] = max_tokens
    yakalanan["stream"] = stream
    return json.dumps({
        "stories": [{"id": "olay-1", "title": "Baslik", "secim": "one_cikan",
                     "kategori": "politika"}],
        "radar": [{"tema": "Tema", "maddeler": [{"baslik": "Madde"}]}],
        "brief": ["madde"],
    })


llm.llm_cagri = _sahte_cagri
derin = [{"event_key": "olay-1", "kategori": "politika", "puan": 80,
          "olgunluk": "karar", "baslik_ozet": "Ozet", "sirketler": [],
          "ulkeler": ["AB"],
          "kaynaklar": [{"name": "K", "domain": "ec.europa.eu",
                         "url": "https://ec.europa.eu/x",
                         "published_date": "2026-09-17", "primary": True,
                         "paywall": False, "text": "metin"}]}]
radar = [{"event_key": "r1", "kategori": "biyoyakit", "baslik_ozet": "R",
          "kaynaklar": [{"name": "K", "domain": "reuters.com",
                         "url": "https://reuters.com/x",
                         "published_date": "2026-09-18", "primary": True}]}]
try:
    b = pipeline.yaz(derin, radar, 999, "2026-09-15", "2026-09-22",
                     AYARLAR["pencere_gun"])
    dogrula("yaz() config modelini kullandı",
            yakalanan.get("model") == AYARLAR["model_yazim"],
            str(yakalanan.get("model")))
    dogrula("yazım akışlı çağrıldı", yakalanan.get("stream") is True)
    dogrula("yazım GENİŞ bütçeyle çağrıldı (AKIL_YURUTEN kapsıyor)",
            yakalanan.get("max_tokens")
            == AYARLAR["max_tokens_yazim_reasoning"],
            f"{yakalanan.get('max_tokens')} != "
            f"{AYARLAR['max_tokens_yazim_reasoning']}")
    dogrula("yaz() çıktısı doğrulamayı geçti",
            pipeline.yazim_eksik(b, derin, radar) is None)
finally:
    llm.llm_cagri = _gercek_cagri


# ============================================================
# 6) Gerçek maliyet muhasebesi
# ============================================================
llm.KULLANIM.clear()
llm.kullanim_ekle("openrouter:anthropic/claude-sonnet-5",
                  {"input_tokens": 1000, "output_tokens": 500, "cost": 0.0123})
rapor, toplam = llm.maliyet_raporu()
dogrula("usage.cost muhasebeye girdi", abs(toplam - 0.0123) < 1e-9, str(toplam))
dogrula("rapor 'gerçek' diyor", "(gerçek)" in rapor)

llm.KULLANIM.clear()
llm.kullanim_ekle("openrouter:anthropic/claude-sonnet-5",
                  {"input_tokens": 1_000_000, "output_tokens": 0})   # cost YOK
rapor, toplam = llm.maliyet_raporu()
dogrula("cost yoksa FIYAT tahminine düşer", abs(toplam - 2.00) < 1e-6,
        str(toplam))
dogrula("rapor 'tahmin' diyor", "(tahmin)" in rapor)


# ============================================================
# 7) AKIŞTA UTF-8 — Türkçe karakter bozulması (22 Eylül 2026 vakası)
# ============================================================
# OpenRouter'ın SSE yanıtı Content-Type'ta charset bildirmiyor. requests bu
# durumda RFC 2616 gereği ISO-8859-1 varsayıyor ve iter_lines(decode_unicode)
# gövdeyi o kodlamayla çözüyor → "güncellenmiş" yerine "gÃ¼ncellenmiÅ".
# Anthropic charset bildirdiği için bu hata doğrudan yolda hiç görünmedi.
# Bültenin TAMAMI bu yoldan geçtiği için sessiz ama yıkıcı bir hata.
TURKCE = "AB güncellenmiş çerçeveyi kabul etti — çığır açıcı bir karar oldu."


class _SahteAkisYaniti:
    """requests.Response'un akış davranışını taklit eder: iter_lines,
    decode_unicode=True iken gövdeyi self.encoding'e göre çözer."""
    status_code = 200
    encoding = "ISO-8859-1"        # ← charset bildirmeyen sunucunun sonucu

    def __init__(self, metin):
        olaylar = [
            {"type": "message_start",
             "message": {"usage": {"input_tokens": 10}}},
            {"type": "content_block_delta",
             "delta": {"type": "text_delta", "text": metin}},
            {"type": "message_delta", "usage": {"output_tokens": 5}},
        ]
        self._satirlar = [
            ("data: " + json.dumps(o, ensure_ascii=False)).encode("utf-8")
            for o in olaylar]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self, decode_unicode=False):
        for ham in self._satirlar:
            yield (ham.decode(self.encoding, errors="replace")
                   if decode_unicode else ham)


def _akis_post(url, headers=None, json=None, stream=False, timeout=None, **kw):
    return _SahteAkisYaniti(TURKCE)


llm.requests.post = _akis_post
_metin = llm.llm_cagri("openrouter:anthropic/claude-sonnet-5", "S", "K", 100,
                       stream=True)
dogrula("akışta Türkçe karakterler bozulmuyor", _metin == TURKCE,
        repr(_metin[:70]))
dogrula("mojibake imzası yok (Ã / Å)",
        "Ã" not in _metin and "Å" not in _metin, repr(_metin[:70]))


llm.requests.post = _gercek_post
llm.KULLANIM.clear()


# ============================================================
print("=" * 62)
if KALAN:
    for s in KALAN:
        print(f"  ✗ {s}")
    print(f"{GECEN}/{GECEN + len(KALAN)} geçti — {len(KALAN)} KALDI")
    sys.exit(1)
print(f"openrouter_birim_testi: {GECEN}/{GECEN} geçti")
