# Verificación del runner

## Ampliación del 13 de noviembre de 2026

Base de esta ampliación: `6e44a4408813a71bae867c83e32591529a031e97`. Los apartados posteriores describen comprobaciones históricas; no equivalen a ejecutar remotamente la versión actual.

Se añadieron pruebas para las respuestas HTTP parciales, un único arranque HTTP renovado antes de apostar, rechazo de reenvíos financieros, recuperación auditada sin apuesta, separación entre cobertura ejecutable y total, validación de la partición del inventario, alias canónicos y cierre de Pragmatic en la última continuación permitida. Los recibos privados conservan los dueños anteriores y se excluyen de la exportación pública.

El collector y el bridge tienen regresiones sin tráfico a proveedores para cierre explícito, bloqueos 403, catálogo incompleto, todos los tipos de modo, exclusión entre procesos, retenciones compartidas, recibos decimales independientes, coste circular rechazado, preparaciones pagadas y continuidad de sus saldos. El bridge incluye una ejecución sintética completa y rechazo de repetición. Hay pruebas de terminación de procesos descendientes para Unix y del Job Object de Windows.

Comandos desde la raíz del repositorio:

```sh
python -B -m unittest discover -s bet-collector/tests -p 'test_*.py' -v
python -B -m unittest discover -s game-runner/tests -p 'test_*.py' -v
cd game-runner
cargo +1.99.1 fmt --all -- --check
cargo +1.99.1 test --locked
cargo +1.99.1 clippy --locked --all-targets -- -D warnings
```

Evidencia de esta ampliación: las cuatro regresiones iniciales de HTTP y renovación fallaron contra la implementación anterior en CI; las pruebas de recibos y estados compartidos también tuvieron fallos previos observados. La matriz `Rust demo runner` de la PR registra la compilación, pruebas y análisis estático de cada revisión exacta en Linux y Windows. El estado final de esa matriz es la referencia para los resultados de la versión publicada.

No se ejecutaron nuevas campañas remotas para esta ampliación. Un preflight correcto acredita disponibilidad de contratos y dependencias locales; una prueba sintética acredita su comportamiento frente a esos paquetes. Ninguna de las dos equivale a completar todos los modos contra los servidores del proveedor.

El ejecutable Linux producido por CI se comprobó también fuera del runner de Actions, importando el inventario completo y ejecutando `plan-all`, `check` y `coverage` sin llamadas a proveedores. Con los bindings nativos publicados produjo 3.195 trabajos: 1.106 normales, 1.399 compras, 47 antebets, 313 boosters y 330 variantes. Las otras 183 entradas equivalentes de Reel Kingdom se vincularon a su trabajo canónico. Las 16.685 modalidades restantes y 648 juegos sin modalidades quedaron identificados como omisiones; cero muestras se presentaron como ejecutadas. El total de modalidades concilia: 3.195 + 183 + 16.685 = 20.063. Estas cifras describen la planificación nativa; la ampliación por suite depende de sus contratos y dependencias instalados.

### Límites que permanecen explícitos

- Los contratos externos, fuentes privadas, dependencias o ejecutables ausentes quedan como omisiones de planificación; el bridge no los reemplaza con históricos.
- Los workers que requieren transporte de navegador permanecen fuera del bridge HTTP: KA Gaming, Belatra, RedTiger, NetEnt y Playson legacy. Playson nativo sigue disponible con su binding público revisado.
- BGaming legacy, Playtech agregado, Irondog sin saldo demo autoritativo, Habanero portmessage y bancos Mascot con premio nativo ambiguo requieren contrato monetario completo antes de ejecutar por el bridge.
- Los modos condicionales necesitan un presupuesto finito y conservar cada preparación pagada. Agotar ese presupuesto no cuenta como completar el modo.
- Kendoo conserva su pausa; los modelos locales NGM no se presentan como liquidaciones remotas.

## Evidencia histórica de la entrega base — 12 de noviembre de 2026

Base de contratos e inventarios: `fd95f62d39ce5abe236a62b66d7cdf0d0f394d33` de `Shisetsu-Code/Evidencia`. No se modificaron inventarios, informes históricos, capturas ni las evidencias NetEnt congeladas.

## Comprobaciones ejecutadas

| Comprobación | Resultado observado |
|---|---|
| `cargo fmt --check` | Correcto |
| `cargo clippy --locked --all-targets -- -D warnings` | Correcto, sin advertencias |
| `cargo test --locked --offline` | 73 pruebas de biblioteca y 2 pruebas de CLI aprobadas, incluyendo preflight e informe de `smoke-all` |
| `cargo build --locked --offline --release` | Ejecutable Linux compilado con Rust 1.99.1 |
| Regresiones Python Endorphina/Playson | 19 pruebas aprobadas en la entrega base; no se modificaron en el seguimiento HTTP |
| Importación del inventario publicado | 35 proveedores, 9.874 registros de juego, 20.063 modalidades |
| Plan de ejemplo con dos proveedores y cinco trabajos | Validación correcta, cero solicitudes de red |

Comando de regresiones Python, desde `demo-dashboard/`, con las dependencias del proyecto instaladas:

```sh
python -m unittest test_endorphina_batches test_endorphina_client test_endorphina_durability test_endorphina_rounds test_playson_stdout -q
```

El inventario importado tiene ID semántico `3158af3b9f88acab5278e6addd5e34ca94fcbf5fa5e2229323cef7e056ca90c4`. La importación conserva el tipo original, claves nativas y procedencia del hash. Los hashes históricos CRLF se reconocen explícitamente; las modificaciones de contenido se rechazan.

