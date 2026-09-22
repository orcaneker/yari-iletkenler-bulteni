# -*- coding: utf-8 -*-
"""
BİYOEKONOMİ BÜLTENİ — LLM KATMANI
=====================================
Sağlayıcı-bağımsız tek arayüz:

    from llm import llm_cagri
    metin = llm_cagri("anthropic:claude-sonnet-4-6", sistem, kullanici,
                      max_tokens=24000, stream=True)

Model adı "saglayici:model" biçimindedir:
    openrouter:anthropic/claude-sonnet-5  → OpenRouter geçidi (VARSAYILAN)
    anthropic:claude-haiku-4-5-20251001   → doğrudan Anthropic Messages API
    openai:gpt-5-mini                     → OpenAI Chat Completions API

openrouter: ve anthropic: AYNI istek gövdesini kullanır — OpenRouter'ın
/api/v1/messages ucu Anthropic Messages API şemasını birebir kabul eder
(system bloğu, cache_control, output_config ve Anthropic SSE olayları dahil).
Değişen tek şey: URL, kimlik başlığı ve model adının yazımı — OpenRouter'da
org öneki + noktalı sürüm ("anthropic/claude-sonnet-5", "anthropic/claude-haiku-4.5");
Anthropic'in tarihli kimlikleri (…-20251001) OpenRouter'da YOKTUR, 404 döner.

OpenAI denemek için OPENAI_API_KEY tanımla ve config.py'de modeli değiştir.
temperature parametresi BİLEREK gönderilmiyor (model uyumsuzluk deneyimi).
"""

import os
import json
import time
from datetime import datetime, timezone

import requests

from config import FIYAT, AYARLAR as _A

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# OpenRouter'ın Anthropic-uyumlu ucu — OpenAI formatındaki /chat/completions
# DEĞİL. Bu uç sayesinde Anthropic gövdesi hiç dönüştürülmeden gönderilir.
OPENROUTER_URL = "https://openrouter.ai/api/v1/messages"

# Token muhasebesi — model bazında birikir, çalışma raporuna yazılır
KULLANIM = {}

_log_fn = print


def set_logger(fn):
    """pipeline.py kendi log() fonksiyonunu bağlar."""
    global _log_fn
    _log_fn = fn


def _log(msg):
    _log_fn(f"  {msg}")


def kullanim_ekle(model, u):
    k = KULLANIM.setdefault(model, {"in": 0, "out": 0, "cache_w": 0, "cache_r": 0,
                                    "cagri": 0, "cost": 0.0})
    k["in"] += u.get("input_tokens", 0)
    k["out"] += u.get("output_tokens", 0)
    k["cache_w"] += u.get("cache_creation_input_tokens", 0)
    k["cache_r"] += u.get("cache_read_input_tokens", 0)
    # OpenRouter usage'a "cost" (USD, faturalanan gerçek tutar) ekler.
    # Anthropic/OpenAI eklemez → 0 kalır ve FIYAT tahmini devreye girer.
    k["cost"] = k.get("cost", 0.0) + (u.get("cost") or 0.0)
    k["cagri"] += 1


def maliyet_raporu():
    satirlar, toplam = [], 0.0
    for model, k in KULLANIM.items():
        # OpenRouter gerçek maliyeti bildirir → tahmin yerine onu kullan.
        # Akışlı isteklerde cost gelmezse FIYAT tahminine düşülür; bu yüzden
        # FIYAT tablosundaki openrouter satırları SİLİNMEMELİ.
        gercek = k.get("cost") or 0.0
        f = FIYAT.get(model)
        if gercek:
            m, kaynak = gercek, "gerçek"
        elif f:
            m = (k["in"] * f["in"] + k["out"] * f["out"]
                 + k["cache_w"] * f["cache_w"] + k["cache_r"] * f["cache_r"]) / 1_000_000
            kaynak = "tahmin"
        else:
            satirlar.append(f"  {model}: fiyat bilinmiyor")
            continue
        toplam += m
        satirlar.append(
            f"  {model}  ({k['cagri']} çağrı)\n"
            f"    girdi {k['in']:,} · çıktı {k['out']:,} · "
            f"cache yaz {k['cache_w']:,} · cache oku {k['cache_r']:,}\n"
            f"    ≈ ${m:.3f} ({kaynak})"
        )
    # "model toplamı" — Exa arama maliyeti buna DAHİL DEĞİL; genel toplamı
    # pipeline.py hesaplayıp raporun altına ayrı satır olarak yazar.
    satirlar.append(f"  ── model toplamı ≈ ${toplam:.3f}")
    return "\n".join(satirlar), toplam


