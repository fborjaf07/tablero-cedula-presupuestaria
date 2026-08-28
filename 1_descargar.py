#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1_descargar.py — Descarga la consulta presupuestaria desde eGob.

Reproduce con Playwright el mismo recorrido que hace una persona:

    1. CAS login          egob.gadmriobamba.gob.ec:8443/cas/login
    2. Portal             clic en "e-GOB FINANCIERO"
    3. Buscador Accion    "consulta presupuestaria"
    4. Programa           3.6 -> DIRECCION GENERAL DE GESTION DE OBRAS PUBLICAS
    5. Seleccionar todo   doble clic en la casilla de la cabecera
    6. Imprimir           "Partida XLS"          -> datos/partidas.xls
    7. Por cada subpartida que cambio respecto de la corrida anterior:
       marcar su casilla e "Detalle de Movimiento Partida"
                                                  -> datos/detalle/<codigo>.xls

El paso 7 es lo que mantiene la corrida corta: entre un dia y el siguiente
suelen moverse dos o tres subpartidas, no las 218. La primera vez, como no
hay con que comparar, se bajan todas las que tengan movimiento (--todas).

Deja una captura de pantalla de cada paso en capturas/, de modo que si algo
falla se puede ver exactamente donde.

Credenciales: variables de entorno EGOB_USUARIO y EGOB_CLAVE. En GitHub
Actions se cargan desde los Secrets del repositorio.

Uso:
    python3 1_descargar.py
    python3 1_descargar.py --todas          primera corrida
    python3 1_descargar.py --sin-detalle    solo el Partida XLS
    python3 1_descargar.py --ver            con navegador visible, para depurar
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import leer_partida_xls as LP

TZ = timezone(timedelta(hours=-5))
BASE = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(BASE, "datos")
DETALLE = os.path.join(DATOS, "detalle")
CAPTURAS = os.path.join(BASE, "capturas")

CAS = os.environ.get("EGOB_CAS", "https://egob.gadmriobamba.gob.ec:8443/cas/login")
APP = os.environ.get("EGOB_APP", "e-GOB FINANCIERO")
PROGRAMA = os.environ.get("EGOB_PROGRAMA", "3.6")
POA = os.environ.get("EGOB_POA", "2026")
DESDE = os.environ.get("EGOB_DESDE", "01/01/2026")
HASTA = os.environ.get("EGOB_HASTA", "31/12/2026")

ESPERA = 60_000        # ms por accion
PASO = 0


def log(msg):
    print(f"[{datetime.now(TZ):%H:%M:%S}] {msg}", flush=True)


def captura(page, nombre):
    global PASO
    PASO += 1
    os.makedirs(CAPTURAS, exist_ok=True)
    ruta = os.path.join(CAPTURAS, f"{PASO:02d}_{nombre}.png")
    try:
        page.screenshot(path=ruta, full_page=False)
    except Exception:
        pass
    return ruta


# ------------------------------------------------------------------ pasos

def iniciar_sesion(page, usuario, clave):
    log("1. Abriendo CAS")
    page.goto(CAS, timeout=ESPERA, wait_until="domcontentloaded")
    captura(page, "cas_login")

    page.fill("#username, input[name=username]", usuario)
    page.fill("#password, input[name=password]", clave)
    page.click("input[type=submit], button[type=submit], .btn-submit")
    page.wait_for_load_state("networkidle", timeout=ESPERA)
    captura(page, "cas_resultado")

    # CAS confirma con "Inicio de sesion exitoso" y la tabla de aplicaciones.
    # Entrando sin parametro service no hay ticket en la URL, asi que el
    # exito se comprueba por el contenido, no por la direccion.
    exito = page.locator("text=/Inicio de sesi[oó]n exitoso|Log In Successful/i")
    if exito.count():
        log("   sesión iniciada")
        return
    if page.locator("text=/credenciales|no v[aá]lid|incorrect|Invalid/i").count():
        raise SystemExit("CAS rechazó las credenciales.")
    if page.locator("input[name=password]").count():
        raise SystemExit("Sigue en el formulario de CAS: no se envió el inicio de sesión.")
    log("   sesión iniciada (sin mensaje de confirmación)")


