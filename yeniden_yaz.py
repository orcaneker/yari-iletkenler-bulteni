# -*- coding: utf-8 -*-
"""
YARI İLETKENLER BÜLTENİ — YAZIMI YENİDEN ÇALIŞTIR (model kıyası)
=================================================================
Var olan bir sayının HABERLERİNİ, aynı kaynaklar üzerinden başka bir
yazım modeliyle yeniden yazar. Exa araması ve triyaj TEKRAR ÇALIŞMAZ —
haberler, kaynaklar ve seçim aynı kalır; değişen tek şey metni yazan model.

Neden ayrı bir araç: pipeline'daki KARSILASTIR_MODEL boru hattının TAMAMINI
baştan çalıştırır (yeni Exa araması + yeni triyaj) — çıkan haberler farklı
olur, dolayısıyla iki model kıyaslanamaz. Bu araç aynı girdiyi kullanır.

Kaynak metinleri taslakta saklanmaz (pipeline kaydetmeden önce siler), bu
yüzden Exa'nın /contents uç noktasından URL ile yeniden çekilir. Tek istek,
birkaç sent.

KULLANIM
--------
  # 1) Mevcut taslağı okunaklı metne dök (model çağrısı YOK, ücretsiz)
  python yeniden_yaz.py --girdi kiyas/sayi2-sonnet5.json --sadece-dok

  # 2) Aynı kaynaklarla Terra medium ile yeniden yaz
  python yeniden_yaz.py --girdi kiyas/sayi2-sonnet5.json \
      --model openai:gpt-5.6-terra --effort medium --cikti kiyas/sayi2-terra-medium

  # 3) Terra high
  python yeniden_yaz.py --girdi kiyas/sayi2-sonnet5.json \
      --model openai:gpt-5.6-terra --effort high --cikti kiyas/sayi2-terra-high

  # 4) İki (veya daha fazla) çıktıyı yan yana koy
  python yeniden_yaz.py --kiyas kiyas/sayi2-sonnet5.json \
      kiyas/sayi2-terra-medium.json kiyas/sayi2-terra-high.json

  # Girdiyi Neon'dan almak (DATABASE_URL gerekir):
  python yeniden_yaz.py --hafta 2026-H32 --model ... --cikti ...

  # Beğenilen çıktıyı taslağa GERİ YAZMAK (dikkat — üzerine yazar):
  python yeniden_yaz.py --geri-yaz kiyas/sayi2-terra-high.json --hafta 2026-H32

GEREKEN ANAHTARLAR
------------------
  EXA_API_KEY                      kaynak metinlerini yeniden çekmek için
  OPENAI_API_KEY / ANTHROPIC_API_KEY   seçilen modele göre
  DATABASE_URL                     yalnızca --hafta / --geri-yaz kullanılırsa
"""

import os
import re
import sys
import json
import time
import argparse

import requests

# config import edilir edilmez repo kökündeki .env ortama yüklenir —
# llm ve pipeline anahtarları import anında okuduğu için sıra önemli.
from config import AYARLAR, FIYAT
import prompts
import llm
import pipeline
from pipeline import (
    url_normalize, domain_of, kaynak_tier, odeme_duvarli, temizle,
    json_ayikla, kaynaklari_sabitle, varlik_denetimi, dogrula_taslak, log,
)

EXA_CONTENTS_URL = "https://api.exa.ai/contents"
EXA_MALIYET = {"istek": 0, "bildirilen": 0.0}


# ============================================================
# GİRDİ — dosya veya Neon
# ============================================================
def taslak_yukle(girdi=None, hafta=None):
    """Dönen: (taslak_gövdesi, etiket).

    İnceleme servisinin /api/{token}/draft çıktısı {"taslak": {...}} sarmalıdır;
    Neon'daki draft_json ise doğrudan gövdedir. İkisi de kabul edilir.
    """
    if girdi:
        with open(girdi, encoding="utf-8") as f:
            d = json.load(f)
        govde = d.get("taslak") if isinstance(d.get("taslak"), dict) else d
        return govde, os.path.basename(girdi)

    import db
    sayi = db.issue_getir(hafta=hafta)
    if not sayi:
        sys.exit(f"Sayı bulunamadı: {hafta}")
    govde = sayi["draft_json"]
    if isinstance(govde, str):
        govde = json.loads(govde)
    return govde, f"neon:{hafta}"


