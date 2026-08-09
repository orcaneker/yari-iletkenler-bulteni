# -*- coding: utf-8 -*-
"""Araçların ortak yol çözümü.

Bu klasördeki betikler repo kökünden İKİ dizin aşağıda duruyor; hem repo
modüllerini (pipeline, yeniden_yaz…) import edebilmeleri hem de kayıtlı
model çıktılarını bulabilmeleri için yolları buradan alırlar.

    from yollar import KOK, CIKTI
"""
import os
import sys

ARACLAR = os.path.dirname(os.path.abspath(__file__))
DENEMELER = os.path.dirname(ARACLAR)
KOK = os.path.dirname(DENEMELER)                 # repo kökü
CIKTI = os.path.join(DENEMELER, "model-kiyasi-2026-08", "ciktilar")

if KOK not in sys.path:
    sys.path.insert(0, KOK)


def veri(ad):
    """Kayıtlı model çıktısının tam yolu."""
    return os.path.join(CIKTI, ad)