## Qué verifican las pruebas

- Exclusión del proveedor entre procesos y entre los alias Pragmatic/Reel Kingdom, sin expiración artificial del lock.
- Paralelismo entre proveedores distintos y orden secuencial dentro del mismo proveedor.
- Intención persistida antes de que el servidor local reciba la solicitud; pérdida de respuesta sin reenvío; bloqueo que sobrevive al reinicio.
- Sesión inmutable, respuestas que no pueden sobrescribirse y frames WebSocket guardados antes de analizar JSON inválido.
- Muestras idempotentes por campaña/trabajo/índice; una muestra fallida no se omite al relanzar la campaña para seguir con la siguiente.
- Cierre con liquidación inconsistente produce `validation_failed` y hold del proveedor en una misma transacción. El desbloqueo manual se audita y no admite raíces pendientes.
- Conciliación decimal exacta, incluidas cantidades demasiado pequeñas, productos que perderían precisión y precios ante expresados como decimales.
- Exportación con filtros, IDs conservados, rutas sin colisiones ni escape, permisos privados y rechazo de sobrescritura. La exportación pública omite sesiones, configuración y payloads crudos.
- Transporte WSS por CONNECT cuando se configura relay, sin salida directa alternativa.

Cinco pruebas integrales usan **respuestas sintéticas y un servidor HTTP local**, atravesando `NativeExecutor`, `RunContext` y `Store.complete`: Hacksaw normal/compra, y Pragmatic normal/compra/nivel `bl-1`. Verifican dueño previo al envío, identificadores, precio, secuencia, continuidad sin otra entrada pagada y liquidación final. También exigen cookies emitidas por el arranque y las redirecciones, incluyendo rotación, múltiples `Set-Cookie`, cookies `Secure` y aislamiento de dominio/ruta. Dos pruebas negativas omiten la cookie necesaria y reciben 403 antes de cualquier solicitud financiera. Estas fixtures no son capturas remotas ni demuestran disponibilidad actual del proveedor.

El seguimiento de sesión añade además pruebas de redirección inicial Endorphina permitida/rechazada/acotada, rango y muestreo de la clave anónima Peter & Sons, continuidad HTTP → WSS → HTTP, aislamiento entre sesiones independientes, retención de 403 de handshake sin reintento y compatibilidad exacta de serialización/hash con respuestas históricas. Las cookies privadas se comprueban excluidas de la exportación pública. El cuerpo de un rechazo WSS se conserva como bytes disponibles del buffer, sin afirmar que esté completo.

La preparación de Actions añade cuatro pruebas offline: clasificación de los 35 proveedores y sus cuatro trabajos ejecutables, rechazo de inventario o selección distintos, informe sin secretos que distingue HTTP de mensajes WSS y parada del alias canónico, y CLI sin red por defecto con rechazo de sobrescritura. El workflow se comprobó con un CLI simulado para salidas 2 y 124, incluido el sellado de diarios y la conservación de artefactos antes del fallo de cobertura. Estas verificaciones del mecanismo no equivalen a probar las demos remotas.

La revisión independiente de la entrega base encontró y permitió corregir el precio ante de Playson, la selección del premio acumulado de Pragmatic, las lecturas iniciales del saldo demo de Endorphina, acciones nativas desconocidas y la compatibilidad LF/CRLF del catálogo fijado. Una segunda revisión del seguimiento HTTP comprobó alcance de cookies, compatibilidad histórica, privacidad y ausencia de reenvíos. Se corrigió una expectativa de ruta en la fixture Endorphina. No quedaron hallazgos P1/P2 pendientes en esas revisiones.

## Comprobación remota y límites

En la entrega base se intentó una campaña de **una muestra normal Hacksaw, juego 2405**. Se detuvo en la lectura de `version.json` porque el entorno no resolvió `static-live.hacksawgaming.com` (error DNS). Quedó un único intercambio no financiero registrado, estado `blocked` y **cero solicitudes financieras**. No se reintentó ni se cambió la ruta para eludir esa limitación. En el seguimiento HTTP no se ejecutaron nuevas demos remotas: la evidencia adicional procede de fixtures locales.

Por tanto, esta versión no acredita rondas remotas completadas ni una resolución general de los 403. Endorphina, Peter & Sons y Playson tienen pruebas de contratos/parsers y el arranque HTTP de Endorphina, pero todavía no una secuencia integral remota o de capturas completas de inicialización a liquidación. La distribución Windows se compila en CI; la verificación local se realiza en Linux.

Hay cinco familias de adaptador y seis IDs de inventario: Hacksaw, Endorphina, Peter & Sons, Playson, Pragmatic y su alias Reel Kingdom. Los otros 29 inventarios se importan y consultan, pero su ejecución se rechaza por falta de adaptador nativo en esta versión. Endorphina usa el contrato JSON/WSS publicado en `endorphina_client.py`; no implementa el worker protobuf mencionado por el inventario. Peter & Sons y Playson requieren parámetros públicos revisados mediante `--settings`, porque las vinculaciones necesarias no están completas en los archivos publicados.

Los errores de un proveedor no provocan apuestas nuevas automáticas, ni sustituyen dueños. No hay recuperación automática de raíces inciertas. Las muestras retenidas y sus intercambios quedan disponibles para diagnóstico. La exclusión entre procesos exige que compartan la misma raíz `--data`; no coordina máquinas con almacenes independientes. El almacenamiento local es SQLite; las exportaciones se construyen como snapshots en memoria, por lo que conviene acotarlas con filtros cuando el dataset crezca.