def abrir_financiero(page):
    log(f"2. Entrando a {APP}")
    # El portal lista las aplicaciones en una tabla; se busca por texto
    # porque el orden puede cambiar.
    fila = page.locator("a[href*='egobfinanciero']").first
    if not fila.count():
        fila = page.locator(f"tr:has-text('{APP}') a").first
    if not fila.count():
        captura(page, "portal_sin_enlace")
        raise SystemExit(f"No encontré el enlace a {APP} en el portal.")
    fila.click()
    page.wait_for_load_state("networkidle", timeout=ESPERA)
    # La aplicación tarda en armarse: se espera al buscador, no un tiempo fijo.
    page.wait_for_selector("input[placeholder*='cci'], input[placeholder*='cción']",
                           timeout=ESPERA)
    captura(page, "financiero")
    log("   financiero cargado")


def abrir_consulta(page):
    log("3. Abriendo la consulta presupuestaria")
    buscador = page.locator("input[placeholder*='cci'], input[placeholder*='cción']").first
    buscador.click()
    buscador.fill("consulta presupuestaria")
    page.wait_for_timeout(1200)
    opcion = page.locator("text=/Presupuesto \\/ Reportes \\/ Consulta presupuestaria/i").first
    if not opcion.count():
        captura(page, "sin_sugerencia")
        raise SystemExit("El buscador no ofreció «Consulta presupuestaria».")
    opcion.click()
    page.wait_for_load_state("networkidle", timeout=ESPERA)
    page.wait_for_timeout(2000)
    captura(page, "consulta_abierta")


def inventario(page):
    """Lista los campos visibles: sirve para ver por que fallo un selector."""
    campos = page.locator("input:visible")
    log(f"   campos visibles: {campos.count()}")
    for i in range(min(campos.count(), 20)):
        c = campos.nth(i)
        try:
            info = {"name": c.get_attribute("name"), "id": c.get_attribute("id"),
                    "type": c.get_attribute("type"),
                    "placeholder": c.get_attribute("placeholder"),
                    "value": (c.input_value() or "")[:28]}
            log("     " + " ".join(f"{k}={v}" for k, v in info.items() if v))
        except Exception:
            pass


def elegir_sugerencia(page, texto, espera=25):
    """Espera a que aparezca la sugerencia y hace clic en ella.

    El autocompletado consulta al servidor y a veces tarda varios
    segundos. Esperar un tiempo fijo no alcanza: hay que sondear hasta
    que la opcion exista.
    """
    selectores = [f"li:has-text('{texto}')",
                  f"div[role=option]:has-text('{texto}')",
                  f"td:has-text('{texto}')",
                  f"*:visible:has-text('{texto}')"]
    for _ in range(espera * 2):
        for sel in selectores:
            c = page.locator(sel).last
            try:
                if c.count() and c.is_visible():
                    c.click(timeout=8_000)
                    return True
            except Exception:
                continue
        page.wait_for_timeout(500)
    return False


def llenar(page, campo, valor, sugerencia=None, reintentos=3):
    """Escribe en un campo por su atributo name y elige del autocompletado."""
    c = page.locator(f"input[name={campo}]").first
    if not c.count():
        raise SystemExit(f"No existe el campo '{campo}' en la pantalla.")

    for intento in range(1, reintentos + 1):
        esperar_procesando(page)
        c.click(timeout=15_000)
        c.fill("")
        page.wait_for_timeout(400)
        c.type(valor, delay=120)
        page.wait_for_timeout(1200)
        if not sugerencia:
            return
        if elegir_sugerencia(page, sugerencia):
            page.wait_for_timeout(1500)
            return
        log(f"   intento {intento}: no apareció «{sugerencia}», reintento")
        captura(page, f"sin_sugerencia_{campo}_{intento}")
        # Un caracter menos suele forzar una consulta nueva al servidor.
        c.fill("")
        page.wait_for_timeout(800)

    raise SystemExit(f"Escribí «{valor}» en {campo} pero nunca apareció la "
                     f"sugerencia «{sugerencia}» tras {reintentos} intentos.")