# ============================================================
# KAYNAK METİNLERİ — Exa /contents ile yeniden çek
# ============================================================
def kaynak_metinleri_cek(urls):
    """URL → {"title":…, "text":…}. Exa 100 URL'e kadar tek istek alır.

    Metin bulunamayan URL sözlükte yer ALMAZ; çağıran boş metinle baş eder
    (o kaynak prompta konmaz, haber yine de yazılır)."""
    if not urls:
        return {}
    if not os.environ.get("EXA_API_KEY"):
        sys.exit("EXA_API_KEY tanımlı değil — kaynak metinleri çekilemez")

    sonuc = {}
    for i in range(0, len(urls), 100):
        parca = urls[i:i + 100]
        payload = {
            "urls": parca,
            "text": {"maxCharacters": AYARLAR["exa_metin_karakter"]},
        }
        for deneme in range(3):
            try:
                EXA_MALIYET["istek"] += 1
                r = requests.post(
                    EXA_CONTENTS_URL,
                    headers={"x-api-key": os.environ["EXA_API_KEY"],
                             "Content-Type": "application/json"},
                    json=payload, timeout=120)
                if r.status_code == 200:
                    veri = r.json()
                    bildirilen = pipeline._exa_bildirilen_maliyet(veri)
                    if bildirilen is not None:
                        EXA_MALIYET["bildirilen"] += bildirilen
                    for res in veri.get("results", []):
                        u = res.get("url") or res.get("id")
                        if u:
                            sonuc[url_normalize(u)] = {
                                "title": res.get("title") or "",
                                "text": temizle(res.get("text") or ""),
                            }
                    break
                log(f"  Exa contents {r.status_code}: {r.text[:160]}")
            except Exception as e:
                log(f"  Exa contents hata ({deneme+1}/3): {e}")
            time.sleep(3 * (deneme + 1))
    log(f"Kaynak metni çekildi: {len(sonuc)}/{len(urls)} URL")
    return sonuc


# ============================================================
# OLAYLARI GERİ KUR — story → yazım promptunun beklediği olay bloğu
# ============================================================
def olaylari_kur(taslak, metinler):
    """Dönen: (derin, radar_havuz).

    baslik_ozet için ÖNCE Exa'nın döndürdüğü ORİJİNAL başlık kullanılır.
    Eski modelin Türkçe başlığını kullanmak yeni modele onun cümle kurgusunu
    sızdırır ve kıyası bozar — kaynağa sadık kalmak şart.
    """
    derin = []
    for s in (taslak.get("stories") or []):
        birincil = (s.get("source") or {}).get("url")
        if not birincil:
            log(f"  ! kaynağı yok, atlandı: {(s.get('title') or '?')[:50]}")
            continue

        kaynaklar = []
        satirlar = [(birincil, True)] + [(x.get("url"), False)
                                         for x in (s.get("supporting_sources") or [])
                                         if x.get("url")]
        for u, primary in satirlar:
            m = metinler.get(url_normalize(u), {})
            dom = domain_of(u)
            metin = m.get("text") or ""
            kaynaklar.append({
                "name": dom, "domain": dom, "url": u,
                "published_date": s.get("published_date") if primary else None,
                "text": metin, "image": None, "tier": kaynak_tier(dom),
                "paywall": odeme_duvarli(dom, metin), "primary": primary,
            })

        if not (kaynaklar[0].get("text") or "").strip():
            log(f"  ! birincil kaynak metni boş: {(s.get('title') or '?')[:50]} "
                f"[{kaynaklar[0]['domain']}]")

        derin.append({
            "event_key": s.get("id"),
            "kategori": s.get("category"),
            "puan": s.get("score") or 5,
            "olgunluk": s.get("maturity"),
            "baslik_ozet": (metinler.get(url_normalize(birincil), {}).get("title")
                            or s.get("title") or ""),
            "sirketler": s.get("companies") or [],
            "ulkeler": s.get("countries") or [],
            "ikinci_el": False,
            "kaynaklar": kaynaklar,
            "sadece_radar": False,
        })

    # radar: mevcut maddeler olduğu gibi radar havuzuna döner (metin gerekmez)
    radar_havuz = []
    for kume in (taslak.get("radar") or []):
        for m in kume.get("maddeler", []):
            if not m.get("url"):
                continue
            dom = domain_of(m["url"])
            radar_havuz.append({
                "event_key": f"radar-{len(radar_havuz)}",
                "kategori": m.get("category") or "rapor",
                "puan": 3, "olgunluk": None,
                "baslik_ozet": m.get("title") or "",
                "sirketler": [], "ulkeler": [],
                "kaynaklar": [{"name": m.get("source") or dom, "domain": dom,
                               "url": m["url"], "published_date": m.get("date"),
                               "text": "", "image": None, "tier": kaynak_tier(dom),
                               "paywall": False, "primary": True}],
            })
    return derin, radar_havuz


