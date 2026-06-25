#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zara_check.py  (version para GitHub Actions: corre UNA vez y sale)

Lee la config desde variables de entorno (que vos cargas como GitHub Secrets):
    PRODUCT_URL  -> link del producto agotado
    TALLES       -> talles separados por coma, ej: "M,L"
    NTFY_TOPIC   -> tu topic secreto de ntfy
    NTFY_SERVER  -> opcional, por defecto https://ntfy.sh

A diferencia de la version local, NO tiene 'while True': cada vez que el cron
de GitHub lo dispara, revisa una sola vez. Si el talle esta disponible, manda
el push. (Esto significa que si el producto sigue en stock, te va a avisar en
cada corrida; para un restock que dura poco, suele estar bien. Si queres que
avise una sola vez, lo upgradeamos con cache de Actions.)
"""

import os
import sys
import requests
from playwright.sync_api import sync_playwright

PRODUCT_URL = os.environ.get("PRODUCT_URL", "").strip()
TALLES_DESEADOS = [t.strip() for t in os.environ.get("TALLES", "").split(",") if t.strip()]
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip()


def enviar_push(texto, url=None):
    headers = {
        "Title": "Volvio el stock en ZARA",
        "Priority": "urgent",
        "Tags": "rotating_light",
    }
    if url:
        headers["Click"] = url
    try:
        requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}",
                      data=texto.encode("utf-8"), headers=headers, timeout=15)
    except Exception as e:
        print(f"No pude mandar el push: {e}", flush=True)


def leer_disponibilidad(page):
    disponibilidad = page.evaluate(
        """
        () => {
            const visto = new Set();
            const resultado = {};
            const ESTADOS_OK = ['in_stock', 'low_on_stock'];
            function recorrer(obj, prof) {
                if (!obj || prof > 8 || typeof obj !== 'object') return;
                if (visto.has(obj)) return;
                visto.add(obj);
                if (typeof obj.availability === 'string' &&
                    (typeof obj.name === 'string' || obj.size)) {
                    const talle = (obj.name || obj.size || '').toString().trim();
                    if (talle) resultado[talle] = ESTADOS_OK.includes(obj.availability);
                }
                for (const k in obj) { try { recorrer(obj[k], prof + 1); } catch (e) {} }
            }
            for (const k of Object.keys(window)) {
                try { const v = window[k]; if (v && typeof v === 'object') recorrer(v, 0); }
                catch (e) {}
            }
            return resultado;
        }
        """
    )
    if not disponibilidad:
        botones = page.query_selector_all(
            '[data-qa-action*="size"], li[role="option"], button[aria-label]')
        for b in botones:
            etiqueta = (b.inner_text() or b.get_attribute("aria-label") or "").strip()
            if not etiqueta:
                continue
            attrs = ((b.get_attribute("class") or "") + " " +
                     (b.get_attribute("data-qa-action") or "") + " " +
                     (b.get_attribute("aria-disabled") or "")).lower()
            agotado = any(x in attrs for x in
                          ["out-of-stock", "out_of_stock", "disabled", "agotad", "true"])
            disponibilidad[etiqueta.split("\n")[0]] = not agotado
    return disponibilidad


def main():
    if not (PRODUCT_URL and TALLES_DESEADOS and NTFY_TOPIC):
        print("Faltan secrets: PRODUCT_URL / TALLES / NTFY_TOPIC", flush=True)
        sys.exit(1)

    with sync_playwright() as p:
        navegador = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"])
        contexto = navegador.new_context(
            locale="es-AR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900},
        )
        contexto.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = contexto.new_page()

        page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60000)
        for sel in ['button:has-text("Aceptar")', '#onetrust-accept-btn-handler',
                    'button:has-text("ACEPTAR")']:
            try:
                page.click(sel, timeout=2000); break
            except Exception:
                pass
        page.wait_for_timeout(4000)

        stock = leer_disponibilidad(page)
        print("Estado de talles: " + (", ".join(
            f"{t}={'SI' if v else 'no'}" for t, v in stock.items()) or "no se pudo leer"),
            flush=True)

        en_stock = [t for t in TALLES_DESEADOS if stock.get(t, False)]
        if en_stock:
            talles = ", ".join(en_stock)
            enviar_push(f"VOLVIO EL STOCK EN ZARA!\nTalle disponible: {talles}\n"
                        f"Compralo YA (no se reserva). Toca para abrir el producto.",
                        url=PRODUCT_URL)
            print(f"ALERTA enviada por talle: {talles}", flush=True)
        else:
            print("Sin stock de los talles buscados. Nada que avisar.", flush=True)

        navegador.close()


if __name__ == "__main__":
    main()