def filtrar(page):
    log("4. Esperando a que la pantalla termine de cargarse")
    # El POA y las fechas los pone la propia aplicacion; no hay que
    # escribirlos, solo esperar a que aparezcan. Si se toca el formulario
    # antes de tiempo, la consulta se queda vacia.
    for intento in range(30):
        poa = page.locator("input[name=poa]").first
        ini = page.locator("input[name=start_date]").first
        if poa.count() and poa.input_value() and ini.count() and ini.input_value():
            log(f"   POA {poa.input_value()} · desde {ini.input_value()}")
            break
        page.wait_for_timeout(1000)
    else:
        captura(page, "formulario_sin_cargar")
        inventario(page)
        raise SystemExit("El formulario no terminó de cargarse en 30 s: "
                         "revise formulario_sin_cargar.png")
    page.wait_for_timeout(1500)
    captura(page, "formulario_listo")

    log(f"   programa {PROGRAMA}")
    llenar(page, "program", PROGRAMA, "DIRECCIÓN GENERAL")
    captura(page, "programa_elegido")

    # Recargar la consulta con el filtro puesto.
    for sel in ["[title*='Recargar']", "[title*='Buscar']", "[title*='Refrescar']"]:
        b = page.locator(sel).first
        if b.count():
            b.click()
            break
    page.wait_for_load_state("networkidle", timeout=ESPERA)
    page.wait_for_timeout(4000)
    captura(page, "consulta_filtrada")

    filas = page.locator("tbody tr").count()
    log(f"   {filas} filas cargadas")
    if filas < 2:
        raise SystemExit("La consulta quedó vacía: revise consulta_filtrada.png")


TABLA_DATOS = "table.table-striped"   # distingue la tabla de datos del árbol lateral


def marcadas(page):
    # Contar solo las filas de la tabla principal (no el árbol lateral del menú,
    # que también tiene checkboxes en su tbody).
    return page.locator(f"{TABLA_DATOS} tbody input[type=checkbox]:checked").count()


def raton_sobre_las_filas(page):
    """Deja el puntero sobre las filas de datos.

    Quien se desplaza es la ventana, no la tabla: esta no tiene barra
    propia. Aun asi conviene tener el puntero sobre las filas para que la
    rueda no la intercepte ningun otro panel.
    """
    fila = page.locator("tbody tr").nth(3)
    if not fila.count():
        fila = page.locator("tbody tr").first
    if not fila.count():
        return False
    caja = fila.bounding_box()
    if not caja:
        return False
    page.mouse.move(caja["x"] + caja["width"] / 2, caja["y"] + caja["height"] / 2)
    return True


def posicion(page):
    """Cuanto se ha desplazado la ventana, en pixeles."""
    return page.evaluate("() => window.scrollY || "
                         "document.scrollingElement.scrollTop || 0")


def bajar_con_flechas(page, tope=2000):
    """Recorre la tabla con la flecha abajo.

    Es mas fiable que la rueda: el foco avanza fila por fila y la
    aplicacion va trayendo los tramos siguientes a medida que se llega al
    borde. Se pulsa en tandas y se mide si siguen apareciendo filas.
    """
    primera = page.locator("tbody tr").first
    if primera.count():
        try:
            primera.click(position={"x": 60, "y": 8}, timeout=8_000)
        except Exception:
            pass

    previo, quieto, pulsaciones = 0, 0, 0
    while pulsaciones < tope:
        for _ in range(25):
            page.keyboard.press("ArrowDown")
            pulsaciones += 1
        # La tabla trae cada tramo del servidor y tarda: si se corta la
        # espera demasiado pronto, se da por terminada a mitad de camino.
        page.wait_for_timeout(1500)
        cerrar_aviso(page)
        esperar_procesando(page, 30)
        page.wait_for_timeout(1000)
        filas = page.locator("tbody tr").count()
        if filas == previo:
            quieto += 1
            log(f"   sin filas nuevas ({quieto}/8) en {filas}")
            if quieto >= 8:
                break
        else:
            if filas - previo > 40 or previo == 0:
                log(f"   {filas} filas…")
            quieto = 0
        previo = filas
    log(f"   {previo} filas tras {pulsaciones} pulsaciones")
    return previo


