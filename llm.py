# -*- coding: utf-8 -*-
"""
BİYOEKONOMİ BÜLTENİ — LLM KATMANI
=====================================
Sağlayıcı-bağımsız tek arayüz:

    from llm import llm_cagri
    metin = llm_cagri("anthropic:claude-sonnet-4-6", sistem, kullanici,
                      max_tokens=24000, stream=True)

Model adı "saglayici:model" biçimindedir:
    anthropic:claude-haiku-4-5-20251001   → Anthropic Messages API
    openai:gpt-5-mini                     → OpenAI Chat Completions API

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

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

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
                                    "cagri": 0})
    k["in"] += u.get("input_tokens", 0)
    k["out"] += u.get("output_tokens", 0)
    k["cache_w"] += u.get("cache_creation_input_tokens", 0)
    k["cache_r"] += u.get("cache_read_input_tokens", 0)
    k["cagri"] += 1


def maliyet_raporu():
    satirlar, toplam = [], 0.0
    for model, k in KULLANIM.items():
        f = FIYAT.get(model)
        if not f:
            satirlar.append(f"  {model}: fiyat bilinmiyor")
            continue
        m = (k["in"] * f["in"] + k["out"] * f["out"]
             + k["cache_w"] * f["cache_w"] + k["cache_r"] * f["cache_r"]) / 1_000_000
        toplam += m
        satirlar.append(
            f"  {model}  ({k['cagri']} çağrı)\n"
            f"    girdi {k['in']:,} · çıktı {k['out']:,} · "
            f"cache yaz {k['cache_w']:,} · cache oku {k['cache_r']:,}\n"
            f"    ≈ ${m:.3f}"
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
    if ad.startswith("claude-haiku"):
        return False
    if ad.startswith("claude-sonnet-4-5"):
        return False
    return ad.startswith(("claude-sonnet-4-6", "claude-sonnet-5",
                          "claude-opus-", "claude-fable-", "claude-mythos-"))


def _parcala(model):
    """'anthropic:claude-...' → ('anthropic', 'claude-...')"""
    if ":" not in model:
        raise ValueError(f"Model adı 'saglayici:model' biçiminde olmalı: {model}")
    saglayici, ad = model.split(":", 1)
    if saglayici not in ("anthropic", "openai"):
        raise ValueError(f"Bilinmeyen sağlayıcı: {saglayici}")
    return saglayici, ad


def llm_cagri(model, sistem, kullanici, max_tokens, stream=False, cache=False):
    """Tek arayüz. Dönen değer: modelin ürettiği metin (str)."""
    saglayici, ad = _parcala(model)
    if saglayici == "anthropic":
        return _anthropic(model, ad, sistem, kullanici, max_tokens, stream, cache)
    return _openai(model, ad, sistem, kullanici, max_tokens, stream)


# ============================================================
# ANTHROPIC — Messages API (ham HTTP; yarı iletken bülteninden kanıtlanmış)
# ============================================================
def _anthropic(model, ad, sistem, kullanici, max_tokens, stream, cache):
    """stream=True → UZUN çıktılarda ZORUNLU: akışsız istekte bağlantı
    300 sn'de zaman aşımına uğruyor. Bülten yazımı 5 dk'yı aşabiliyor.

    cache=True → sistem promptu cache'lenir. SADECE aynı sistem promptu
    birden çok kez gönderildiğinde işe yarar (triyaj partileri).
    Tek çağrılık yazımda cache yazmak net zarardır.
    """
    if not ANTHROPIC_API_KEY:
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

    basliklar = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    for deneme in range(4):
        try:
            if not stream:
                r = requests.post(ANTHROPIC_URL, headers=basliklar, json=body, timeout=300)
                if r.status_code == 200:
                    d = r.json()
                    kullanim_ekle(model, d.get("usage", {}))
                    return "".join(b.get("text", "") for b in d.get("content", [])
                                   if b.get("type") == "text")
                _log(f"Anthropic {r.status_code}: {r.text[:200]}")
                if r.status_code in (429, 529, 500, 502, 503):
                    time.sleep(15 * (deneme + 1))
                    continue
                break

            # ── STREAMING ──
            parcalar, u = [], {}
            with requests.post(ANTHROPIC_URL, headers=basliklar, json=body,
                               stream=True, timeout=(30, 120)) as r:
                if r.status_code != 200:
                    _log(f"Anthropic {r.status_code}: {r.text[:200]}")
                    if r.status_code in (429, 529, 500, 502, 503):
                        time.sleep(15 * (deneme + 1))
                        continue
                    break
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
            _log(f"Anthropic hata ({deneme+1}/4): {e}")
            time.sleep(10 * (deneme + 1))

    raise RuntimeError("Anthropic API başarısız")


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
