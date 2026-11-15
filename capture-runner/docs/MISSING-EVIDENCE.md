# Evidencia necesaria para ampliar la cobertura

La infraestructura ejecuta todos los proveedores con cupos independientes por salida. La cobertura de protocolos es otra medida: [COVERAGE.md](COVERAGE.md) indica qué modos tienen un flujo implementado. Esta revisión buscó archivos en todo el repositorio, incluidas las referencias archivadas, `demo-dashboard`, `game-runner` y `bet-collector`.

## RubyPlay

El runner dispone del decodificador de **African Cats (`rp_47`)**. La orquestación Python existe, pero importa componentes nativos que no se publicaron. Para recuperar el soporte genérico, hacen falta estos archivos del workspace anterior:

```text
provider-work/rubyplay-chat2/native_bundle.cjs
provider-work/rubyplay-chat2/native_choices.cjs
provider-work/rubyplay-chat2/native_contracts.json
provider-work/rubyplay-chat2/validate_next_init.cjs
provider-work/rubyplay-chat2/plan_next_normal.cjs
provider-work/rubyplay-chat2/results/rp_*-binding.json
provider-work/rubyplay-chat2/catalogs/official-links.json
```

También hacen falta las fuentes nativas y fixtures que esos bindings referencian: `private/live/<game>-preparation/game-js.body.private`, las inicializaciones y los pares request/response. El índice público enumera 178 bindings por juego ausentes. El archivo `rubyplay-rp47-source-index.json` contiene offsets para una versión exacta del cliente de African Cats; no contiene un decodificador universal.

Fuentes del diagnóstico: `standalone info/rubyplay/referencias/provider-work/rubyplay-chat2/batch_runner.py`, el índice de evidencia de RubyPlay y `game-runner/src/adapters/rubyplay_native.rs`. El ZIP entregado en este chat no contiene esos componentes.

Con la evidencia actual, configurar cuatro cupos de RubyPlay permite como máximo **un juego distinto por salida**. `plan` muestra esa diferencia entre cupos configurados y juegos ejecutables.

## Playtech

El repositorio conserva observaciones de menús, catálogos y hashes. El motor genérico y los perfiles ejecutables permanecieron fuera del checkout según sus propios `HANDOFF.md` y `CONTINUITY.md`.

Recuperar principalmente:

```text
provider-work/playtech-root/playtech_engine/
bet-collector/collection_full_playtech.py
bet-collector/playtech_family_replay.py
bet-collector/collection_families.py
playtech-private-root/ngm-families/profile-loader.cjs
playtech-private-root/ngm-families/profile-worker.cjs
playtech-private-root/ngm-families/profiles/registry.json
```

El paquete `playtech_engine/` incluye `protocol.py`, `runtime.py`, `direct_runtime.py`, `direct_transport.py`, `client_sources.py`, `command_bindings.py`, `source_selectors.py` y los continuadores de cada familia. Para los perfiles NGM también hacen falta sus adaptadores, manifiestos, fuentes y fixtures. Los bootstraps y wire logs históricos sirven como evidencia; el runner crea sesiones nuevas.

El resumen de 143 perfiles NGM no sustituye esos programas. Los UUID de menú GPAS tampoco especifican por sí solos las clases de comando y sus mensajes anidados. La entrega conserva el binding completo de Blitz10 y declara pendientes los demás.

## Otras familias