# ============================================================
# YENİDEN YAZIM
# ============================================================
def yeniden_yaz(taslak, model, derin, radar_havuz):
    issue = taslak.get("issue") or {}
    yeni = pipeline.yaz(
        derin, radar_havuz,
        issue.get("number") or 0,
        issue.get("coverage_start") or "", issue.get("coverage_end") or "",
        issue.get("window_days") or AYARLAR["pencere_gun"],
        model=model)

    notlar, dusenler = kaynaklari_sabitle(yeni, derin, radar_havuz)
    notlar += varlik_denetimi(yeni)
    hatalar = dogrula_taslak(yeni, issue.get("coverage_start"),
                             issue.get("coverage_end"))

    # Görselleri eski taslaktan taşı — görsel yazım modeliyle ilgisiz, yeniden
    # çekmek gereksiz istek demek. Eşleme id, olmazsa birincil kaynak URL'i ile.
    eski_id = {s.get("id"): s for s in (taslak.get("stories") or [])}
    eski_url = {url_normalize((s.get("source") or {}).get("url") or ""): s
                for s in (taslak.get("stories") or [])}
    for s in (yeni.get("stories") or []):
        e = eski_id.get(s.get("id")) or eski_url.get(
            url_normalize((s.get("source") or {}).get("url") or ""))
        if e and (e.get("image") or {}).get("url"):
            s["image"] = e["image"]
        s.pop("_kaynak_metni", None)

    return {
        "issue": issue,
        "brief": yeni.get("brief", []),
        "lead_id": yeni.get("lead_id"),
        "stories": yeni.get("stories", []),
        "radar": yeni.get("radar", []),
        "hatalar": hatalar,
        "_model": model,
        "_notlar": notlar,
        "_dusen": dusenler,
    }


# ============================================================
# OKUNAKLI DÖKÜM
# ============================================================
def _olcum(taslak):
    st = taslak.get("stories") or []
    if not st:
        return {"haber": 0, "exc": 0, "det": 0, "rakam": 0, "radar": 0}
    exc = [len(s.get("excerpt") or "") for s in st]
    det = [len(s.get("detail") or "") for s in st]
    rak = [len(re.findall(r"\d", (s.get("excerpt") or "") + (s.get("detail") or "")))
           for s in st]
    return {
        "haber": len(st),
        "exc": round(sum(exc) / len(exc)),
        "det": round(sum(det) / len(det)),
        "rakam": round(sum(rak) / len(rak), 1),
        "radar": sum(len(k.get("maddeler", [])) for k in (taslak.get("radar") or [])),
    }


def okunakli_dok(taslak, yol, etiket=""):
    o = _olcum(taslak)
    p = [f"{'=' * 72}",
         f"{etiket or taslak.get('_model') or 'taslak'}",
         f"{'=' * 72}",
         f"haber {o['haber']} · radar {o['radar']} · ort. özet {o['exc']} krkt · "
         f"ort. metin {o['det']} krkt · haber başına rakam {o['rakam']}",
         ""]
    p.append("── BU HAFTA 60 SANİYEDE ──")
    for i, m in enumerate(taslak.get("brief") or [], 1):
        p.append(f"{i}. {m.get('text') if isinstance(m, dict) else m}")
    p.append("")
    for s in (taslak.get("stories") or []):
        manset = "  ★ MANŞET" if s.get("id") == taslak.get("lead_id") else ""
        p += [f"{'─' * 72}",
              f"[{s.get('category')}] {s.get('title')}{manset}",
              f"id: {s.get('id')} · kaynak: {(s.get('source') or {}).get('url')}",
              "",
              f"ÖZET:\n{s.get('excerpt')}",
              "",
              f"METİN:\n{s.get('detail')}",
              ""]
    if taslak.get("radar"):
        p.append(f"{'─' * 72}\nRADAR")
        for k in taslak["radar"]:
            p.append(f"\n  ▸ {k.get('kume')}")
            for m in k.get("maddeler", []):
                p.append(f"    - {m.get('title')}  ({m.get('source')})")
    if taslak.get("hatalar"):
        p += ["", f"{'─' * 72}", "ŞEMA UYARILARI:"] + \
             [f"  ! {h}" for h in taslak["hatalar"]]
    if taslak.get("_dusen"):
        p += ["", "YAYINDAN DÜŞEN (kaynağı doğrulanamadı):"] + \
             [f"  ✗ {t}" for t in taslak["_dusen"]]

    with open(yol, "w", encoding="utf-8") as f:
        f.write("\n".join(p))
    return yol


