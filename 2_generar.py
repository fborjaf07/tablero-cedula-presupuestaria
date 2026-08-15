#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2_generar.py — Arma datos.json para el tablero desde lo que baja el robot.

Toma las dos descargas de eGob y las combina:

    datos/partidas.xls      cifras oficiales de partidas y subpartidas
    datos/detalle/*.xls     movimientos por subpartida, con beneficiario

Del detalle sale lo que antes se llevaba a mano en la matriz de proyectos:
quien, cuando, con que documento y por cuanto. Y como los movimientos
llevan signo, las anulaciones aparecen como tales en lugar de perderse en
un saldo.

Uso:
    python3 2_generar.py
    python3 2_generar.py --datos datos --salida publico/datos.json
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import leer_partida_xls as LP
import leer_detalle_xls as LD

TZ = timezone(timedelta(hours=-5))

# Gasto computable segun la Direccion Financiera.
GRUPOS_COMPUTABLES = ("73", "75", "77", "84", "88")

ESTADOS = [("planificado", "Planificado"), ("certificado", "Certificado"),
           ("comprometido", "Comprometido"), ("ejecucion", "En ejecución"),
           ("devengado", "Devengado")]


def es_computable(codigo):
    return str(codigo).strip()[:2] in GRUPOS_COMPUTABLES


def estado(o):
    """Etapa en la que esta una certificacion o una subpartida."""
    if o["certificado"] <= 0:
        return "planificado"
    if o["comprometido"] <= 0:
        return "certificado"
    if o["devengado"] <= 0:
        return "comprometido"
    if o["devengado"] + 0.01 < o["comprometido"]:
        return "ejecucion"
    return "devengado"


# ------------------------------------------------------------------ detalle

def cargar_detalles(carpeta):
    """Lee todos los .xls de detalle y los indexa por subpartida.

    Puede haber un archivo por subpartida o uno con varios bloques; los
    dos casos se tratan igual. Si una subpartida aparece en mas de un
    archivo se conserva la del mas reciente.
    """
    bloques, leidos, avisos = {}, 0, []
    rutas = sorted(glob.glob(os.path.join(carpeta, "*.xls")),
                   key=os.path.getmtime)
    for ruta in rutas:
        try:
            d = LD.leer(ruta)
        except Exception as e:
            avisos.append(f"{os.path.basename(ruta)}: {str(e)[:80]}")
            continue
        leidos += 1
        for b in d["bloques"]:
            if not b["vacio"]:
                bloques[b["codigo"]] = b
    return bloques, leidos, avisos


# El concepto de una certificacion viene con toda la formula legal. El
# objeto de la contratacion va tras "para:" y antes de ", por un valor de".
OBJETO = re.compile(
    r"disponibilidad\s+presupuestaria\s+para\s*:?\s*(.+?)"
    r"(?:,?\s*por\s+(?:un\s+)?valor|,?\s*por\s+la\s+cantidad|$)",
    re.I | re.S)
MEMO = re.compile(r"(Memorando\s+Nro\.?\s*[\w\-]+)", re.I)


def objeto_de(concepto):
    """Saca el objeto de la contratación del texto de la certificación."""
    t = " ".join((concepto or "").split())
    if not t:
        return ""
    m = OBJETO.search(t)
    if m:
        obj = m.group(1).strip(" .,;:")
        if 5 < len(obj) < 400:
            return obj
    # Si no encaja el patrón, al menos el memorando dice de qué trámite es.
    m = MEMO.search(t)
    if m and len(t) > 200:
        return m.group(1)
    return t[:200] + ("…" if len(t) > 200 else "")


def certificaciones(bloque):
    """Agrupa los movimientos de una subpartida por certificacion.

    Cada certificacion es lo mas parecido a un 'proyecto': tiene su
    beneficiario, su objeto y su recorrido de certificado a pagado. Las
    modificaciones se suman a la certificacion que afectan, de modo que
    una anulada queda en cero y se marca como tal.
    """
    grupos = defaultdict(lambda: {
        "certificacion": "", "beneficiario": "", "concepto": "",
        "fecha": "", "ultimo": "", "f_comprometido": "", "f_devengado": "",
        "certificado": 0.0, "comprometido": 0.0,
        "devengado": 0.0, "pagado": 0.0, "documentos": [], "movimientos": 0,
    })
    for m in bloque["movimientos"]:
        clave = m["certificacion"] or m["documento"] or "(sin certificación)"
        g = grupos[clave]
        g["certificacion"] = clave
        for k in ("certificado", "comprometido", "devengado", "pagado"):
            g[k] = round(g[k] + m[k], 2)
        g["movimientos"] += 1
        if not g["fecha"] or (m["fecha"] and m["fecha"] < g["fecha"]):
            g["fecha"] = m["fecha"]
        # el ultimo movimiento es lo que marca si el expediente sigue vivo
        if m["fecha"] and m["fecha"] > g["ultimo"]:
            g["ultimo"] = m["fecha"]
        # primera vez que aparece cada etapa, para medir cuanto tardo
        if m["comprometido"] > 0 and (not g["f_comprometido"]
                                      or m["fecha"] < g["f_comprometido"]):
            g["f_comprometido"] = m["fecha"]
        if m["devengado"] > 0 and (not g["f_devengado"]
                                   or m["fecha"] < g["f_devengado"]):
            g["f_devengado"] = m["fecha"]
        if m["beneficiario"] and not g["beneficiario"]:
            g["beneficiario"] = m["beneficiario"]
        if m["concepto"] and not g["concepto"]:
            g["concepto"] = objeto_de(m["concepto"])
        if m["documento"] and m["documento"] not in g["documentos"]:
            g["documentos"].append(m["documento"])

    salida = []
    for g in grupos.values():
        g["anulada"] = (g["certificado"] <= 0.005 and g["comprometido"] <= 0.005)
        g["estado"] = "anulada" if g["anulada"] else estado(g)
        g["avance"] = (round(g["devengado"] / g["certificado"] * 100, 2)
                       if g["certificado"] > 0 else 0.0)
        salida.append(g)
    salida.sort(key=lambda g: -g["certificado"])
    return salida


# ------------------------------------------------------------------ armado

def armar(partidas, bloques, fuentes=None):
    """Cuelga subpartidas y detalle de cada partida general."""
    porc = defaultdict(list)
    for s in partidas["subpartidas"]:
        porc[s["padre"]].append(s)

    fuentes = fuentes or {}
    grupos = []
    for p in partidas["partidas"]:
        subs = []
        for s in porc.get(p["codigo"], []):
            b = bloques.get(s["codigo"])
            certs = certificaciones(b) if b else []
            subs.append({
                "codigo": s["codigo"],
                "denominacion": s["nombre"],
                "fuente": fuentes.get(s["codigo"], SIN_FUENTE),
                "codificado": s["codificado"],
                "certificado": s["certificado"],
                "comprometido": s["comprometido"],
                "devengado": s["devengado"],
                "pagado": (b or {}).get("pagado", 0.0),
                "saldo_certificar": s["pend_certificar"],
                "saldo_devengar": s["pend_devengar"],
                "saldo_disponible": (b or {}).get("saldo_disponible", 0.0),
                "con_detalle": b is not None,
                "n_movimientos": (b or {}).get("n_movimientos", 0),
                "certificaciones": certs,
                # El tablero lista cada certificacion como una linea de
                # detalle, igual que antes hacia con la matriz en Excel.
                "en_matriz": "SÍ" if b else "—",
                "detalle": [{
                    "denominacion": (
                        (c["beneficiario"] + " — " if c["beneficiario"] else "")
                        + (c["concepto"] or c["certificacion"])
                        + (" [ANULADA]" if c["anulada"] else "")),
                    "codificado": c["certificado"],
                    "certificado": c["certificado"],
                    "comprometido": c["comprometido"],
                    "devengado": c["devengado"],
                    "saldo": False,
                } for c in certs] + ([{
                    "denominacion": "SALDO DISPONIBLE",
                    "codificado": b["saldo_disponible"],
                    "certificado": 0.0, "comprometido": 0.0, "devengado": 0.0,
                    "saldo": True,
                }] if b and b.get("saldo_disponible", 0) > 0 else []),
                "anulaciones": [{
                    "fecha": m["fecha"], "documento": m["documento"],
                    "certificacion": m["certificacion"],
                    "monto": m["certificado"] or m["comprometido"],
                } for m in (b or {}).get("anulaciones", [])],
            })
        grupos.append({
            "codigo": p["codigo"],
            "denominacion": p["nombre"],
            "grupo": p["codigo"][:2],
            "computable": es_computable(p["codigo"]),
            "asignacion": p["inicial"],
            "reformas": p["reformas"],
            "codificado": p["codificado"],
            "certificado": p["certificado"],
            "comprometido": p["comprometido"],
            "devengado": p["devengado"],
            "pagado": round(sum(x["pagado"] for x in subs), 2),
            "saldo_certificar": p["pend_certificar"],
            "saldo_devengar": p["pend_devengar"],
            "delta": 0.0,
            "estado": "",
            "partidas": subs,
        })
    return grupos


def cargar_fuentes(ruta="fuentes.json"):
    """Catalogo de fuente de financiamiento por codigo de subpartida.

    eGob no la expone en la consulta presupuestaria, asi que se mantiene
    aparte, en fuentes.json. Si el archivo no esta, todo queda como
    "Sin fuente asignada" y el tablero sigue funcionando igual.
    """
    if not os.path.exists(ruta):
        return {}
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


SIN_FUENTE = "Sin fuente asignada"


def resumir_fuentes(grupos):
    """Agrega las cifras por fuente, sumando desde las subpartidas."""
    campos = ["codificado", "certificado", "comprometido", "devengado",
              "pagado", "saldo_certificar", "saldo_devengar"]
    acum = {}
    for g in grupos:
        for s in g["partidas"]:
            f = s.get("fuente") or SIN_FUENTE
            a = acum.setdefault(f, {k: 0.0 for k in campos})
            a["n"] = a.get("n", 0) + 1
            for k in campos:
                a[k] += s.get(k, 0.0)
    salida = []
    for nombre, a in acum.items():
        fila = {"fuente": nombre, "n": a["n"]}
        fila.update({k: round(a[k], 2) for k in campos})
        salida.append(fila)
    salida.sort(key=lambda x: -x["codificado"])
    return salida


def resumir(grupos):
    campos = ["asignacion", "reformas", "codificado", "certificado",
              "comprometido", "devengado", "pagado", "saldo_certificar",
              "saldo_devengar", "delta"]

    def agregar(sel):
        r = {k: round(sum(g[k] for g in sel), 2) for k in campos}
        r["partidas"] = len(sel)
        r["sin_devengar"] = sum(1 for g in sel if g["devengado"] <= 0)
        r["sin_certificar"] = sum(1 for g in sel if g["certificado"] <= 0)
        return r

    return {"todo": agregar(grupos),
            "computable": agregar([g for g in grupos if g["computable"]]),
            "no_computable": agregar([g for g in grupos if not g["computable"]])}


MESES_ES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def resumir_meses(grupos, bloques):
    """Flujo mensual real, tomado de la fecha de cada movimiento.

    No sirve fechar por la certificacion: una obra certificada en enero y
    devengada en julio no es devengo de enero. Cada movimiento cuenta en el
    mes en que ocurrio, que es lo que permite ver el ritmo de ejecucion.

    El codificado no aparece aqui a proposito: el Partida XLS solo da la
    foto de hoy, asi que no hay forma de reconstruir el presupuesto vigente
    de meses anteriores sin inventarlo.
    """
    campos = ("certificado", "comprometido", "devengado", "pagado")
    # de que partida general cuelga cada subpartida
    padre = {}
    for g in grupos:
        for s in g["partidas"]:
            padre[s["codigo"]] = (g["codigo"], g["denominacion"])

    meses = defaultdict(lambda: {k: 0.0 for k in campos})
    porpar = defaultdict(lambda: defaultdict(lambda: {k: 0.0 for k in campos}))

    for cod, b in bloques.items():
        pcod, pnom = padre.get(cod, (cod[:8], ""))
        for m in b["movimientos"]:
            mes = (m["fecha"] or "")[:7]
            if len(mes) != 7:
                continue
            r = meses[mes]
            r["n"] = r.get("n", 0) + 1
            if m["certificado"] < 0 or m["comprometido"] < 0:
                r["anulaciones"] = r.get("anulaciones", 0) + 1
            p = porpar[mes][pcod]
            p["denominacion"] = pnom
            for k in campos:
                r[k] += m[k]
                p[k] += m[k]

    salida = []
    acum = {k: 0.0 for k in campos}
    for mes in sorted(meses):
        r = meses[mes]
        for k in campos:
            acum[k] += r[k]
        aa, mm = mes.split("-")
        partidas = []
        for pcod, p in porpar[mes].items():
            fila = {"codigo": pcod, "denominacion": p["denominacion"]}
            fila.update({k: round(p[k], 2) for k in campos})
            if any(abs(fila[k]) > 0.005 for k in campos):
                partidas.append(fila)
        partidas.sort(key=lambda x: -abs(x["certificado"]) - abs(x["devengado"]))
        fila = {
            "mes": mes,
            "etiqueta": f"{MESES_ES[int(mm)]} {aa}",
            "corto": MESES_ES[int(mm)][:3].capitalize(),
            "movimientos": r.get("n", 0),
            "anulaciones": r.get("anulaciones", 0),
            "partidas": partidas,
        }
        fila.update({k: round(r[k], 2) for k in campos})
        fila.update({"acum_" + k: round(acum[k], 2) for k in campos})
        salida.append(fila)
    return salida


def proyectos_desde_detalle(grupos):
    """Convierte las certificaciones en la lista de 'proyectos'.

    Cada certificacion viva es una contratacion con su beneficiario. Es lo
    que reemplaza al PAC que se llevaba en Excel, con la ventaja de venir
    del propio sistema y no de una transcripcion.
    """
    proyectos = []
    for g in grupos:
        for s in g["partidas"]:
            for c in s["certificaciones"]:
                nombre = c["concepto"] or c["beneficiario"] or c["certificacion"]
                proyectos.append({
                    "nombre": nombre,
                    "beneficiario": c["beneficiario"],
                    "certificacion": c["certificacion"],
                    "fecha": c["fecha"],
                    "ultimo": c["ultimo"],
                    "f_comprometido": c["f_comprometido"],
                    "f_devengado": c["f_devengado"],
                    "saldo": False,
                    "codificado": c["certificado"],
                    "certificado": c["certificado"],
                    "comprometido": c["comprometido"],
                    "devengado": c["devengado"],
                    "avance": c["avance"],
                    "estado": c["estado"],
                    "computable": g["computable"],
                    "generales": [g["codigo"]],
                    "partidas": [{"partida": s["codigo"],
                                  "general": g["codigo"],
                                  "codificado": c["certificado"],
                                  "certificado": c["certificado"],
                                  "comprometido": c["comprometido"],
                                  "devengado": c["devengado"]}],
                })
    proyectos.sort(key=lambda p: -p["certificado"])
    return proyectos


def resumir_proyectos(proyectos):
    vivos = [p for p in proyectos if p["estado"] != "anulada"]
    por_estado = []
    for clave, etiqueta in ESTADOS + [("anulada", "Anulada")]:
        sel = [p for p in proyectos if p["estado"] == clave]
        por_estado.append({"estado": clave, "etiqueta": etiqueta,
                           "n": len(sel),
                           "codificado": round(sum(p["certificado"] for p in sel), 2)})
    return {
        "n": len(vivos),
        "codificado": round(sum(p["certificado"] for p in vivos), 2),
        "certificado": round(sum(p["certificado"] for p in vivos), 2),
        "comprometido": round(sum(p["comprometido"] for p in vivos), 2),
        "devengado": round(sum(p["devengado"] for p in vivos), 2),
        "por_estado": por_estado,
    }


def adjuntar_top(grupos, proyectos, n=3):
    por_grupo = defaultdict(list)
    for p in proyectos:
        if p["estado"] != "anulada":
            por_grupo[p["generales"][0]].append(p)
    for g in grupos:
        sel = sorted(por_grupo.get(g["codigo"], []),
                     key=lambda p: -p["certificado"])
        g["n_proyectos"] = len(sel)
        g["top_proyectos"] = [{
            "nombre": p["nombre"], "codificado": p["certificado"],
            "certificado": p["certificado"], "comprometido": p["comprometido"],
            "devengado": p["devengado"], "estado": p["estado"],
        } for p in sel[:n]]


# ------------------------------------------------------------------ salida

def incrustar(ruta_html, data):
    """Refresca la instantanea embebida en el HTML."""
    if not ruta_html or not os.path.exists(ruta_html):
        return False
    with open(ruta_html, encoding="utf-8") as f:
        html = f.read()
    bloque = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    bloque = bloque.replace("</script>", "<\\/script>")
    nuevo, n = re.subn(
        r'(<script id="datos-embebidos" type="application/json">).*?(</script>)',
        lambda m: m.group(1) + bloque + m.group(2),
        html, count=1, flags=re.S)
    if n:
        with open(ruta_html, "w", encoding="utf-8") as f:
            f.write(nuevo)
    return bool(n)


def construir(carpeta_datos):
    xls = os.path.join(carpeta_datos, "partidas.xls")
    if not os.path.exists(xls):
        raise SystemExit(f"Falta {xls}: ejecute antes 1_descargar.py")

    partidas = LP.leer(xls)
    bloques, n_archivos, avisos = cargar_detalles(
        os.path.join(carpeta_datos, "detalle"))

    grupos = armar(partidas, bloques, cargar_fuentes())
    proyectos = proyectos_desde_detalle(grupos)
    adjuntar_top(grupos, proyectos)

    t = partidas["total"] or {}
    total = {
        "denominacion": "TOTAL GENERAL",
        "asignacion": t.get("inicial", 0.0),
        "reformas": t.get("reformas", 0.0),
        "codificado": t.get("codificado", 0.0),
        "certificado": t.get("certificado", 0.0),
        "comprometido": t.get("comprometido", 0.0),
        "devengado": t.get("devengado", 0.0),
        "pagado": round(sum(g["pagado"] for g in grupos), 2),
        "saldo_certificar": t.get("pend_certificar", 0.0),
        "saldo_devengar": t.get("pend_devengar", 0.0),
        "delta": 0.0,
        "m_codificado": t.get("codificado", 0.0),
    }

    con_detalle = sum(1 for g in grupos for s in g["partidas"] if s["con_detalle"])
    sin_detalle = sum(1 for g in grupos for s in g["partidas"]
                      if not s["con_detalle"] and s["certificado"] > 0)
    if sin_detalle:
        avisos.append(f"{sin_detalle} subpartida(s) con certificación pero sin "
                      f"detalle descargado")

    return {
        "fuente": "eGob — GAD Municipal de Riobamba",
        "hoja": "Consulta presupuestaria · Programa 3.6",
        "corte": datetime.now(TZ).strftime("%d/%m/%Y %H:%M"),
        "generado": datetime.now(TZ).isoformat(timespec="seconds"),
        "criterio_computable": list(GRUPOS_COMPUTABLES),
        "fuentes": {
            "cedula": {"tipo": "Partida XLS", "direccion": "DIRECCIÓN GENERAL "
                       "DE GESTIÓN DE OBRAS PÚBLICAS", "periodo": "2026",
                       "impresion": datetime.now(TZ).strftime("%d/%m/%Y %H:%M"),
                       "leido": datetime.now(TZ).isoformat(timespec="seconds"),
                       "avisos": partidas["avisos"] + avisos,
                       "subpartidas_sin_detalle": sin_detalle},
            "matriz": {"archivo": f"{n_archivos} archivo(s) de detalle",
                       "leido": datetime.now(TZ).isoformat(timespec="seconds"),
                       "corte": f"{con_detalle} subpartidas con movimientos"},
        },
        "discrepancias": [],
        "total": total,
        "resumen": resumir(grupos),
        "financiamiento": resumir_fuentes(grupos),
        "mensual": resumir_meses(grupos, bloques),
        "grupos": grupos,
        "proyectos": proyectos,
        "resumen_proyectos": resumir_proyectos(proyectos),
    }


def main():
    ap = argparse.ArgumentParser(description="Genera datos.json para el tablero.")
    ap.add_argument("--datos", default="datos", help="Carpeta con los .xls")
    ap.add_argument("--salida", default=os.path.join("publico", "datos.json"))
    ap.add_argument("--html", default=os.path.join("publico", "index.html"))
    a = ap.parse_args()

    data = construir(a.datos)

    os.makedirs(os.path.dirname(a.salida) or ".", exist_ok=True)
    tmp = a.salida + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, a.salida)
    incrustar(a.html, data)

    r = data["resumen"]["todo"]
    rp = data["resumen_proyectos"]
    print(f"Corte {data['corte']}")
    print(f"  {len(data['grupos'])} partidas · codificado {r['codificado']:,.2f} "
          f"· devengado {r['devengado']:,.2f}")
    print(f"  {rp['n']} certificaciones vivas · "
          f"{sum(1 for p in data['proyectos'] if p['estado'] == 'anulada')} anuladas")
    for e in rp["por_estado"]:
        if e["n"]:
            print(f"     {e['etiqueta']:16} {e['n']:5}  {e['codificado']:>15,.2f}")
    for av in data["fuentes"]["cedula"]["avisos"]:
        print("  ! " + av)
    print(f"Escrito {a.salida}")


if __name__ == "__main__":
    main()