def bajar_con_rueda(page):
    """Alternativa: rueda y desplazamiento por codigo."""
    previo, quieto = 0, 0
    for _ in range(400):
        filas = page.locator("tbody tr").count()
        if filas == previo:
            quieto += 1
            if quieto >= 5:
                break
        else:
            quieto = 0
        previo = filas
        raton_sobre_las_filas(page)
        page.mouse.wheel(0, 3000)
        page.evaluate("""() => {
            const ult = document.querySelector('tbody tr:last-child');
            if (ult) ult.scrollIntoView({block: 'end'});
            window.scrollTo(0, document.body.scrollHeight);
        }""")
        page.wait_for_timeout(500)
        esperar_procesando(page, 20)
    return previo


def bajar_hasta_el_final(page):
    """Carga toda la tabla: primero con flechas, y si no, con la rueda."""
    n = bajar_con_flechas(page)
    if n < 200:
        log("   pocas filas con las flechas; pruebo con la rueda")
        n = max(n, bajar_con_rueda(page))
    log(f"   {n} filas cargadas")
    return n


AVISO = ("div.modal.in, div.modal[style*='display: block'], "
         "div[role=dialog]:visible, .modal-dialog:visible")


def cerrar_aviso(page):
    """Cierra el aviso de eGob si esta en pantalla.

    Cuando la tabla se recarga, la aplicacion descarta los identificadores
    de la carga anterior. Si el script marca o exporta con los viejos, eGob
    responde con un modal: "Esta intentando leer los registros ... del
    modelo 'Cedula presupuestaria' que ya no existen". Se abre con
    data-backdrop static -no se cierra pulsando fuera- y como queda por
    encima intercepta todos los clics siguientes. De ahi los reintentos que
    terminan en tiempo agotado.

    Devuelve True si habia un aviso y se cerro.
    """
    dlg = page.locator(AVISO).first
    try:
        if not dlg.count() or not dlg.is_visible():
            return False
    except Exception:
        return False

    try:
        texto = (dlg.inner_text() or "").strip().replace(chr(10), " ")[:160]
        log(f"   aviso de eGob: {texto}")
    except Exception:
        pass

    for sel in ["button:has-text('ACEPTAR')", "button:has-text('Aceptar')",
                "button:has-text('Cerrar')", "button.close",
                "[data-dismiss=modal]", ".modal-footer button"]:
        b = dlg.locator(sel).first
        try:
            if b.count() and b.is_visible():
                b.click(timeout=8_000)
                break
        except Exception:
            continue
    else:
        page.keyboard.press("Escape")

    try:
        dlg.wait_for(state="hidden", timeout=10_000)
    except Exception:
        log("   ! el aviso no se cerro")
        return True
    page.wait_for_timeout(600)
    return True


def esperar_procesando(page, segundos=60):
    """Espera a que desaparezca la capa de 'Processing…'.

    Mientras la tabla trae datos, la aplicacion pone una capa por encima
    que se traga todos los clics. Si no se espera, cualquier accion falla
    con 'intercepts pointer events'.
    """
    cerrar_aviso(page)
    for _ in range(segundos * 2):
        capa = page.locator("text=/Processing/i")
        try:
            if not capa.count() or not capa.first.is_visible():
                page.wait_for_timeout(400)
                return True
        except Exception:
            return True
        page.wait_for_timeout(500)
    log("   ! la capa 'Processing' sigue ahí tras esperar")
    return False


def casilla_codigo(page):
    """La casilla de la cabecera de la tabla principal de datos.

    IMPORTANTE: en la página coexisten al menos dos tablas con checkbox en
    el thead: el árbol lateral de navegación (class='tree table-hover
    table-condensed no-responsive') y la tabla de datos (class='tree table
    table-hover table-striped ...'). Los selectores genéricos como
    'thead input[type=checkbox]' atrapan el checkbox del árbol lateral, que
    es el primero en el DOM. Hay que calificar con TABLA_DATOS para llegar
    al correcto.

    La th que contiene el checkbox tiene class='selection-state' y está en
    la posición 0 del thead, ANTES de la th 'Código' (posición 3). Por eso
    los XPath que buscan el checkbox dentro de la th 'Código' no funcionan.
    """
    intentos = [
        # Selector primario: tabla de datos → thead → th.selection-state
        f"{TABLA_DATOS} thead th.selection-state input[type='checkbox']",
        # Alternativa si la clase selection-state cambia: buscar por tabla-striped
        f"{TABLA_DATOS} thead input[type='checkbox']",
        # XPath equivalente como respaldo
        "xpath=//table[contains(@class,'table-striped')]//thead//input[@type='checkbox']",
        # Último recurso (puede atrapar el árbol lateral, pero mejor que nada)
        "th input[type=checkbox]",
    ]
    for sel in intentos:
        c = page.locator(sel).first
        if c.count():
            return c
    return None