def kiyas_dok(yollar, cikti, etiketler=None, baslik=None):
    """N taslağı haber haber yan yana koyar. Eşleme birincil kaynak URL'i ile —
    story id'leri modelden modele değişebilir, URL değişmez.

    etiketler: sütun adları. Verilmezse _model alanı kullanılır — ama AYNI
    modelin iki sürümü kıyaslanırken (prompt değişikliği gibi) o alan ikisinde
    de aynı olur ve sütunlar ayırt edilemez; o durumda etiket ZORUNLUDUR.
    """
    taslaklar, otomatik = [], []
    for y in yollar:
        t, ad = taslak_yukle(girdi=y)
        taslaklar.append(t)
        otomatik.append(t.get("_model") or ad)
    etiketler = list(etiketler) if etiketler else otomatik
    if len(etiketler) != len(taslaklar):
        raise ValueError(f"{len(taslaklar)} dosyaya {len(etiketler)} etiket verildi")

    idx = [{url_normalize((s.get("source") or {}).get("url") or ""): s
            for s in (t.get("stories") or [])} for t in taslaklar]
    ortak = [u for u in idx[0] if all(u in d for d in idx[1:])]

    p = [f"{'=' * 72}",
         baslik or "MODEL KIYASI — aynı haberler, farklı yazım modelleri",
         f"{'=' * 72}"]
    for e, t in zip(etiketler, taslaklar):
        o = _olcum(t)
        p.append(f"  {e:38} haber {o['haber']:>2} · radar {o['radar']:>2} · "
                 f"özet {o['exc']:>4} · metin {o['det']:>5} krkt · rakam {o['rakam']:>4}")
    p += ["", f"Kıyaslanabilir (aynı kaynaklı) haber: {len(ortak)}", ""]

    for i, u in enumerate(ortak, 1):
        p += [f"{'━' * 72}", f"HABER {i} — {u}", f"{'━' * 72}"]
        for e, d in zip(etiketler, idx):
            s = d[u]
            p += [f"", f"┌─ {e} ─" + "─" * max(0, 66 - len(e)),
                  f"BAŞLIK: {s.get('title')}",
                  f"ÖZET  : {s.get('excerpt')}",
                  f"METİN :", s.get("detail") or "", ""]
    with open(cikti, "w", encoding="utf-8") as f:
        f.write("\n".join(p))
    return cikti


