#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
leer_partida_xls.py — Lee el "Partida XLS" que exporta la Consulta
presupuestaria de eGob (GADM Riobamba).

El archivo es un .xls antiguo (Excel 97) con la cabecera en la fila 10 y
trece columnas. Las filas se distinguen por la cantidad de segmentos del
codigo de partida:

    5                                        raiz    (1 segmento)
    51                                       raiz
    51.01                                    grupo   (2 segmentos)
    51.01.05                                 partida general (3)
    51.01.05.2026.3.6.000.000.000.200.002    subpartida (11)
    P0                                       fila de totales

Uso:
    python3 leer_partida_xls.py archivo.xls
    python3 leer_partida_xls.py archivo.xls salida.json
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd

TZ = timezone(timedelta(hours=-5))
FILA_CABECERA = 9          # 0-indexado

COLUMNAS = ["partida", "nombre", "inicial", "reformas", "codificado",
            "certificado", "comprometido", "devengado", "ejecutado",
            "pend_certificar", "pend_comprometer", "pend_devengar",
            "pend_ejecutar"]

CIFRAS = COLUMNAS[2:]


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if pd.isna(f) else round(f, 2)


def txt(v):
    return "" if v is None or pd.isna(v) else " ".join(str(v).split())


def leer(ruta):
    d = pd.read_excel(ruta, sheet_name=0, header=None)

    cab = [txt(x) for x in d.iloc[FILA_CABECERA].tolist()]
    if "PARTIDA" not in cab[0].upper():
        raise SystemExit(
            f"{os.path.basename(ruta)}: no encuentro la cabecera esperada en la "
            f"fila {FILA_CABECERA + 1}. Puede que eGob haya cambiado el formato.")

    c = d.iloc[FILA_CABECERA + 1:].copy()
    c = c.iloc[:, :len(COLUMNAS)]
    c.columns = COLUMNAS
    c = c[c["partida"].notna()]

    filas, total = [], None
    for _, r in c.iterrows():
        cod = txt(r["partida"])
        if not cod:
            continue
        reg = {k: num(r[k]) for k in CIFRAS}
        reg["codigo"] = cod
        reg["nombre"] = txt(r["nombre"])
        if cod.upper().startswith("P"):          # P0 = CATALOGO DE PARTIDAS
            reg["nivel"] = "total"
            total = reg
            continue
        seg = cod.count(".") + 1
        reg["nivel"] = {1: "raiz", 2: "grupo", 3: "partida"}.get(seg, "subpartida")
        reg["padre"] = ".".join(cod.split(".")[:3]) if seg > 3 else None
        filas.append(reg)

    partidas = [f for f in filas if f["nivel"] == "partida"]
    subpartidas = [f for f in filas if f["nivel"] == "subpartida"]

    avisos = []
    if total:
        suma = round(sum(p["codificado"] for p in partidas), 2)
        if abs(suma - total["codificado"]) > 0.05:
            avisos.append(f"las partidas suman {suma:,.2f} y la fila de totales "
                          f"dice {total['codificado']:,.2f}")
    else:
        avisos.append("no encontre la fila de totales (P0)")

    return {
        "archivo": os.path.basename(ruta),
        "leido": datetime.now(TZ).isoformat(timespec="seconds"),
        "total": total,
        "partidas": partidas,
        "subpartidas": subpartidas,
        "avisos": avisos,
    }


def indexar(d):
    """Diccionario codigo -> cifras, para comparar dos corridas."""
    return {f["codigo"]: f for f in d["partidas"] + d["subpartidas"]}


def comparar(antes, ahora, campos=("codificado", "certificado",
                                   "comprometido", "devengado")):
    """Subpartidas cuyas cifras cambiaron entre dos corridas.

    Es lo que decide de que subpartidas hay que bajar el detalle: solo las
    que se movieron, no las 218.
    """
    A = indexar(antes) if antes else {}
    B = indexar(ahora)
    cambios = []
    for cod, b in B.items():
        if b["nivel"] != "subpartida":
            continue
        a = A.get(cod)
        dif = {}
        for k in campos:
            d = round(b[k] - (a[k] if a else 0.0), 2)
            if abs(d) > 0.005:
                dif[k] = {"antes": a[k] if a else None, "ahora": b[k], "cambio": d}
        if dif:
            cambios.append({"codigo": cod, "nombre": b["nombre"],
                            "nuevo": a is None, "diferencias": dif})
    cambios.sort(key=lambda c: -max(abs(v["cambio"]) for v in c["diferencias"].values()))
    return cambios


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    d = leer(sys.argv[1])
    t = d["total"] or {}
    print(f"{d['archivo']}")
    print(f"  {len(d['partidas'])} partidas · {len(d['subpartidas'])} subpartidas")
    print(f"  codificado   {t.get('codificado', 0):>16,.2f}")
    print(f"  certificado  {t.get('certificado', 0):>16,.2f}")
    print(f"  comprometido {t.get('comprometido', 0):>16,.2f}")
    print(f"  devengado    {t.get('devengado', 0):>16,.2f}")
    print("  verificacion: " + ("cuadra" if not d["avisos"] else "REVISAR"))
    for a in d["avisos"]:
        print("   ! " + a)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  escrito {sys.argv[2]}")


if __name__ == "__main__":
    main()