def seleccionar_todo(page):
    """Baja hasta el fondo y ahi marca la casilla de la cabecera.

    El orden es el que se sigue a mano: primero se recorre toda la tabla
    para que carguen las filas, y una vez en el fondo se hace doble clic
    en la casilla que esta junto a 'Código'. Hace falta marcarla porque la
    exportacion respeta la seleccion: sin ella el archivo sale con una
    sola fila.
    """
    log("5. Bajando hasta el final de la tabla")
    esperar_procesando(page)
    total = bajar_hasta_el_final(page)
    captura(page, "tabla_completa")

    log("   subiendo para dejar la cabecera a la vista")
    # La seleccion se mantiene aunque se vuelva arriba; lo que no se puede
    # es pulsar una casilla que quedo fuera de la ventana.
    # IMPORTANTE: document.querySelector('thead') devuelve el thead del árbol
    # lateral (primer en el DOM), no el de la tabla de datos.  Hay que buscar
    # específicamente el thead de la tabla con class table-striped.
    page.evaluate("""() => {
        const tbl = document.querySelector('table.table-striped');
        const th  = tbl ? tbl.querySelector('thead') : document.querySelector('thead');
        if (th) th.scrollIntoView({block: 'center'});
        window.scrollBy(0, -200);
    }""")
    page.wait_for_timeout(2000)
    esperar_procesando(page)
    captura(page, "cabecera_a_la_vista")

    log("   marcando desde la casilla de Código")
    cab = casilla_codigo(page)
    if cab is None:
        captura(page, "sin_casilla_codigo")
        raise SystemExit("No encontré la casilla de la cabecera junto a «Código».")

    # La casilla tiene tres estados y arranca en el intermedio (se ve un
    # guion, no un visto). Desde ahi un clic lleva a "ninguna", no a
    # "todas": hay que pulsarla hasta que el conteo diga que estan todas.
    try:
        cab.scroll_into_view_if_needed(timeout=8_000)
    except Exception:
        pass
    page.wait_for_timeout(800)

    def pulsar():
        # Nunca force=True a ciegas: si hay un aviso encima, el clic se lo
        # lleva el modal y la casilla no se entera.
        cerrar_aviso(page)
        try:
            cab.click(timeout=10_000)
            return True
        except Exception:
            if cerrar_aviso(page):
                try:
                    cab.click(timeout=10_000)
                    return True
                except Exception:
                    pass
            caja = cab.bounding_box()
            if caja:
                page.mouse.click(caja["x"] + caja["width"] / 2,
                                 caja["y"] + caja["height"] / 2)
                return True
        return False

    for intento in range(1, 5):
        if not pulsar():
            log(f"   intento {intento}: no pude pulsar la casilla")
            break
        page.wait_for_timeout(2500)
        # Aqui aparece el aviso de registros inexistentes: la tabla se
        # recargo mientras se bajaba y los ids que envio el navegador son de
        # la carga anterior. Se cierra y se vuelve a recorrer la tabla, que
        # es lo unico que devuelve ids validos.
        if cerrar_aviso(page):
            log("   los identificadores estaban vencidos; recargo la tabla")
            esperar_procesando(page)
            total = bajar_hasta_el_final(page)
            page.evaluate("""() => {
                const tbl = document.querySelector('table.table-striped');
                const th  = tbl ? tbl.querySelector('thead') : null;
                if (th) th.scrollIntoView({block: 'center'});
                window.scrollBy(0, -200);
            }""")
            page.wait_for_timeout(1500)
            cab = casilla_codigo(page)
            if cab is None:
                break
            continue
        esperar_procesando(page)
        n = marcadas(page)
        estado = cab.evaluate("el => el.indeterminate ? 'intermedio' : "
                              "(el.checked ? 'marcada' : 'vacía')")
        log(f"   intento {intento}: {n} de {total} marcadas (casilla {estado})")
        if n >= max(2, total - 1):
            captura(page, "todo_seleccionado")
            return n

    captura(page, "seleccion_incompleta")
    log(f"   ! solo {marcadas(page)} de {total} marcadas; el archivo puede "
        f"salir incompleto")
    return marcadas(page)


