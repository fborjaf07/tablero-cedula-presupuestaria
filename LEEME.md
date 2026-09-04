# Publicar el tablero de Obras Publicas

Repo: fborjaf07/tablero-cedula-presupuestaria

Tres archivos, en este orden:

1. `index.html` -> raiz del repo.
   Es el tablero. Trae una instantanea de los datos dentro, la pinta al
   instante y enseguida la reemplaza con el `datos.json` del repo. Por eso
   se actualiza solo cada noche sin volver a compilarlo.

2. `datos.json` -> raiz del repo.
   Los datos de hoy. Sirve para que el tablero funcione antes de la primera
   corrida del workflow; despues lo sobreescribe el propio workflow.

3. `egob.yml` -> `.github/workflows/egob.yml` (reemplaza el actual).
   Dos cambios:
   - el generador ya no escribe `index.html` (ahora `tablero-generado.html`),
     asi no pisa el tablero definitivo;
   - antes de publicar comprueba que `datos.json` traiga partidas, para no
     subir un archivo vacio si eGob falla a mitad de camino.

Despues, en Settings -> Pages, servir la rama `main` desde `/ (root)`.