def _effort_destekler(ad):
    """Anthropic modeli output_config.effort kabul ediyor mu?

    Kabul EDENLER : Sonnet 4.6 / Sonnet 5, Opus 4.5 ve sonrası, Fable 5
    Kabul ETMEYEN : Haiku 4.5, Sonnet 4.5  → gönderilirse istek hata döner.
    Triyaj Haiku'da çalıştığı için bu ayrım kritik.
    """
    # OpenRouter slug'ı: "anthropic/claude-sonnet-4.6" → "claude-sonnet-4-6".
    # Bu normalizasyon olmadan aşağıdaki startswith kontrolleri tutmaz ve
    # effort SESSİZCE gönderilmez (model varsayılan "high"a düşer, maliyet artar).
    ad = ad.split("/")[-1].replace(".", "-")
    if ad.startswith("claude-haiku"):
        return False
    if ad.startswith("claude-sonnet-4-5"):
        return False
    return ad.startswith(("claude-sonnet-4-6", "claude-sonnet-5",
                          "claude-opus-", "claude-fable-", "claude-mythos-"))


def _openrouter_saglayici():
    """OpenRouter "provider" bloğu — isteği HANGİ altyapının karşılayacağı.

    NEDEN VAR: OpenRouter aynı Claude modelini birden çok altyapıdan sunuyor
    (Anthropic, Amazon Bedrock, Google Vertex, Azure). Model aynı olsa da
    parametre desteği farklı — ör. output_config bazı altyapılarda reddedilir.

    ⚠ 22 Eylül 2026 ÖLÇÜMÜ: kurumsal OpenRouter hesabında Anthropic'in KENDİ
    ucu görünmüyor. {"order": ["anthropic"], "allow_fallbacks": False} ile
    istek 404 "No endpoints found" döndü; yönlendirme hunisi 8 uç → bölge
    filtresi 4 → guardrails 2 → bizim sabitlememiz 0. Sabitleme kalkınca
    isteği Amazon Bedrock karşıladı. Bu yüzden Bedrock TERCİH edilir ama
    kilitlenmez (allow_fallbacks True).
    Ortam değişkeniyle kod değiştirmeden oynanabilir:
        OPENROUTER_SAGLAYICI=serbest          → blok hiç gönderilmez
        OPENROUTER_SAGLAYICI=amazon-bedrock   → tercih; yoksa yedeğe düşer
        OPENROUTER_SAGLAYICI=sadece:anthropic → katı sabitleme (yedek YOK)
    Ortam değişkeni config'deki ayarı EZER.
    """
    ham = os.environ.get("OPENROUTER_SAGLAYICI", "").strip()
    if ham:
        if ham.lower() in ("serbest", "yok", "kapali", "none", "off"):
            return None
        kati = ham.lower().startswith("sadece:")
        if kati:
            ham = ham.split(":", 1)[1]
        return {"order": [p.strip() for p in ham.split(",") if p.strip()],
                "allow_fallbacks": not kati}
    return _A.get("openrouter_saglayici")


def _parcala(model):
    """'anthropic:claude-...' → ('anthropic', 'claude-...')"""
    if ":" not in model:
        raise ValueError(f"Model adı 'saglayici:model' biçiminde olmalı: {model}")
    saglayici, ad = model.split(":", 1)
    if saglayici not in ("anthropic", "openai", "openrouter"):
        raise ValueError(f"Bilinmeyen sağlayıcı: {saglayici}")
    return saglayici, ad