def imprimir(page, opcion, destino):
    """Abre el menú de impresión, elige una opción y guarda la descarga."""
    esperar_procesando(page)
    boton = page.locator("[title*='mprimir'], button:has(i.fa-print), "
                         "[class*='print']").first
    if not boton.count():
        captura(page, "sin_boton_imprimir")
        raise SystemExit("No encontré el botón de impresión en la barra.")
    cerrar_aviso(page)
    boton.click(timeout=15_000)
    page.wait_for_timeout(1200)
    cerrar_aviso(page)
    captura(page, "menu_impresion")
    item = page.locator(f"text='{opcion}'").first
    if not item.count():
        opciones = page.locator("li:visible, a:visible").all_inner_texts()
        log("   opciones del menú: " + " | ".join(
            o.strip() for o in opciones if o.strip())[:400])
        raise SystemExit(f"No encontré «{opcion}» en el menú de impresión. "
                         f"Revise menu_impresion.png")
    with page.expect_download(timeout=180_000) as info:
        item.click()
    descarga = info.value
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    descarga.save_as(destino)
    return destino


def descargar_partidas(page):
    log("6. Descargando Partida XLS")
    destino = os.path.join(DATOS, "partidas.xls")
    imprimir(page, "Partida XLS", destino)
    tam = os.path.getsize(destino)
    log(f"   {destino} ({tam:,} bytes)")
    captura(page, "partida_xls")
    try:
        d = LP.leer(destino)
        t = d["total"] or {}
        log(f"   {len(d['partidas'])} partidas · {len(d['subpartidas'])} subpartidas"
            f" · codificado {t.get('codificado', 0):,.2f}")
        for aviso in d["avisos"]:
            log("   ! " + aviso)
    except Exception as e:
        log(f"   ! no pude verificar el archivo: {e}")
    return destino


def limpiar_seleccion(page):
    """Deja la tabla sin ninguna fila marcada.

    Entre una subpartida y la siguiente no puede quedar nada marcado: si
    se cuela otra fila, el reporte sale con dos bloques y el de nivel
    agregado viene vacio. Se desmarcan primero las filas una a una, que es
    lo predecible; la casilla de la cabecera solo se toca si quedan
    muchas, porque su comportamiento depende de en que estado este.
    """
    cerrar_aviso(page)
    n = marcadas(page)
    if n == 0:
        return
    if n <= 5:
        casillas = page.locator(f"{TABLA_DATOS} tbody input[type=checkbox]:checked")
        for i in range(casillas.count() - 1, -1, -1):
            try:
                casillas.nth(i).uncheck(timeout=8_000)
            except Exception:
                try:
                    casillas.nth(i).click(timeout=8_000, force=True)
                except Exception:
                    pass
        page.wait_for_timeout(600)

    if marcadas(page) == 0:
        return

    # Quedan muchas: se usa la cabecera, pulsando hasta que no quede nada.
    cab = casilla_codigo(page)
    if cab is None:
        return
    for _ in range(3):
        try:
            cab.click(timeout=8_000, force=True)
        except Exception:
            break
        page.wait_for_timeout(1200)
        if marcadas(page) == 0:
            return
    if marcadas(page):
        log(f"   ! quedaron {marcadas(page)} filas marcadas al limpiar")


def buscar_fila(page, codigo):
    """Localiza la fila de una subpartida entre las ya cargadas.

    No se usa la caja de FILTROS del sistema: ademas de ser lenta, cambia
    el contenido de la tabla y obliga a recargarla despues. Como al bajar
    ya quedaron cargadas las 288 filas, basta con encontrar la que lleva
    ese codigo, igual que haria una busqueda del navegador.

    El codigo aparece recortado en pantalla ("73.08.11.2026.3...."), asi
    que la comparacion se hace contra el texto completo de la celda, que
    el navegador conserva aunque se muestre con puntos suspensivos.
    """
    idx = page.evaluate("""(cod) => {
        const tabla = document.querySelector('table.table-striped');
        if (!tabla) return -1;
        const filas = tabla.querySelectorAll('tbody tr');
        for (let i = 0; i < filas.length; i++) {
            const celdas = filas[i].querySelectorAll('td');
            for (let j = 0; j < Math.min(celdas.length, 4); j++) {
                const t = (celdas[j].getAttribute('title') ||
                           celdas[j].textContent || '').trim();
                if (t === cod) return i;
            }
        }
        return -1;
    }""", codigo)
    if idx < 0:
        return None
    return page.locator(f"{TABLA_DATOS} tbody tr").nth(idx)


