# Tablero de la cédula presupuestaria

Seguimiento de la ejecución presupuestaria del GAD Municipal del Cantón
Riobamba. Cada noche entra a eGob, descarga la consulta presupuestaria y
publica un tablero actualizado.

**[Ver el tablero →](https://USUARIO.github.io/tablero-cedula-presupuestaria/)**

## Qué hace

```
00:00  GitHub Actions
       → entra a eGob (CAS) y abre la consulta presupuestaria
       → filtra por el programa 3.6 y descarga partidas.xls
       → compara con la corrida anterior
       → baja el detalle de las subpartidas que cambiaron
       → regenera el tablero y lo publica
```

Antes esto era un PDF que alguien descargaba a mano y una matriz en Excel que
se llenaba a mano. Ahora el detalle sale del propio sistema: cada certificación
con su beneficiario, su objeto y su recorrido de certificado a pagado. Las
anulaciones aparecen como tales en lugar de diluirse en un saldo.

## Las cuatro pestañas

**Resumen** — indicadores generales, embudo de ejecución con la caída entre
etapas, estado de las certificaciones, mapa de partidas por monto y ejecución,
y una tarjeta por partida con sus tres contrataciones principales.

**Presupuesto total** — la lista desplegable: 41 partidas → 218 subpartidas →
certificaciones.

**Gasto computable** — la misma lista, restringida a los grupos 73, 75, 77, 84
y 88.

**Proyectos** — cada certificación con su estado y la partida que la financia.

## Los archivos

| Archivo | Qué hace |
|---|---|
| `1_descargar.py` | Entra a eGob con Playwright y baja los XLS |
| `2_generar.py` | Los convierte en `publico/datos.json` |
| `leer_partida_xls.py` | Lee el Partida XLS y compara dos corridas |
| `leer_detalle_xls.py` | Lee el Detalle de Movimiento Partida |
| `leer_pdf.py` | Lee la cédula en PDF, para archivos históricos |
| `publico/` | Lo que se publica en GitHub Pages |
| `PUBLICAR.md` | Cómo poner esto en marcha |

## Criterios

**Gasto computable** — grupos 73, 75, 77, 84 y 88. Una constante en
`2_generar.py`.

**Estado de una certificación** — se deriva de las cifras, no de un campo del
sistema:

| Estado | Regla |
|---|---|
| Planificado | sin certificación |
| Certificado | certificado, sin comprometer |
| Comprometido | comprometido, sin devengar |
| En ejecución | devengado parcial |
| Devengado | el devengado alcanza al comprometido |
| Anulada | las modificaciones la dejaron en cero |

## Probar en local

```bash
pip install -r requirements.txt
playwright install chromium
export EGOB_USUARIO=... EGOB_CLAVE=...

python3 1_descargar.py --ver --sin-detalle    # solo el Partida XLS
python3 1_descargar.py --ver --lote           # y el detalle de lo que cambió
python3 2_generar.py                          # arma el tablero
python3 pruebas/test_lectores.py
```

`--ver` abre el navegador para ver qué hace. Cada paso deja una captura en
`capturas/`, y en GitHub Actions quedan como artefacto de la corrida.

## Datos

El repositorio no guarda las descargas: `.gitignore` deja fuera `datos/*.xls`,
`datos/detalle/` y `capturas/`. Sí se versiona `datos/partidas_anterior.json`,
que es la foto contra la que se compara al día siguiente, y `publico/`, que es
lo que se publica.

## Licencia

MIT. Ver [LICENSE](LICENSE).
