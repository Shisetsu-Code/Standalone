# Play’n GO

Catálogo importado de los cuatro HAR suministrados: 477 fichas, orden original por fecha, sin reutilizar sus sesiones. Los HAR no contienen los mensajes WebSocket de las rondas.

El adaptador inicia sesiones anónimas nuevas en el lanzador oficial `practice=1&demo=2`, exige moneda `DEMO` y comprueba un saldo inicial sin ronda activa. El protocolo usa comandos nativos dentro de SignalR MessagePack. Ninguna cuenta real interviene.

Los lotes `batches/1-100`, `batches/101-200`, `batches/201-300` y `batches/301-400` tienen catálogos, índices, evidencias y auditorías separados. Cada caso guarda su entrada y los pasos internos en `traces/`; las pruebas rechazadas que requirieron corregir parámetros permanecen en `rejected/` con sus hashes. No se repite automáticamente una entrada enviada. Los parámetros provienen del componente de apuesta publicado por cada juego y de las denominaciones nativas, no del índice de la denominación.

La auditoría vuelve a calcular apuesta, premio, cierre y saldo desde los mensajes, reproduce el perfil desde el JavaScript guardado y comprueba los hashes de los resultados anteriores. La respuesta 52 con segundo campo 0 confirma cierre; se exigen además cero tiradas gratis restantes y la igualdad `saldo inicial - coste + premio = saldo final`.

GoUltra se incluye únicamente cuando está registrado en el componente del juego y SETUPDATA60 lo habilita. HyperSpin no se clasifica como compra: los parámetros revisados controlan tiempos e interacción. No encontrar palabras de compras en el código no demuestra ausencia universal de otros controles. El informe conserva esta limitación.

GO CRAPS utiliza un adaptador separado de fichas y dados. La muestra coloca una sola ficha mínima en Pass Line y, si sigue activa, continúa esa misma apuesta sin añadir fichas. Su premio se obtiene del campo 1 de SPINEND, no del campo 2 usado en los slots. El conversor oficial ignora campos sobrantes de la respuesta 1; se conservan como datos sin interpretar. Otras selecciones de apuestas de mesa y todos los desenlaces naturales posibles quedan fuera de esta muestra.

European Roulette Pro usa una apuesta mínima al cero, posición nativa 150. El retorno bruto de un cero ganador incluye el premio 35:1 y la ficha devuelta; se contrasta con el resultado y con el saldo. La muestra registrada terminó sin premio; la rama ganadora se comprueba con una prueba de regresión, sin presentarla como resultado observado en vivo.

3-Hand Casino Hold’em usa una sola posición con ante mínimo, sin AA, y Fold únicamente después del TURN nativo correspondiente. Se comprueban la respuesta Fold, el resultado sin premios y el saldo cerrado. Call y showdown no están cubiertos por esta muestra. Los tres adaptadores de mesa rechazan comandos previos desconocidos y acciones posteriores al cierre; ruleta y Hold’em comprueban también que el saldo de bono no cambie.

Comandos:

```text
python playngo_run.py --execute
python playngo_run.py --batch 101-200 --execute
python playngo_run.py --go-ultra --execute
python playngo_audit.py
python playngo_audit.py --batch 101-200
python playngo_reports.py
python playngo_reports.py --batch 101-200
python -m unittest discover -q
```

`--retry-rejected` exige un rechazo nativo explícito recibido y un cambio comprobado del tuple de apuesta; archiva el intento anterior antes de iniciar una sesión nueva. No sirve para reintentar timeouts o respuestas inciertas.

`--retry-rejected-continuation` admite únicamente el caso documentado de FEATURE_COLLECT rechazado después de `needsCollect=false`, con todas las respuestas recibidas. Conserva el intento anterior y permite una sola nueva muestra con la regla corregida de cobro normal. `FEATURE_END` con indicador 0 no solicita `FEATURE_COLLECT`; con indicador 1 sí lo solicita.

Un título se clasifica como no disponible únicamente cuando la respuesta oficial identifica explícitamente `Game not enabled` para ese juego y no se envió ninguna apuesta. No se convierte un error genérico o un timeout en indisponibilidad ni en un caso completado.


## Cierre del catálogo · lote 401–477

Lote final: 77 casos completos, 0 GoUltra, 0 pendientes. Incluye 65 slots y 12 muestras de mesa/especiales. Total de los cinco lotes: 476 demos con entrada normal conciliada, 17 GoUltra; una demo no habilitada por el proveedor (Detroit Red Wings Winged Reelers, id901). Las tres manos parciales de diagnóstico de póker se conservan por separado y no cuentan como cierres. La cobertura sigue siendo una muestra por juego y cada GoUltra identificado; no cubre todos los desenlaces naturales ni todas las apuestas de mesa.