| Proveedor | Material que falta o límite concreto |
|---|---|
| Betsoft | `provider-work/mocks/betsoft/`, `betsoft-private/init-*.json`, `betsoft-private/results/`, `client-548.js`, `modern_audit.py` y las inicializaciones modernas. Se conserva el transporte de los tres juegos con binding completo. |
| IronDog | Mapeos de lanzamiento NYX y perfiles nativos para los demás juegos; `provider-work/mocks/irondog/capture/`, `build_bank.py`, `iron-dog-profile-mode-audit-20261104.json` y el catálogo/summary completo. El gateway genérico existe, pero sólo dos mapeos públicos son explícitos. |
| Kendoo | `provider-work/kendoo-chat4/catalog.json`, `live/games/`, `normalizer.py` y los colectores de la familia Node. El summary de acciones no incluye los códigos de lanzamiento nativos de todos los juegos. |
| Hardfire/Kalamba | `bet-collector/collection_claude_extra.py` y `claude-demo-catalog.json`, con los selectores y continuaciones por juego. El binding publicado contiene booleanos de cobertura histórica, no las apuestas nativas. |
| Microgaming | Los mismos colectores/catálogos anteriores, con `ProductID`, contexto de lanzamiento y comandos de compra. Los IDs module/client y `buy_declared` no especifican esos comandos. |
| BGaming | Se portaron legacy v2/v1, variantes, elecciones y las familias RPC/Cocos con fuentes suficientes. Quedan 21 modos de cinco juegos, detallados debajo. Los históricos `live/<game>.json` ausentes no son por sí solos un bloqueo cuando el protocolo puede reconstruirse desde los parsers entregados. |
| Habanero | Las dos compras no enlazadas conservan un motivo específico en `plan --details`. El protocolo adicional del traspaso sí se incorporó para elecciones y continuaciones conocidas. |
| Evoplay | Los 489 modos pendientes de 20 juegos tienen claves `native:<hash>` y etiquetas, sin el payload ejecutable. Faltan `demo-dashboard/evoplay`, `collection_full_playtech.py` y `playtech_family_replay.py`. |
| Spinomenal | Los 238 modos pendientes necesitan contratos para ramas observadas, tower, wheel o prerrequisitos. Faltan `spinomenal-private/client.py`, sus resultados y `collection_full_misc.py`; el presupuesto de prerrequisitos del plan no especifica la acción nativa. |
| NetEnt | Existen 32 helpers Python de transporte y contratos en `referencias/provider-work/netent-root/`. Faltan las fuentes y capturas de `netent-private-root/campaign/` y `collection_full_node.py` que permitirían reconstruir los 67 selectores pendientes de 39 juegos. Los bindings GECO/Horizon/RedTiger publicados ya están incorporados. |
| Mascot | Los 31 juegos pendientes no tienen entry binding. Faltan `collection_mascot.py`, `provider-work/mocks/mascot` y `provider-work/mascot-gaming`. |
| Pragmatic | Quedan 20 compras de tickets de scratchcards y dos `fsp-0`. El protocolo de `pur-*`/`bl-*` no describe esos comandos; falta `collection_full_existing.py` y sus contratos de entrada. |
| 1spin4win | Los 18 modos pendientes de siete juegos no tienen tabla de líneas/selector/continuación; faltan `provider-work/mocks/1spin4win`, `collection_full_misc.py` y las capturas correspondientes. |

Los archivos ausentes no se recuperan modificando `ready`, `campaign_eligible` ni las antiguas verificaciones financieras. Cuando se incorporen, se puede ampliar un conector sin cambiar el planificador, WireGuard o el formato de captura.

### Los 21 modos pendientes de BGaming

Veinte requieren estos archivos preparados, además de los clientes originales que sus hashes y rutas señalen:

```text
provider-work/bgaming-chat4/protocols/KeepersOfTheSecret7rst.rpc-extra-prepared.json
provider-work/bgaming-chat4/protocols/GrandPatron7rst.rpc-extra-prepared.json
provider-work/bgaming-chat4/protocols/ClashofGodsAnubisvsHades.rpc-extra-prepared.json
provider-work/bgaming-chat4/protocols/AztecsClawWildDice.rpc-extra-prepared.json
```

Son respectivamente 2, 5, 12 y 1 modos. Los preparados contienen `fresh_version_guard`, `fresh_source_pins` y `metadata_source_routes`. Sus fuentes originales se referencian bajo `bgaming-private-chat4/research/frontends/<GID>/`. El parser publicado `rpc_source_pins.py` exige esos contratos para seleccionar y verificar los clientes.

El modo normal de **PrincessOfSky** sólo conserva URL y resultado HTTP 404: falta un launcher/init/cliente que pruebe entrada y continuación. Se deja pendiente por ausencia de ese contrato, no por el fracaso histórico.

## Protocolos recuperados de las referencias

La nueva implementación sí utiliza material que el adaptador Rust anterior no exponía: NoLimit (141 juegos/1.147 modos), ELK (159/803), BGaming (215/787), las 18 modalidades adicionales de Play’n GO y los 301 selectores Yggdrasil del CSV junto con el protocolo del traspaso. La cifra vigente de cada proveedor se genera con el mismo registro que ejecuta las apuestas y se publica en [COVERAGE.md](COVERAGE.md).
