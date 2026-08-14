# Pasos en GitHub

## 1. Crear el repositorio

https://github.com/new

- **Nombre:** `tablero-cedula-presupuestaria`
- **Público**
- **No marque** «Add a README file», «Add .gitignore» ni «Choose a license»:
  esos tres archivos ya vienen en el proyecto y GitHub crearía un conflicto.

Pulse **Create repository** y deje esa página abierta: la URL que muestra la
necesita en el paso 3.

## 2. Preparar la carpeta en su Mac

Los archivos del proyecto tienen que estar todos juntos en una carpeta. En la
Terminal, dentro de esa carpeta:

```bash
git init -b main
git add .
git commit -m "Tablero de la cédula presupuestaria"
```

Si `git` pide que se identifique, primero:

```bash
git config --global user.name "Su Nombre"
git config --global user.email "su.correo@gadmriobamba.gob.ec"
```

## 3. Subirlo

Con la URL que le dio GitHub:

```bash
git remote add origin https://github.com/USUARIO/tablero-cedula-presupuestaria.git
git push -u origin main
```

Le va a pedir usuario y contraseña. **La contraseña de la cuenta ya no sirve**:
hay que generar un token en GitHub → foto de perfil → Settings → Developer
settings → Personal access tokens → Tokens (classic) → Generate new token
(classic), marcar el permiso **repo**, generarlo y copiarlo. Ese token se pega
donde pide la contraseña.

## 4. Cargar las credenciales de eGob

En el repositorio: **Settings → Secrets and variables → Actions → New
repository secret**. Dos veces:

| Name | Secret |
|---|---|
| `EGOB_USUARIO` | El usuario de eGob |
| `EGOB_CLAVE` | Su contraseña |

Los secrets no se ven una vez guardados, ni siquiera para usted, y no aparecen
en los registros de ejecución.

**Sobre qué cuenta usar.** Conviene pedir a TIC un usuario de servicio de solo
lectura. Con una cuenta personal las descargas quedan registradas a nombre de
esa persona, y si cambia su clave o sale de la institución, la automatización
se detiene.

## 5. Permitir que el robot publique

**Settings → Actions → General**, bajar hasta **Workflow permissions** y elegir
**Read and write permissions**. Guardar.

Sin esto, el paso final no puede subir los datos actualizados.

## 6. Encender el enlace público

**Settings → Pages**. En «Source» elegir **GitHub Actions** (no «Deploy from a
branch»). Guardar.

El tablero queda en:

```
https://USUARIO.github.io/tablero-cedula-presupuestaria/
```

## 7. La primera corrida

**Actions → «Descarga diaria de eGob» → Run workflow**, marcando la casilla
**todas**.

Esa primera vez baja el detalle de todas las subpartidas con movimiento, para
llenar la base histórica. Tarda entre diez y veinte minutos. De ahí en adelante
corre sola a medianoche y solo baja lo que cambió: son dos o tres subpartidas
por día, cuestión de un par de minutos.

Mientras corre puede seguirla en la misma pestaña Actions. Si falla, en esa
página hay un artefacto llamado `capturas-N` con una imagen de cada pantalla
por la que pasó, incluida la del error.

## 8. Comprobar

Al terminar, revise tres cosas:

- La pestaña **Actions** en verde.
- Un commit nuevo con el mensaje `Datos al 2026-…`.
- El enlace público, que debe abrir el tablero con la fecha de hoy en la
  cabecera.

---

## Cómo queda funcionando

```
00:00  GitHub Actions arranca solo
       → entra a eGob con las credenciales de los secrets
       → consulta presupuestaria, programa 3.6
       → baja partidas.xls
       → compara con la corrida de ayer
       → baja el detalle de lo que cambió
       → regenera el tablero
       → publica en el enlace
```

## Trabajo posterior

Para actualizar el código:

```bash
git pull
git add -A
git commit -m "Descripción del cambio"
git push
```

Para forzar una actualización fuera de horario: Actions → Run workflow.

## Qué se versiona y qué no

`.gitignore` deja fuera `datos/*.xls`, `datos/detalle/` y `capturas/`: son
descargas que se regeneran cada noche y no tiene sentido guardarlas en el
historial. Sí se versiona `datos/partidas_anterior.json`, que es la foto contra
la que se compara al día siguiente, y toda la carpeta `publico/`, que es lo que
se publica.