def llm_cagri(model, sistem, kullanici, max_tokens, stream=False, cache=False):
    """Tek arayüz. Dönen değer: modelin ürettiği metin (str)."""
    saglayici, ad = _parcala(model)
    if saglayici in ("anthropic", "openrouter"):
        return _anthropic(model, ad, sistem, kullanici, max_tokens, stream, cache,
                          gecit=saglayici)
    return _openai(model, ad, sistem, kullanici, max_tokens, stream)


# ============================================================
# ANTHROPIC — Messages API (ham HTTP; yarı iletken bülteninden kanıtlanmış)
# ============================================================
def _anthropic(model, ad, sistem, kullanici, max_tokens, stream, cache,
               gecit="anthropic"):
    """gecit="openrouter" → istek OpenRouter'ın Anthropic-uyumlu ucuna gider.
    Gövde AYNI kalır; yalnızca URL, kimlik başlığı ve sağlayıcı bloğu değişir.
    Bu yüzden cache, effort ve akış çözümleme kodu ortaktır.

    stream=True → UZUN çıktılarda ZORUNLU: akışsız istekte bağlantı
    300 sn'de zaman aşımına uğruyor. Bülten yazımı 5 dk'yı aşabiliyor.

    cache=True → sistem promptu cache'lenir. SADECE aynı sistem promptu
    birden çok kez gönderildiğinde işe yarar (triyaj partileri).
    Tek çağrılık yazımda cache yazmak net zarardır.
    """
    etiket = "OpenRouter" if gecit == "openrouter" else "Anthropic"
    if gecit == "openrouter":
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY tanımlı değil")
    elif not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY tanımlı değil")

    if cache:
        sistem_blok = [{"type": "text", "text": sistem,
                        "cache_control": {"type": "ephemeral"}}]
    else:
        sistem_blok = sistem

    body = {
        "model": ad,
        "max_tokens": max_tokens,
        "system": sistem_blok,
        "messages": [{"role": "user", "content": kullanici}],
    }

    # ── EFFORT (output_config.effort) ──
    # Anthropic'te akıl yürütme derinliği bu parametreyle ayarlanır
    # (OpenAI'deki reasoning_effort'un karşılığı; aynı config anahtarını kullanıyoruz).
    # ⚠ HER MODEL DESTEKLEMEZ: Haiku 4.5 ve Sonnet 4.5'e gönderilirse HATA verir —
    # triyaj Haiku'da çalıştığı için bu kapı şart. Sonnet 4.6+/5, Opus 4.5+ ve
    # Fable 5 destekler.
    # ⚠ temperature / top_p / top_k ve thinking.budget_tokens BİLEREK gönderilmiyor:
    # Sonnet 5 ve Opus 4.7+ bunları 400 ile reddediyor.
    seviye = os.environ.get("REASONING_EFFORT", "").strip() or _A.get("reasoning_effort")
    if seviye and _effort_destekler(ad):
        body["output_config"] = {"effort": seviye}
        _log(f"{ad}: effort={seviye}")

    if stream:
        body["stream"] = True

    if gecit == "openrouter":
        url = OPENROUTER_URL
        basliklar = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "Yari Iletkenler Bulteni",   # OpenRouter panelinde görünen ad
        }
        # Sağlayıcı sabitleme — bkz. _openrouter_saglayici(). None ise blok
        # hiç gönderilmez ve seçimi OpenRouter yapar.
        sag = _openrouter_saglayici()
        if sag:
            body["provider"] = sag
    else:
        url = ANTHROPIC_URL
        basliklar = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    for deneme in range(4):
        try:
            if not stream:
                r = requests.post(url, headers=basliklar, json=body, timeout=300)
                if r.status_code == 200:
                    d = r.json()
                    kullanim_ekle(model, d.get("usage", {}))
                    return "".join(b.get("text", "") for b in d.get("content", [])
                                   if b.get("type") == "text")
                _log(f"{etiket} {r.status_code}: {r.text[:200]}")
                if r.status_code in (429, 529, 500, 502, 503):
                    time.sleep(15 * (deneme + 1))
                    continue
                break

            # ── STREAMING ──
            parcalar, u = [], {}
            with requests.post(url, headers=basliklar, json=body,
                               stream=True, timeout=(30, 120)) as r:
                if r.status_code != 200:
                    _log(f"{etiket} {r.status_code}: {r.text[:200]}")
                    if r.status_code in (429, 529, 500, 502, 503):
                        time.sleep(15 * (deneme + 1))
                        continue
                    break
                # ⚠ TÜRKÇE KARAKTER BOZULMASINI ÖNLER — SİLMEYİN.
                # SSE gövdesi her zaman UTF-8'dir (text/event-stream standardı),
                # ama sunucu Content-Type'ta charset bildirmezse requests
                # RFC 2616 gereği ISO-8859-1 varsayar ve iter_lines o kodlamayla
                # çözer: "güncellenmiş" → "gÃ¼ncellenmiÅ".
                # Gerçek vaka (22 Eylül 2026): Anthropic charset bildirdiği için
                # yıllarca görünmedi; OpenRouter bildirmiyor ve ilk denemede
                # bülten metni bozuk çıktı. Akışsız yolda sorun yok — orada
                # r.json() zaten UTF-8 çözüyor.
                r.encoding = "utf-8"
                for satir in r.iter_lines(decode_unicode=True):
                    if not satir or not satir.startswith("data: "):
                        continue
                    veri = satir[6:]
                    if veri.strip() == "[DONE]":
                        break
                    try:
                        olay = json.loads(veri)
                    except Exception:
                        continue
                    tip = olay.get("type")
                    if tip == "content_block_delta":
                        d = olay.get("delta", {})
                        if d.get("type") == "text_delta":
                            parcalar.append(d.get("text", ""))
                    elif tip == "message_start":
                        u.update(olay.get("message", {}).get("usage", {}) or {})
                    elif tip == "message_delta":
                        u.update(olay.get("usage", {}) or {})
                    elif tip == "error":
                        raise RuntimeError(olay.get("error", {}).get("message", "stream hatası"))

            if parcalar:
                kullanim_ekle(model, u)
                _log(f"Stream tamam — {sum(len(p) for p in parcalar)} karakter · "
                     f"girdi {u.get('input_tokens', 0):,} / çıktı {u.get('output_tokens', 0):,}")
                return "".join(parcalar)
            _log("Stream boş döndü")

        except Exception as e:
            _log(f"{etiket} hata ({deneme+1}/4): {e}")
            time.sleep(10 * (deneme + 1))

    raise RuntimeError(f"{etiket} API başarısız")