def descargar_detalle(page, codigo):
    """Marca una sola subpartida y baja su Detalle de Movimiento.

    Solo puede quedar marcada la subpartida con codigo programatico
    completo: si se cuela una fila de nivel agregado, el reporte sale
    vacio, porque los movimientos cuelgan de la subpartida y no del grupo.
    """
    limpiar_seleccion(page)

    fila = buscar_fila(page, codigo)
    if fila is None:
        log(f"   ! {codigo}: no está entre las filas cargadas, se omite")
        return None

    try:
        fila.scroll_into_view_if_needed(timeout=8_000)
    except Exception:
        pass
    page.wait_for_timeout(400)

    casilla = fila.locator("input[type=checkbox]").first
    if not casilla.count():
        log(f"   ! {codigo}: la fila no tiene casilla")
        return None
    try:
        casilla.check(timeout=10_000)
    except Exception:
        cerrar_aviso(page)
        casilla.click(timeout=10_000, force=True)
    page.wait_for_timeout(1000)
    cerrar_aviso(page)

    n = marcadas(page)
    if n != 1:
        log(f"   ! {codigo}: quedaron {n} filas marcadas en vez de 1")
        if n == 0:
            return None

    destino = os.path.join(DETALLE, f"{codigo}.xls")
    imprimir(page, "Detalle de Movimiento Partida", destino)

    try:
        import leer_detalle_xls as LD
        d = LD.leer(destino)
        vivos = sum(b["n_movimientos"] for b in d["bloques"])
        log(f"      {vivos} movimiento(s)")
        for a in d["avisos"][:2]:
            log("      ! " + a)
    except Exception as e:
        log(f"      ! no pude leer el detalle: {str(e)[:60]}")

    limpiar_seleccion(page)
    return destino


def descargar_detalle_lote(page, codigos):
    """Marca varias subpartidas y baja un solo archivo con todas.

    El reporte admite varios bloques, uno por cada fila marcada. Sale mas
    rapido que ir de una en una, con dos condiciones: que todas sean
    subpartidas con codigo programatico completo -las de nivel agregado
    salen vacias- y que ninguna quede sin marcar.
    """
    limpiar_seleccion(page)

    puestas, faltan = [], []
    for codigo in codigos:
        fila = buscar_fila(page, codigo)
        if fila is None:
            faltan.append(codigo)
            continue
        try:
            fila.scroll_into_view_if_needed(timeout=8_000)
        except Exception:
            pass
        casilla = fila.locator("input[type=checkbox]").first
        try:
            casilla.check(timeout=10_000)
            puestas.append(codigo)
        except Exception:
            try:
                casilla.click(timeout=8_000, force=True)
                puestas.append(codigo)
            except Exception:
                faltan.append(codigo)
        page.wait_for_timeout(300)

    n = marcadas(page)
    log(f"   {n} filas marcadas de {len(codigos)} pedidas")
    for c in faltan:
        log(f"   ! {c}: no se pudo marcar")
    if n == 0:
        return None

    sello = datetime.now(TZ).strftime("%Y-%m-%d")
    destino = os.path.join(DETALLE, f"detalle_{sello}.xls")
    imprimir(page, "Detalle de Movimiento Partida", destino)

    try:
        import leer_detalle_xls as LD
        d = LD.leer(destino)
        vivos = sum(b["n_movimientos"] for b in d["bloques"])
        log(f"   {len(d['bloques'])} bloque(s) · {vivos} movimiento(s)")
        vacios = [b["codigo"] for b in d["bloques"] if b["vacio"]]
        if vacios:
            log(f"   ! {len(vacios)} bloque(s) vacío(s): " + ", ".join(vacios[:3]))
    except Exception as e:
        log(f"   ! no pude leer el detalle: {str(e)[:60]}")

    limpiar_seleccion(page)
    return destino


# ------------------------------------------------------------------- main

