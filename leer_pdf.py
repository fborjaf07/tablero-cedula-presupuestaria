#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
leer_pdf.py — Lee la cedula presupuestaria en PDF exportada por eGob.

El reporte "CEDULA PRESUPUESTARIA DE GASTO" sale de eGob como PDF con capa
de texto (generado por LibreOffice). Cada linea util empieza con el codigo
de partida y termina con diez importes:

    A asignacion inicial   B reformas          C codificado = A+B
    D certificado          E comprometido      F devengado
    G pagado               H saldo x cert=C-D  I saldo x comp=E-D
    J saldo x devengar=E-F

Las partidas generales tienen codigo de tres segmentos (75.01.03) y las
subpartidas, el codigo programatico completo (75.01.03.2026.3.6...).

Uso:
    python3 leer_pdf.py cedula.pdf            # muestra un resumen
    python3 leer_pdf.py cedula.pdf salida.json
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

# Codigo de partida + denominacion + diez importes al final de la linea
IMPORTE = r"-?[\d.,]+\.\d{2}"
FILA = re.compile(
    r"^(?P<cod>\d{2}\.\d{2}\.\d{2}(?:\.[\w.]+)?)\s+"
    r"(?P<den>.+?)\s+"
    r"(?P<nums>(?:" + IMPORTE + r"\s+){9}" + IMPORTE + r")\s*$"
)
TOTALES = re.compile(r"^TOTALE?S?:\s+(?P<nums>(?:" + IMPORTE + r"\s+){9}" + IMPORTE + r")\s*$")
CABECERA = re.compile(r"DEL\s+(\d{4}-\d{2}-\d{2})\s+AL\s+(\d{4}-\d{2}-\d{2})")
IMPRESION = re.compile(r"Fecha Impresi[oó]n:\s*([\d/]+\s+[\d:]+)")
DIRECCION = re.compile(r"^-\s*(DIRECCI[ÓO]N.+?)\s*$")

CAMPOS = ["asignacion", "reformas", "codificado", "certificado", "comprometido",
          "devengado", "pagado", "saldo_certificar", "saldo_comprometer",
          "saldo_devengar"]


def texto_pdf(ruta):
    """Extrae el texto conservando la disposicion en columnas."""
    try:
        return subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", ruta, "-"],
            capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        raise SystemExit("Falta pdftotext. Instale poppler-utils "
                         "(Ubuntu: apt install poppler-utils).")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"pdftotext fallo al leer {ruta}: {e.stderr[:200]}")


def n(s):
    return round(float(s.replace(",", "")), 2)


def parsear(texto):
    periodo = direccion = impresion = ""
    filas, total = [], None

    for linea in texto.splitlines():
        linea = linea.rstrip()
        if not linea.strip():
            continue

        if not periodo:
            m = CABECERA.search(linea)
            if m:
                periodo = f"{m.group(1)} al {m.group(2)}"
        if not direccion:
            m = DIRECCION.match(linea.strip())
            if m:
                direccion = m.group(1)
        if not impresion:
            m = IMPRESION.search(linea)
            if m:
                impresion = m.group(1)

        m = TOTALES.match(linea.strip())
        if m and total is None:
            total = dict(zip(CAMPOS, [n(x) for x in m.group("nums").split()]))
            continue

        m = FILA.match(linea)
        if not m:
            continue
        cod = m.group("cod")
        reg = dict(zip(CAMPOS, [n(x) for x in m.group("nums").split()]))
        reg["codigo"] = cod
        reg["denominacion"] = " ".join(m.group("den").split())
        reg["nivel"] = 1 if cod.count(".") == 2 else 2
        filas.append(reg)

    return {"periodo": periodo, "direccion": direccion,
            "impresion": impresion, "filas": filas, "total": total}


def agrupar(filas):
    """Cuelga cada subpartida de su partida general."""
    grupos, actual = [], None
    huerfanas = []
    for f in filas:
        if f["nivel"] == 1:
            actual = dict(f)
            actual["partidas"] = []
            grupos.append(actual)
        else:
            if actual and f["codigo"].startswith(actual["codigo"] + "."):
                actual["partidas"].append(f)
            else:
                # Subpartida cuya cabecera quedo en otra pagina: se busca.
                padre = ".".join(f["codigo"].split(".")[:3])
                dueño = next((g for g in grupos if g["codigo"] == padre), None)
                if dueño:
                    dueño["partidas"].append(f)
                else:
                    huerfanas.append(f["codigo"])
    return grupos, huerfanas


def verificar(grupos, total):
    """Contrasta la suma de partidas generales contra la fila TOTALES."""
    avisos = []
    for c in ["codificado", "certificado", "comprometido", "devengado", "pagado"]:
        suma = round(sum(g[c] for g in grupos), 2)
        if total and abs(suma - total[c]) > 0.05:
            avisos.append(f"{c}: partidas suman {suma:,.2f} y TOTALES dice "
                          f"{total[c]:,.2f} (dif {suma - total[c]:,.2f})")
    for g in grupos:
        if not g["partidas"]:
            continue
        suma = round(sum(p["codificado"] for p in g["partidas"]), 2)
        if abs(suma - g["codificado"]) > 0.05:
            avisos.append(f"{g['codigo']}: subpartidas suman {suma:,.2f} "
                          f"y la partida dice {g['codificado']:,.2f}")
    return avisos


def leer(ruta_pdf):
    d = parsear(texto_pdf(ruta_pdf))
    grupos, huerfanas = agrupar(d["filas"])
    avisos = verificar(grupos, d["total"])
    if huerfanas:
        avisos.append(f"{len(huerfanas)} subpartida(s) sin partida general: "
                      + ", ".join(huerfanas[:5]))
    tz = timezone(timedelta(hours=-5))
    return {
        "origen": "PDF eGob",
        "periodo": d["periodo"],
        "direccion": d["direccion"],
        "impresion": d["impresion"],
        "leido": datetime.now(tz).isoformat(timespec="seconds"),
        "total": d["total"],
        "grupos": grupos,
        "avisos": avisos,
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    d = leer(sys.argv[1])
    nsub = sum(len(g["partidas"]) for g in d["grupos"])
    print(f"{d['direccion']}")
    print(f"Periodo {d['periodo']} · impreso {d['impresion']}")
    print(f"{len(d['grupos'])} partidas generales, {nsub} subpartidas")
    if d["total"]:
        t = d["total"]
        print(f"Codificado {t['codificado']:>16,.2f}")
        print(f"Certificado{t['certificado']:>16,.2f}")
        print(f"Comprometido{t['comprometido']:>15,.2f}")
        print(f"Devengado  {t['devengado']:>16,.2f}")
    print("Verificacion: " + ("cuadra" if not d["avisos"] else "REVISAR"))
    for a in d["avisos"]:
        print("  ! " + a)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Escrito {sys.argv[2]}")


if __name__ == "__main__":
    main()