# ============================================================
# OPENAI — Chat Completions API
# ============================================================
def _openai(model, ad, sistem, kullanici, max_tokens, stream):
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY tanımlı değil — config.py'de openai: modeli seçildi "
            "ama anahtar yok. Render → Environment'a ekleyin.")

    body = {
        "model": ad,
        "max_completion_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": sistem},
            {"role": "user", "content": kullanici},
        ],
    }

    # ── AKIL YÜRÜTME SEVİYESİ (gpt-5.x reasoning modelleri) ──
    # AÇIKÇA gönderilir: gönderilmediğinde model kendi varsayılanını kullanır
    # ve ürettiği "düşünme" token'ları ÇIKTI fiyatından faturalanır — maliyet
    # sessizce katlanabilir. Ayrıca gpt-5.6'da reasoning_effort belirtilmemiş
    # isteklerin bazı durumlarda 400 döndürdüğü bildirildi.
    # Reasoning desteklemeyen eski modellere (gpt-4o vb.) gönderilmez.
    # REASONING_EFFORT ortam değişkeni config'i EZER — model kıyası yaparken
    # seviyeyi Render'dan değiştirip kod dokunmadan tekrar denemek için.
    seviye = os.environ.get("REASONING_EFFORT", "").strip() or _A.get("reasoning_effort")
    if seviye and ad.startswith(("gpt-5", "o1", "o3", "o4")):
        body["reasoning_effort"] = seviye
        _log(f"{ad}: reasoning_effort={seviye}")

    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}

    basliklar = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    for deneme in range(4):
        try:
            if not stream:
                r = requests.post(OPENAI_URL, headers=basliklar, json=body, timeout=300)
                if r.status_code == 200:
                    d = r.json()
                    kullanim_ekle(model, _openai_usage(d.get("usage") or {}))
                    return (d.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
                _log(f"OpenAI {r.status_code}: {r.text[:200]}")
                if r.status_code in (429, 500, 502, 503):
                    time.sleep(15 * (deneme + 1))
                    continue
                break

            # ── STREAMING ──
            parcalar, u = [], {}
            bitis, ham_usage = None, {}
            with requests.post(OPENAI_URL, headers=basliklar, json=body,
                               stream=True, timeout=(30, 120)) as r:
                if r.status_code != 200:
                    _log(f"OpenAI {r.status_code}: {r.text[:200]}")
                    if r.status_code in (429, 500, 502, 503):
                        time.sleep(15 * (deneme + 1))
                        continue
                    break
                # ⚠ TÜRKÇE KARAKTER BOZULMASINI ÖNLER — SİLMEYİN.
                # SSE gövdesi her zaman UTF-8'dir (text/event-stream standardı),
                # ama sunucu Content-Type'ta charset bildirmezse requests
                # RFC 2616 gereği ISO-8859-1 varsayar ve iter_lines o kodlamayla
                # çözer: "güncellenmiş" → "gÃ¼ncellenmiÅ".
                # Gerçek vaka (22 Eylül 2026): Anthropic charset bildirdiği için
                # yıllarca görünmedi; OpenRouter bildirmiyor ve ilk denemede
                # bülten metni bozuk çıktı. Akışsız yolda sorun yok — orada
                # r.json() zaten UTF-8 çözüyor.
                r.encoding = "utf-8"
                for satir in r.iter_lines(decode_unicode=True):
                    if not satir or not satir.startswith("data: "):
                        continue
                    veri = satir[6:]
                    if veri.strip() == "[DONE]":
                        break
                    try:
                        olay = json.loads(veri)
                    except Exception:
                        continue
                    for c in olay.get("choices") or []:
                        icerik = (c.get("delta") or {}).get("content")
                        if icerik:
                            parcalar.append(icerik)
                        if c.get("finish_reason"):
                            bitis = c["finish_reason"]
                    if olay.get("usage"):
                        ham_usage = olay["usage"]
                        u = _openai_usage(ham_usage)

            if parcalar:
                kullanim_ekle(model, u)
                # reasoning modellerinde "düşünme" token'ları çıktıya dahildir;
                # ayrıştırmak maliyeti ve kısa çıktı şüphesini teşhis etmeyi sağlar
                dusunme = ((ham_usage.get("completion_tokens_details") or {})
                           .get("reasoning_tokens")) or 0
                _log(f"Stream tamam — {sum(len(p) for p in parcalar)} karakter · "
                     f"girdi {u.get('input_tokens', 0):,} / çıktı {u.get('output_tokens', 0):,}"
                     + (f" (bunun {dusunme:,}'i düşünme)" if dusunme else ""))
                if bitis == "length":
                    _log("  ⚠ ÇIKTI KESİLDİ (max_completion_tokens doldu) — "
                         "metinler eksik olabilir; limiti artırın")
                return "".join(parcalar)
            _log("Stream boş döndü")

        except Exception as e:
            _log(f"OpenAI hata ({deneme+1}/4): {e}")
            time.sleep(10 * (deneme + 1))

    raise RuntimeError("OpenAI API başarısız")


def _openai_usage(u):
    """OpenAI kullanım alanlarını Anthropic sözlüğüne eşle."""
    cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
    return {
        "input_tokens": (u.get("prompt_tokens") or 0) - cached,
        "output_tokens": u.get("completion_tokens") or 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": cached,
    }