def subpartidas_a_bajar(ruta_xls, todas):
    """Qué subpartidas necesitan detalle en esta corrida."""
    hoy = LP.leer(ruta_xls)
    previo = os.path.join(DATOS, "partidas_anterior.json")

    if todas or not os.path.exists(previo):
        sel = [s for s in hoy["subpartidas"]
               if s["certificado"] or s["comprometido"] or s["devengado"]]
        motivo = "primera corrida: todas las que tienen movimiento"
    else:
        import json
        with open(previo, encoding="utf-8") as f:
            ayer = json.load(f)
        cambios = LP.comparar(ayer, hoy)
        codigos = {c["codigo"] for c in cambios}
        sel = [s for s in hoy["subpartidas"] if s["codigo"] in codigos]
        motivo = f"{len(cambios)} subpartida(s) con cambios desde la corrida anterior"
    return hoy, sel, motivo


def guardar_referencia(datos):
    import json
    os.makedirs(DATOS, exist_ok=True)
    with open(os.path.join(DATOS, "partidas_anterior.json"), "w",
              encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser(description="Descarga la consulta presupuestaria de eGob.")
    ap.add_argument("--todas", action="store_true",
                    help="Bajar el detalle de todas las subpartidas con movimiento")
    ap.add_argument("--sin-detalle", action="store_true",
                    help="Solo el Partida XLS")
    ap.add_argument("--ver", action="store_true", help="Navegador visible")
    ap.add_argument("--lote", action="store_true",
                    help="Marcar todas las subpartidas con cambios y bajar "
                         "un solo archivo, en vez de una por una")
    ap.add_argument("--solo", metavar="CODIGO",
                    help="Bajar el detalle de una sola subpartida, para probar")
    ap.add_argument("--sin-seleccion", action="store_true",
                    help="No marcar las filas (el XLS saldrá con una sola)")
    a = ap.parse_args()

    usuario = os.environ.get("EGOB_USUARIO")
    clave = os.environ.get("EGOB_CLAVE")
    if not usuario or not clave:
        raise SystemExit("Faltan las variables EGOB_USUARIO y EGOB_CLAVE.")

    os.makedirs(DATOS, exist_ok=True)
    os.makedirs(DETALLE, exist_ok=True)
    inicio = time.time()

    with sync_playwright() as pw:
        navegador = pw.chromium.launch(headless=not a.ver)
        ctx = navegador.new_context(
            accept_downloads=True,
            viewport={"width": 1600, "height": 1000},
            ignore_https_errors=True,      # certificado interno del municipio
        )
        page = ctx.new_page()
        page.set_default_timeout(ESPERA)

        try:
            iniciar_sesion(page, usuario, clave)
            abrir_financiero(page)
            abrir_consulta(page)
            filtrar(page)
            if a.sin_seleccion:
                esperar_procesando(page)
            else:
                seleccionar_todo(page)
            xls = descargar_partidas(page)

            if a.solo:
                log(f"7. Detalle — solo {a.solo}")
                descargar_detalle(page, a.solo)
            elif not a.sin_detalle:
                hoy, sel, motivo = subpartidas_a_bajar(xls, a.todas)
                log(f"7. Detalle — {motivo}")
                if a.lote and sel:
                    descargar_detalle_lote(page, [x["codigo"] for x in sel])
                    guardar_referencia(hoy)
                    captura(page, "final")
                    log(f"Listo en {time.time() - inicio:.0f} s")
                    return
                for i, s in enumerate(sel, 1):
                    log(f"   {i}/{len(sel)}  {s['codigo']}")
                    try:
                        descargar_detalle(page, s["codigo"])
                    except PWTimeout:
                        log(f"   ! {s['codigo']}: se agotó el tiempo, se omite")
                    except Exception as e:
                        log(f"   ! {s['codigo']}: {e}")
                guardar_referencia(hoy)

            captura(page, "final")
            log(f"Listo en {time.time() - inicio:.0f} s")
        except Exception:
            captura(page, "error")
            try:
                with open(os.path.join(CAPTURAS, "error.html"), "w",
                          encoding="utf-8") as f:
                    f.write(page.content())
            except Exception:
                pass
            raise
        finally:
            ctx.close()
            navegador.close()


if __name__ == "__main__":
    main()
