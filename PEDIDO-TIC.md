# Solicitud a la Dirección de TIC — acceso automatizado a la cédula presupuestaria

## Qué se está haciendo

La Dirección Financiera publicó un tablero de seguimiento presupuestario que
lee la **Cédula Presupuestaria de Gasto** de eGob y muestra la ejecución por
partida, subpartida y proyecto. El tablero ya funciona: corre en un servidor de
la intranet, procesa el PDF del reporte y se actualiza al recibirlo.

Hoy ese PDF se descarga a mano una vez al día y se carga al tablero desde una
página web. Funciona, pero depende de que una persona lo haga todos los días.

## Qué se pide

Que el servidor pueda descargar por sí mismo el reporte una vez cada 24 horas.
Nada más: el procesamiento, la publicación y el tablero ya están resueltos y no
cambian.

Concretamente, tres cosas:

**1. Cómo se obtiene el reporte por programa.** Cualquiera de estas sirve:

- Un servicio web o API que devuelva la cédula (JSON, CSV, XML o PDF).
- La URL directa del reporte con sus parámetros. En la interfaz actual el
  reporte se genera con: rango de fechas, dirección administrativa y formato de
  salida. Necesitamos saber cómo se pasan esos tres valores en la petición.
- Acceso de solo lectura a las tablas de ejecución presupuestaria de la base de
  datos, si resulta más simple que exponer el reporte.

**2. Un usuario de servicio de solo lectura.** Con permiso únicamente para
consultar este reporte. No se requiere ningún permiso de escritura, ni acceso a
otros módulos de eGob. Preferimos que sea un usuario aparte y no las
credenciales de un funcionario, para poder revocarlo sin afectar a nadie.

**3. Cómo se autentica.** Si eGob usa token, clave de API, sesión con
formulario de inicio, o autenticación integrada de Windows. Con eso ajustamos el
script de descarga.

## Qué se hará con eso

Un script que se autentique, descargue el PDF y lo deje en una carpeta del
servidor. Aproximadamente veinte líneas. Se ejecuta una vez al día por tarea
programada. No escribe nada en eGob, no modifica datos y no consume más que una
petición diaria.

## Datos técnicos del tablero

| | |
|---|---|
| Servidor | (completar: nombre o IP en la intranet) |
| Sistema | Linux o Windows Server |
| Puerto | 8080, solo dentro de la red municipal |
| Software | Python 3 y poppler-utils; sin base de datos ni servicios externos |
| Datos que consume | Un reporte de solo lectura, una vez al día |
| Datos que expone | Ninguno hacia fuera de la red municipal |

## Referencia del reporte

Nombre en eGob: **Cédula Presupuestaria de Gasto**
Ejemplo del reporte que se usa hoy: emitido el 11/08/2026 a las 08:38:12,
período 2026-01-01 al 2026-12-31, Dirección General de Gestión de Obras
Públicas, 5 páginas, 41 partidas y 218 subpartidas.

Se adjunta ese PDF como muestra del formato exacto que se necesita.

## Mientras tanto

El tablero sigue funcionando con la carga manual diaria, así que esto no
bloquea nada. Automatizarlo solo elimina un paso repetitivo y el riesgo de que
un día nadie lo haga.

---

Contacto: (completar)
Fecha: (completar)