# ============================================================
# CLI
# ============================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--girdi", help="taslak JSON dosyası")
    ap.add_argument("--hafta", help="Neon'dan çek (ör. 2026-H32)")
    ap.add_argument("--model", help="ör. openai:gpt-5.6-terra")
    ap.add_argument("--effort", help="none|low|medium|high|xhigh|max — config'i ezer")
    ap.add_argument("--cikti", help="çıktı dosyası ön eki (.json ve .txt üretilir)")
    ap.add_argument("--sadece-dok", action="store_true",
                    help="model çağırma, sadece okunaklı metne dök")
    ap.add_argument("--kiyas", nargs="+", help="verilen taslakları yan yana koy")
    ap.add_argument("--etiketler", nargs="+",
                    help="--kiyas sütun adları (dosya sayısı kadar)")
    ap.add_argument("--kiyas-baslik", help="--kiyas dosyasının başlığı")
    ap.add_argument("--geri-yaz", help="bu JSON'u taslağa geri yaz (--hafta gerekir)")
    ap.add_argument("--kontrol", action="store_true",
                    help="anahtarlar yüklendi mi diye bak (değerleri YAZMAZ)")
    args = ap.parse_args()

    llm.set_logger(lambda m: print(m))

    # ── anahtar kontrolü — değerler ASLA ekrana basılmaz ──
    if args.kontrol:
        for k in ("EXA_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            v = os.environ.get(k, "")
            if not v or v == "BURAYA_YAPISTIR":
                print(f"  {k:20} ✗ EKSİK")
            else:
                print(f"  {k:20} ✓ yüklendi ({len(v)} karakter)")
        for k in ("MODEL_YAZIM", "REASONING_EFFORT"):
            print(f"  {k:20} = {os.environ.get(k) or '(tanımsız → config kullanılır)'}")
        return

    # ── yalnızca kıyas dökümü ──
    if args.kiyas:
        yol = kiyas_dok(args.kiyas, (args.cikti or "kiyas/KIYAS") + ".txt",
                        args.etiketler, args.kiyas_baslik)
        print(f"Kıyas metni → {yol}")
        return

    # ── Neon'a geri yazma ──
    if args.geri_yaz:
        if not args.hafta:
            sys.exit("--geri-yaz için --hafta gerekli")
        import db
        with open(args.geri_yaz, encoding="utf-8") as f:
            yeni = json.load(f)
        sayi = db.issue_getir(hafta=args.hafta)
        if not sayi:
            sys.exit(f"Sayı bulunamadı: {args.hafta}")
        govde = {k: v for k, v in yeni.items() if not k.startswith("_")}
        db.govde_guncelle(sayi["id"], "draft_json", govde)
        print(f"Taslak güncellendi (issue_id={sayi['id']}, hafta={args.hafta})")
        return

    if not (args.girdi or args.hafta):
        sys.exit("--girdi veya --hafta gerekli")

    taslak, etiket = taslak_yukle(args.girdi, args.hafta)
    print(f"Girdi: {etiket} — {len(taslak.get('stories') or [])} haber, "
          f"{sum(len(k.get('maddeler', [])) for k in (taslak.get('radar') or []))} radar")

    if args.sadece_dok:
        yol = (args.cikti or "kiyas/taslak") + ".txt"
        okunakli_dok(taslak, yol, etiket)
        print(f"Döküm → {yol}")
        return

    if not args.model:
        sys.exit("--model gerekli (ör. openai:gpt-5.6-terra)")
    if args.model not in FIYAT:
        print(f"⚠ {args.model} FIYAT tablosunda yok — maliyet raporlanamayacak")
    if args.effort:
        os.environ["REASONING_EFFORT"] = args.effort

    urls = []
    for s in (taslak.get("stories") or []):
        u = (s.get("source") or {}).get("url")
        if u:
            urls.append(u)
        urls += [x["url"] for x in (s.get("supporting_sources") or []) if x.get("url")]
    urls = list(dict.fromkeys(urls))
    print(f"Kaynak metni çekiliyor — {len(urls)} URL…")
    metinler = kaynak_metinleri_cek(urls)

    derin, radar_havuz = olaylari_kur(taslak, metinler)
    print(f"Yazıma giden: {len(derin)} derin olay + {len(radar_havuz)} radar adayı")
    print(f"Model: {args.model} · effort={os.environ.get('REASONING_EFFORT') or AYARLAR.get('reasoning_effort')}")

    t0 = time.time()
    yeni = yeniden_yaz(taslak, args.model, derin, radar_havuz)

    on_ek = args.cikti or f"kiyas/{args.model.replace(':', '-')}"
    os.makedirs(os.path.dirname(on_ek) or ".", exist_ok=True)
    with open(on_ek + ".json", "w", encoding="utf-8") as f:
        json.dump(yeni, f, ensure_ascii=False, indent=2)
    okunakli_dok(yeni, on_ek + ".txt",
                 f"{args.model} (effort={os.environ.get('REASONING_EFFORT') or AYARLAR.get('reasoning_effort')})")

    o = _olcum(yeni)
    mm, mt = llm.maliyet_raporu()
    exa_m = EXA_MALIYET["bildirilen"] or EXA_MALIYET["istek"] * 0.007
    print(f"\n{'─' * 60}")
    print(f"haber {o['haber']} · radar {o['radar']} · ort. özet {o['exc']} krkt · "
          f"ort. metin {o['det']} krkt · haber başına rakam {o['rakam']}")
    for n in (yeni.get("_notlar") or [])[:15]:
        print(f"  · {n}")
    for h in (yeni.get("hatalar") or [])[:15]:
        print(f"  ! {h}")
    print(mm)
    print(f"  Exa contents ≈ ${exa_m:.3f}")
    print(f"  ══ TOPLAM ≈ ${mt + exa_m:.3f}   ({time.time() - t0:.0f} sn)")
    print(f"Çıktı → {on_ek}.json · {on_ek}.txt")


if __name__ == "__main__":
    main()
