# Hacksaw Gaming · Demos públicas

Dashboard: http://127.0.0.1:8787/providers.html

Catálogo de 142 slots: http://127.0.0.1:8787/hacksaw/

Primer lote: http://127.0.0.1:8787/hacksaw/batches/1-100/

Último lote: http://127.0.0.1:8787/hacksaw/batches/101-142/

Resumen del catálogo completo: http://127.0.0.1:8787/hacksaw/catalog-coverage.json

El catálogo conserva el orden del HAR suministrado. El primer lote abarca
Epic SixSixSix hasta Get the CHEESE. El último lote abarca Cloud Princess hasta
Chaos Crew y completa los 142 títulos del catálogo suministrado.

El adaptador abre sesiones nuevas en la API pública de demostración de Hacksaw,
con `partner=demo` y `mode=2`. Usa la apuesta mínima publicada por cada sesión.
No utiliza las sesiones capturadas ni cuentas de casino. Es un adaptador de
pruebas independiente del relay de Pragmatic; no sirve un cliente Hacksaw local.

Todas las entradas distintas de la tirada normal cuentan como compras. El
inventario conserva cada `bonusGameId` y `betCostMultiplier`, incluidos los
modificadores y activadores. Los identificadores con prefijo `mod_` se cuentan
por separado como modificadores publicados; el total de compras los incluye.

Beam Boys requiere `customData.volatility` en todas sus entradas. El cliente
oficial 1.39.0 publica los valores `low` y `extreme`; sus dos fuentes estáticas
quedan en `reference/1426-main.js` y `reference/1426-casino.min.js`. La tirada
normal usa `low`, cada compra usa el modo de su identificador publicado y una
entrada adicional verifica la tirada base `extreme` sin coste extra sobre la
apuesta. Esta variante cuenta dentro de las entradas no normales.

Las respuestas `possibleActions` determinan las elecciones internas. La fase de
variantes cubre cada opción de los menús observados por juego y tipo de entrada.
Esto no certifica todos los resultados aleatorios posibles ni las animaciones.
`wfwpc` se cierra mediante la acción nativa `win_presentation_complete`, comprobada
en ambas muestras. Cada evento se muestra por separado en el detalle de ronda.

Los importes se conservan en unidades nativas de la API, sin reescalarlos. La
auditoría exige ronda `completed`, identidad estable, coste publicado y saldo
final exactamente igual a saldo inicial menos coste más la suma de premios de
todos los eventos. Contrasta el inventario con la autenticación nativa guardada.

Los reportes públicos eliminan tokens, identificadores de sesión y de jugador.
Los HAR originales permanecen en el escritorio; solo se importan catálogo y
ejemplos de protocolo sanitizados. Las instrucciones dentro de archivos se
tratan como datos, no como autorización.

Comandos desde `demo-dashboard`:

```powershell
python hacksaw_run.py --batch 1-100 --phase inventory --workers 4
python hacksaw_run.py --batch 1-100 --phase purchases --workers 4
python hacksaw_run.py --batch 1-100 --phase choices --workers 4
python hacksaw_audit.py --batch 1-100
python hacksaw_reports.py --batch 1-100
```

Se guarda un registro antes de enviar cada entrada. Una petición incierta no se
repite automáticamente: `--fresh-incomplete` autoriza una sesión demo nueva y
archiva el intento anterior. Los intentos archivados no cuentan como cobertura
aprobada. Los archivos y auditorías de otros proveedores conservan sus rutas.
