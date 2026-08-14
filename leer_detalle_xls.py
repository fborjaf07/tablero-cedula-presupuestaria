#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
leer_detalle_xls.py — Lee el "Detalle de Movimiento Partida" de eGob.

Este reporte es el que reemplaza a la matriz de proyectos que se llevaba
a mano: trae la cadena completa de cada partida, con beneficiario y
numero de documento.

    Fecha · Numero de Certificado · Numero de Compromiso · Numero de
    Documento · Beneficiario · Concepto · Certificado · Comprometido ·
    Devengado · Pagado

Dos cosas que conviene tener presentes al leerlo:

  * Un archivo puede traer varios bloques, uno por cada partida que
    estuviera seleccionada al pedirlo. Si se selecciona una fila de nivel
    agregado (por ejemplo 73.08.11 o el grupo 5), ese bloque sale vacio:
    los movimientos cuelgan de la subpartida con codigo programatico
    completo, no de los niveles superiores.
  * Los movimientos llevan signo. Una anulacion aparece como MOD-CERT con
    importe negativo, de modo que el saldo vivo de una certificacion es la
    suma de sus filas, no la primera de ellas.

Uso:
    python3 leer_detalle_xls.py archivo.xls
    python3 leer_detalle_xls.py archivo.xls salida.json
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd

TZ = timezone(timedelta(hours=-5))
IMPORTES = ["certificado", "comprometido", "devengado", "pagado"]


def txt(v):
    return "" if v is None or pd.isna(v) else " ".join(str(v).split())


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if pd.isna(f) else round(f, 2)


def fecha(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    s = txt(v)
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else s


def leer(ruta):
    d = pd.read_excel(ruta, sheet_name=0, header=None)
    filas = d.values.tolist()

    bloques, actual, en_tabla = [], None, False
    for r in filas:
        c0 = txt(r[0])

        if c0 == "Partida":
            actual = {
                "codigo": txt(r[1]),
                "nombre": txt(r[5]) or txt(r[4]),
                "inicial": num(r[7]),
                "saldo_disponible": num(r[11]),
                "movimientos": [],
            }
            bloques.append(actual)
            en_tabla = False
            continue

        if c0.startswith("Codfificado") or c0.startswith("Codificado"):
            if actual:
                actual.update({
                    "codificado": num(r[1]), "certificado": num(r[5]),
                    "comprometido": num(r[7]), "devengado": num(r[9]),
                    "pagado": num(r[11]),
                })
            continue

        if c0 == "Fecha":
            en_tabla = True
            continue

        if c0.startswith("TOTALES"):
            if actual:
                actual["totales"] = {k: num(r[8 + i])
                                     for i, k in enumerate(IMPORTES)}
            en_tabla = False
            continue

        if en_tabla and actual and c0:
            actual["movimientos"].append({
                "fecha": fecha(r[0]),
                "certificacion": txt(r[1]),
                "compromiso": txt(r[2]),
                "documento": txt(r[3]),
                "beneficiario": txt(r[4]),
                "concepto": txt(r[6]),
                "certificado": num(r[8]),
                "comprometido": num(r[9]),
                "devengado": num(r[10]),
                "pagado": num(r[11]),
            })

    for b in bloques:
        b["n_movimientos"] = len(b["movimientos"])
        b["vacio"] = not b["movimientos"]
        b["anulaciones"] = [m for m in b["movimientos"]
                            if m["certificado"] < 0 or m["comprometido"] < 0]

    utiles = [b for b in bloques if not b["vacio"]]
    avisos = []
    for b in bloques:
        if b["vacio"]:
            avisos.append(f"{b['codigo']}: sin movimientos — es un nivel "
                          f"agregado, hay que seleccionar la subpartida completa")
        elif b.get("totales"):
            for k in IMPORTES:
                suma = round(sum(m[k] for m in b["movimientos"]), 2)
                if abs(suma - b["totales"][k]) > 0.05:
                    avisos.append(f"{b['codigo']}: los movimientos de {k} suman "
                                  f"{suma:,.2f} y el total dice {b['totales'][k]:,.2f}")

    return {
        "archivo": os.path.basename(ruta),
        "leido": datetime.now(TZ).isoformat(timespec="seconds"),
        "bloques": bloques,
        "con_movimientos": len(utiles),
        "avisos": avisos,
    }


def resumir_certificaciones(bloque):
    """Agrupa los movimientos por certificacion, sumando anulaciones."""
    cert = {}
    for m in bloque["movimientos"]:
        # Una certificacion nueva se identifica por su documento; las
        # modificaciones apuntan a la certificacion en la columna propia.
        clave = m["certificacion"] or m["documento"]
        c = cert.setdefault(clave, {
            "certificacion": clave, "beneficiario": "", "concepto": "",
            "fecha": m["fecha"], **{k: 0.0 for k in IMPORTES},
            "documentos": [], "anulada": False,
        })
        for k in IMPORTES:
            c[k] = round(c[k] + m[k], 2)
        if m["beneficiario"] and not c["beneficiario"]:
            c["beneficiario"] = m["beneficiario"]
        if m["concepto"] and not c["concepto"]:
            c["concepto"] = m["concepto"]
        if m["documento"] not in c["documentos"]:
            c["documentos"].append(m["documento"])
    for c in cert.values():
        c["anulada"] = c["certificado"] == 0 and c["comprometido"] == 0
    return sorted(cert.values(), key=lambda c: -abs(c["certificado"]))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    d = leer(sys.argv[1])
    print(d["archivo"])
    for b in d["bloques"]:
        estado = "vacio" if b["vacio"] else f"{b['n_movimientos']} movimientos"
        print(f"\n  {b['codigo']}  ({estado})")
        print(f"    {b['nombre'][:70]}")
        if b["vacio"]:
            continue
        print(f"    codificado {b.get('codificado', 0):,.2f} · "
              f"certificado {b.get('certificado', 0):,.2f} · "
              f"devengado {b.get('devengado', 0):,.2f}")
        if b["anulaciones"]:
            print(f"    {len(b['anulaciones'])} anulacion(es):")
            for m in b["anulaciones"]:
                imp = m["certificado"] or m["comprometido"]
                print(f"      {m['fecha']}  {m['documento']:22} "
                      f"{m['certificacion']:18} {imp:>14,.2f}")
    for a in d["avisos"]:
        print("  ! " + a)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        print(f"\n  escrito {sys.argv[2]}")


if __name__ == "__main__":
    main()
