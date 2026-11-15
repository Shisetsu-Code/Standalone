# Game runner de demos

Runner Rust experimental para recolectar rondas de demos públicas con saldo ficticio y guardar cada intercambio. Importa los 35 inventarios publicados; la importación **no** implica que los 35 proveedores tengan adaptador o hayan sido probados con este runner. No usa las sesiones capturadas en HAR.

Desde `game-runner/`, con Rust 1.99 o posterior y Cargo:

```sh
cargo build --locked --release
cargo test --locked
```

El ejecutable es `target/release/game-runner` en Linux o `target\release\game-runner.exe` en Windows. Los ejemplos siguientes usan Linux. `--data` identifica la raíz privada y debe ser la misma para todos los procesos que comparten proveedores; usa SQLite con WAL, y contiene sesiones, solicitudes y respuestas. No incluir esta carpeta en Git ni compartirla. En Unix se limita a permisos privados. `import` elige el inventario del runner común, incluso si ese manifiesto ya está guardado. Los ejecutables individuales guardan su propio inventario junto a los recibos y mantienen la selección del runner común.

### Ejecutables individuales en Windows

Compila cada ejecutable para Windows x64 con la biblioteca de C de Visual C++ incorporada. Desde `game-runner/` en PowerShell:

```powershell
$env:RUSTFLAGS = '-C target-feature=+crt-static'
cargo build --locked --release --bin redtiger
```

El binario queda en `target\release\`. `dumpbin /dependents` permite verificar que el ejecutable final prescinde de `VCRUNTIME140.dll`.

Los ejecutables autónomos se conectan directamente a las demos públicas. Se pueden copiar individualmente a Windows x64 y necesitan acceso a Internet y permiso para escribir el historial local. El historial se crea al ejecutar la primera prueba.

Los binarios individuales de este directorio incluyen su inventario y los parámetros públicos revisados. `games` lista el inventario completo. `check JUEGO MODO` comprueba localmente si el ejecutable dispone de un adaptador y configuración para esa combinación. `run JUEGO MODO` ejecuta una muestra en la demo pública y guarda un historial privado en `%LOCALAPPDATA%\Evidencia\DemoRunners` o en la ubicación indicada con `--data`. Conserva esa ubicación para consultar los bloqueos y las rondas pendientes.

Play’n GO cerró y concilió una tirada normal de Wrappin’ More Gold (`playngo.exe run 1001 normal`). ELK cerró y concilió una tirada normal de Propaganda 2 (`elk.exe run propaganda-2 DEF`). Ambos ensayos se hicieron desde carpetas aisladas con el ejecutable copiado. Las modalidades que declara cada inventario requieren su propia validación.

El ejecutable de Play’n GO incorpora 458 slots revisados y sus 475 modos, con
el GID público y el hash del cliente por juego. `ci/build_playngo_bindings.py`
reconstruye esos datos desde inventarios y recibos conciliados. Se verificó el
plan de los 475 modos desde una carpeta aislada. En los ensayos en vivo,
cerraron y conciliaron 3 Blades and Blessings normal (`1058 normal`) y Wrappin’
More Gold Go Ultra (`1001 go-ultra`).

Playtech GPAS cerró y concilió una tirada de Flaming Stallion Blitz por HTTP y WSS directo desde una carpeta aislada (`playtech.exe run gpas:gpas_blitz10_pop d743f173-2233-463f-909d-a4e95f68a07a`). El runner verificó el balance en la notificación de la misma solicitud financiera. Este ejecutable admite la muestra representativa de GPAS.

Kendoo cerró y concilió una tirada representativa de 3 Power Drums por HTTP directo desde el ejecutable de entrega (`kendoo.exe run 3-power-drums normal`). Registró 10 FUN de coste, premio 0 y saldo final 99.990 FUN. Coin Dragon cerró una tirada en la compilación de depuración y devolvió HTTP 500 en `start` en las pruebas posteriores, antes de apostar. Las campañas de Kendoo siguen pausadas.

1spin4win cerró y concilió una tirada normal de 10 Lucky Spins (`onespin4win.exe run TenLuckySpins normal`) y otra de All Ways Egypt (`onespin4win.exe run AllwaysEgypt normal`) por WSS directo desde una carpeta aislada. El ejecutable incorpora 265 modalidades de 225 slots, incluidas 31 compras y 9 antebet. Cada combinación fija las líneas, el factor de coste y los selectores de entrada y continuación según su banco histórico. El recibo registra el hash SHA-256 del banco que respalda esa combinación. Se contrastaron 1.205 rondas históricas y se comprobó el plan de las 265 modalidades con el ejecutable autónomo. El worker cerró y concilió en vivo la normal, compra y antebet de Burning Spins 243 y Cash the Gold Hold & Win. La ejecución en vivo del resto sigue pendiente.

`status` lee los resultados del proveedor en el historial local e incluye la etapa, el código de respuesta y si cada solicitud podía modificar la ronda. No realiza solicitudes de red. Está disponible en las compilaciones nuevas.

EGT Digital incluye parámetros históricos para 331 modalidades: 236 normales, 64 compras y 31 variantes. El adaptador comprueba la oferta de la sesión actual antes de ejecutar el caso. Conserva la ronda si aparece una elección cuyo control aún requiere revisión. La prueba de ABSlot (`egt-digital.exe run ABSlot 0`) abrió una demo por WSS, completó las tiradas gratis y el cobro, y concilió 30 de coste y 180 de premio en unidades nativas.

La versión con control de identidad de ronda también cerró una compra de ARSlot (`egt-digital.exe run ARSlot 2`) y concilió 2.000 de coste y 5.569 de premio en unidades nativas.

El modo normal de BOSHHRSlot usa el payload del registro `egt-demo-round-closure.jsonl`, con factor 10, nivel 1, denominación 1 y 10 líneas. El worker abrió una nueva demo y cerró por WSS con coste 10, premio 5 y saldo final 4.999.995 en unidades nativas.

Evoplay ejecutó y concilió una tirada normal de Ace Round desde una carpeta aislada (`evoplay.exe run aceround normal`). El adaptador Fullstate conserva 591 modalidades de 238 slots, incluidas compras y antebet. Se contrastaron 587 modalidades contra sus archivos de inicialización guardados. La prueba en vivo corresponde a Ace Round normal.

Betsoft siguió la redirección de invitados a la plantilla pública, confirmó el modo `free` y cerró una tirada normal de At the Movies, Lucky 7 y Rook’s Revenge desde el binario individual (identificadores `266`, `2` y `277`). Las tres tiradas conciliaron. Los modos especiales quedan pendientes.

Ela Games incorpora 68 slots y 66 compras con evidencia histórica. El ejecutable abrió una sesión demo por HTTP y Socket.IO, y cerró y concilió una tirada normal y una compra de giros gratis de Soul Fiesta (`ela-games.exe run ela_soul_fiesta normal` y `ela-games.exe run ela_soul_fiesta freeSpin`). La compra registró un coste de 4.000 y un premio de 1.270 en unidades nativas. La selección interactiva admite el cobro cuando está ofrecido. La verificación en vivo de los demás juegos y modos queda pendiente.

Amusnet abre una sesión FUN por HTTP y conecta por WSS al servidor demo anunciado por el lanzador oficial. Integra 759 modalidades históricas de 466 slots, incluidas 271 compras, 19 antebet y 3 boosters. Fruity Time cerró y concilió una normal y una compra de giros gratis desde el ejecutable aislado (`amusnet.exe run 407 NONE` y `amusnet.exe run 407 BUY_FREESPINS`). El ejecutable admite los giros gratis, el cobro de gamble y Hold & Spin cuando el servidor ofrece esos estados. Las elecciones y continuaciones específicas de algunos juegos quedan pendientes.

NetEnt tiene 218 identificadores públicos en `bindings/netent-launch.json` (133 GECO, 61 Horizon y 24 de la familia HTTP de Red Tiger). El botón oficial envía `X-WP-Nonce` con el valor publicado en cada ficha. Con ese encabezado, Starburst y Aloha Christmas pasaron de HTTP 401 a 200, pero el emisor respondió `Unable to start game - invalid response from API`. `netent.exe probe-launch dead-or-alive-2` también llegó a HTTP 200 y registró `issuer_declined`. Si el emisor devuelve un enlace válido, el comando sigue exclusivamente las redirecciones oficiales de entrada y comprueba si el enlace al cliente incluye un identificador de saldo demo. Solo muestra rutas y estados. Ninguna de estas pruebas envió apuestas. El ejecutable de rondas sigue pendiente de un lanzamiento válido y de la integración de los protocolos de juego.

La ruta alternativa anunciada en la [documentación oficial de Playin](https://beta.netent.com/affiliates-info) usa un emisor distinto. `netent.exe probe-launch starburst --playin` usa el identificador `starburstr000000` de la ficha oficial. La consulta HTTP devolvió 200 para la página y el emisor, y 403 en `fansite.evo-games.com/entry`, antes de acceder al frontend. El comando informa estados y rutas sin imprimir tokens ni enviar solicitudes de juego.

En 216 de 218 capturas, `balance_id` y `table_id` del fragmento guardado por el cliente en `EvoLastAppUri` coincidieron con los parámetros `balanceId` y `tableId` del WebSocket de Horizon. En las otras dos no se encontró un WebSocket que coincidiera. El fragmento pertenece al cliente y no se envía como parte de la petición HTTP. El diagnóstico registra si lo observó en una redirección fresca, sin reutilizar los identificadores históricos.

`netent.exe audit-geco INICIO FINAL MONEDA` calcula la apuesta normal de un par de respuestas GECO guardadas y contrasta el premio nativo con el saldo. `python ci/audit_netent_geco.py EJECUTABLE CARPETA_DE_CAMPAÑA` vincula cada solicitud con su sesión demo guardada, cuenta respuestas históricas de error por separado y coteja los parámetros enviados y los importes. Coincidieron los 122 recibos de un solo paso, incluidos 23 con premio. `--bindings-output ARCHIVO` genera solo los identificadores públicos de las mesas y juegos que además coinciden con el arranque guardado. Mirror Mirror usa el selector `243` y Narcos `0-0`, según el código y las capturas. Butterfly Staxx 2 usa las 25 monedas que indica la configuración original, verificada contra su SHA-256.

El adaptador GECO ejecuta `Spin` por HTTP para esos juegos. Abre una demo nueva desde la ficha oficial, contrasta la mesa y el juego nativo, y guarda cada solicitud, respuesta y continuación con el dueño de la sesión en el diario privado. Apuesta el mínimo que publica GECO y concilia con el premio y saldo nativos al cerrar. `ci/audit_netent_geco_modes.py` genera los selectores de compra y variantes cuyos pasos, importes y rutas de cliente coinciden con las capturas. Antes de apostar en esos modos, el runner verifica el SHA-256 del cliente público y aplica el factor de coste y las continuaciones de la modalidad. Una consulta reciente de Butterfly Staxx 2 devolvió HTTP 200 e `issuer_declined` antes de las solicitudes financieras. Un plan válido solo acredita que el código y los selectores están disponibles localmente.

`ci/audit_netent_horizon.py` vincula el lanzamiento y las capturas WebSocket por mesa, correlaciona las respuestas con `replyTo` y verifica el débito y saldo final del mismo wallet. Con `--contracts` incorpora los selectores propios de Horizon v1 que coinciden con el código del cliente y el recibo histórico. Antes de apostar en v1, el runner comprueba la versión del juego, la integridad anunciada en el frontend, el SHA-256 descargado y, donde se publica, el factor de coste nativo. Horizon usa el mínimo de `AppInfo` y mantiene el mismo `gameRoundId` durante las continuaciones. La conciliación conserva el premio textual del proveedor y acepta diferencias de serialización menores a `10⁻²⁴` solo con moneda de dos decimales y saldo final exacto. Si aparece una decisión pendiente de integrar, detiene la ronda y conserva su diario.

En Jungle Spirit Megaways, las compras conservan la selección exacta de animal y verifican que el servidor confirme ese animal antes de enviar la elección de cobrar o arriesgar. Para NetEnt, un HTTP 200 con `success: false` en el emisor se informa como `demo_issuer_declined`, con el estado HTTP y la fase en el evento público. El JSON original queda en el registro privado.

Las cuatro compras de Finn and the Candy Spin requieren un presupuesto explícito de preparación. Por ejemplo, `netent.exe check finn-and-the-candy-spin FeatureBuy:select=symboltransform --max-prerequisite-rounds 16` verifica la configuración local. El runner comprueba los umbrales publicados, conserva la sesión y guarda el recibo de cada compra de preparación antes de enviar otra. Si el objetivo sigue bloqueado al agotar el presupuesto, o una preparación se cierra sin sumar llaves, detiene esa muestra. El recibo de la compra solicitada conserva su propio coste, premio y saldo, junto con las referencias de las preparaciones.

ThunderSpin incorpora 60 modalidades normales y 24 compras, contrastadas con sus recibos históricos. El ejecutable aislado abrió una demo por HTTP, verificó la revisión del cliente y concilió una normal de Indian Call (`thunderspin.exe run 62 NORMAL`) y una compra de Illuminati Party (`thunderspin.exe run 60 BUY_BONUS`). Las compras con nombre, las elecciones y gamble requieren controles adicionales.

Amigo Gaming obtiene una sesión nueva por el lanzador público, mantiene sus cookies HTTP y verifica el cliente y el estado inicial por WSS. Desde una carpeta aislada se conciliaron la normal (`amigogaming.exe run 200 NORMAL`) y la compra de giros gratis de Lucky Mariachi (`amigogaming.exe run 200 BUY_FREE_GAME`). La compra costó 26,00 EUR ficticios, pagó 10,30 y cerró con 984,30 desde 1.000,00. Se validan precio y saldo antes de enviar la compra. Las elecciones se limitan a los controles demostrados por el cliente y los demás títulos requieren verificación del binario en vivo.

RubyPlay admite la tirada normal de African Cats desde una carpeta aislada (`rubyplay.exe run rp_47 normal`). Compila con `cargo build --locked --release --features rubyplay-native --bin rubyplay` y las opciones de Windows anteriores. Descarga el cliente público, exige el SHA-256 revisado y ejecuta la extracción de matemáticas en un intérprete incorporado al binario, sin acceso a red ni archivos desde JavaScript. La prueba histórica y las pruebas en vivo confirmaron el coste mínimo de 20 unidades nativas. La compilación de entrega cerró con premio 15 y saldo 999.995 desde 1.000.000. El selector de compras y otros juegos quedan fuera de esta prueba representativa. `probe-launch rp_47` comprueba únicamente el inicio.

Spinomenal tiene un ejecutable experimental para el protocolo `StartSlotMachine`, con 1.230 modalidades de 536 slots extraídas de recibos conciliados. Incluye 534 normales, 4 antebet y 692 compras. Lee la oferta y el precio de la demo, separa el débito inicial de las continuaciones y contrasta premios nativos con cada cambio de saldo. La prueba del binario en 81 Frozen Fruits recibió HTTP 403 en `InitClientUrl` en dos sesiones HTTP nuevas y conservó el rechazo sin enviar apuestas. Se contrastaron cuatro secuencias históricas, incluida una compra con 12 acciones. Las ramas que requieren un selector, un cobro interactivo o protocolos Tower y Table siguen fuera del adaptador. Cuando la demo omite el código de moneda, el saldo se representa como `DEMO_COINS` en unidades nativas.

Peter & Sons cerró y concilió una normal y una compra de giros gratis de Abrakadabra desde el ejecutable aislado (`peterandsons.exe run abrakadabra main` y `peterandsons.exe run abrakadabra buy_FS`). La compra registró 16,00 de coste y 28,61 de premio sobre 10.000,00 EUR ficticios. El rechazo 400 `TRANSACTION_REJECTED` de Royal Hunt se conserva con su sesión y sigue pendiente. El cuerpo enviado a `/game/complete` coincide con el contrato del cliente oficial y con el formato de cierres históricos aceptados; la causa del rechazo sigue sin establecerse.

Mascot incluye 117 tiradas normales, 56 compras y 7 antebet con parámetros ligados a la evidencia de 117 slots. El ejecutable sigue el enlace oficial, conserva la sesión HTTP y comprueba que el servidor confirme la demo, el precio y el cierre. En Evil Bet: Cursed Spin cerraron la normal y `buy_0` desde una carpeta aislada. La compra costó 10.000 unidades ficticias, pagó 9.205 y dejó 999.205 de 1.000.000. Las compras sin precio confirmado antes del envío y los juegos de mesa quedan fuera del ejecutable. La verificación en vivo del resto de los slots y modos sigue pendiente.

Habanero incluye 263 modalidades con parámetros históricos de 160 juegos (160 normales, 53 Super Bet y 50 compras). El ejecutable abrió sesiones demo nuevas por HTTP y concilió cuatro rondas desde una carpeta aislada: normal, Super Bet y compra de Legend of Nezha, y normal de 12 Zodiacs por el formato `game.play`. La compra de Nezha costó 8,88, pagó 32,10 y cerró en 2.023,22 créditos ficticios. El runner usa el mínimo ofrecido y compara el saldo con el coste documentado y el premio nativo. Las elecciones y otros estados interactivos pendientes requieren controles adicionales. El resto del inventario no se recorrió en vivo con este binario.

Games Global abrió demos anónimas por HTTP directo y concilió las normales de Gold Blitz Extreme (`gamesglobal.exe run GoldBlitzExtreme normal`) y 12 Masks of Fire Drums (`gamesglobal.exe run 12MasksofFireDrums normal`). El binario valida los saltos oficiales y los identificadores de módulo, cliente y producto; lee la oferta mínima nativa, verifica que el turno vuelva a la etapa base y contrasta los dos saldos del proveedor con los importes de la transacción. Las dos pruebas costaron 20 unidades nativas (0,20 de la unidad demo). En 12 Masks el premio también fue 20. La lista completa del catálogo está incorporada para consulta. Por ahora solo esos dos modos son ejecutables. Las compras y continuaciones pendientes mantienen su estado previo.

Iron Dog tiene un adaptador experimental para el lanzador Morphic público de 3 Apex Treasures y 3 Gods of Goalympus. El gateway rechazaba el `User-Agent` del ejecutable durante `init`. Con el valor documentado, la prueba de 3 Apex Treasures pasó por `init` (201), `setup` (200) y `spin` (200). La ronda devolvió `settled: true`, coste nativo 0,10 FUN y `bet.balance: null`. El adaptador compara el selector, la apuesta base y el coste devuelto por el servidor con la oferta inicial. Usa `bet.buyInCost` para compras y `bet.totalStake` para normal y antebet.

El código oficial de Apex (SHA-256 `6e805667f536cf527efe5b17a669fc79f6c83c4258500aea245f7eae1960b057`) lleva el saldo visible localmente y solo lo sustituye cuando el servidor envía un valor. También registra el destino cifrado `duck/balance`. El módulo compartido ClientAPI (SHA-256 `2015b4e5aa9467a66763a085aeb034dae5b5c7bc9ff6313851cc5acc930772d3`) elige entre ese control y `POST getBalance.jsp` según la configuración de su wrapper. Ambos reciben el objeto del llamador. Cinco HAR adicionales de Iron Dog no contienen una solicitud de saldo. En 351 archivos de cierre decodificados, 342 valores de `bet.balance` eran nulos o ausentes. Los nueve valores de texto de la familia Legacy estaban vacíos. La auditoría histórica documenta 69 raíces cerradas, todas sin saldo independiente. La ronda original queda retenida y el binario sigue fuera de la entrega validada.

El lanzador de la ronda guardada declara el wrapper NYX. Su código (SHA-256 `d83002bd466da77c3b3722b134528450370cff5473cc41be31d679aa868bcf32`) omite la consulta remota de saldo cuando `playingForFun` está activo. El método que llama a `duck/balance` pertenece a otro wrapper. `irondog.exe --data CARPETA audit-iron-dog ID_DE_RONDA` audita la ronda normal desde el historial local, verifica hashes, rotación de claves y dueño demo, y muestra saldo inicial, coste, premio y cierre. La ronda original de 3 Apex Treasures confirmó 5.000 FUN iniciales, coste 0,10 FUN, premio 0 y cierre nativo, con saldo final nulo. La auditoría devuelve código 2 cuando falta la conciliación y no altera el estado de la ronda.

Para las rondas Morphic retenidas por falta de saldo final, `show` y `export --include-unverified` del runner común incluyen `native_receipt` cuando se pueden volver a verificar las solicitudes guardadas. `status` y `run` del ejecutable por proveedor usan el mismo recibo. La auditoría reconoce la tirada normal, la compra y el antebet de los juegos admitidos y comprueba cuándo corresponde enviar cada selector. El saldo final y la conciliación quedan en `null` cuando el proveedor los omite.

La revisión del cliente Legacy de Western (`8a1d912a35bba696bd10ac88cea83be1e6c05a5ece63f169ca6eac1da634ee6c`) permite descartar ese otro lanzador como fuente de saldo de cierre demo. Su consulta `getBalance.jsp` antes de apostar exige `balanceBeforeSpin=true` y `fun_real=real`. El cliente distingue `bet.addBalance` (importe incremental) de `bet.balance` (saldo nuevo). En 465 paquetes decodificados del archivo privado de auditoría, 425 tenían `addBalance`, con 29 valores distintos de cero. Ningún `bet.balance` contenía un importe. La ronda demo guardada de Western cerró con `bet.balance=null`.

KA Gaming validó `BonusMania/normal` localmente. Con el enlace directo al juego, el ejecutable alcanzó `startGame`, que respondió HTTP 403 con un desafío declarado. Red Tiger tiene cuatro rondas HTTP anteriores conciliadas y el binario autónomo recibió HTTP 403 en `/entry` tras un 200 del emisor de sesión. Ambas pruebas se detuvieron antes de enviar apuestas.

Los tres arranques HTTP exitosos de Red Tiger (No Brainer, Revolvero y Cash Volt) siguieron dos redirecciones 302 de `/entry`, luego obtuvieron 200 en el documento de juego, `setup`, `config` y `settings`. La auditoría de las cuatro rondas comprobó identidad de sesión, débito, premio y saldo. El adaptador exige que el saldo inicial venga de `settings` y que coincida con el inicio de la tirada. Los registros exitosos de la entrada conservan estados y rutas. En la prueba nueva de Aztec Tribute `101:Random`, tanto el arranque inicial como la renovación de sesión obtuvieron 200 del emisor y 403 en `/entry`. El historial confirmó cero solicitudes financieras en ambos intentos.

Red Tiger cotiza compras, antebet y cambios de modo a partir de `settings.result.game.mathModes`. El ID y el tipo deben coincidir con el inventario y el proveedor debe ofrecer un único precio positivo. El ejecutable usa la apuesta base mínima de la sesión, verifica saldo suficiente para el coste total y contrasta la apuesta y el débito devueltos con la cotización. Aztec Tribute expone `101:WildMultiplier`, `101:WaysMultiplier` y `101:Random`. El runner exige que la demo anuncie la opción elegida y confirma el resultado en la misma ronda. En seis capturas históricas, `/finish` confirmó el cierre con un acuse que repite ronda, sesión y posición neta. En ese caso se conserva el último saldo conciliado de la fase de juego. Los selectores sin contrato revisado quedan retenidos. La comparación histórica identificó 80 compras y 10 antebet con ofertas coincidentes en 32 slots. Las capturas y pruebas locales todavía requieren una validación en vivo del binario.

Microgaming corrigió el HTTP 406 del inicio de práctica enviando `Accept-Encoding: identity`. El binario lee la moneda en `account.core.currencyIsoCode` y reconstruye la apuesta mínima desde la combinación publicada de moneda, multiplicador y monedas por línea; conserva el contrato anterior cuando el proveedor devuelve una apuesta escalar. `microgaming.exe run 3rd-base normal` cerró por HTTP directo desde una carpeta aislada. Coste 0,50 USD ficticios, premio 0,02, saldo final 999,52 desde 1.000,00. Otros juegos y compras siguen pendientes en el binario.

## Uso

```sh
# Importar el índice publicado y fijar su hash semántico
./target/release/game-runner --data data import

# Consultar IDs exactos y modalidades; ver cobertura declarada
./target/release/game-runner --data data inventory --provider hacksaw
./target/release/game-runner --data data inventory --provider hacksaw --game 2405
./target/release/game-runner --data data capabilities

# Crear una campaña finita sin sobrescribir el archivo existente
./target/release/game-runner --data data plan --provider hacksaw --game 2405 --mode normal --samples 1 --output campaign.json
./target/release/game-runner --data data check --plan campaign.json
./target/release/game-runner --data data run --plan campaign.json

# Estado, muestra pública y exportación
./target/release/game-runner --data data status
./target/release/game-runner --data data show ROUND_ID
./target/release/game-runner --data data export --output exportacion
```

Sustituya `2405` y `normal` por identificadores exactos publicados en el inventario si desea otro juego o modalidad. `--mode` puede repetirse; `--samples` fija la cantidad por modalidad. El plan se valida antes de escribirlo, fija el inventario actual y recibe un UUID de campaña (o uno explícito mediante `--id`). `check` valida sin conectarse. Para una configuración pública específica, `plan` acepta `--settings settings.json`; no incluya credenciales ni sesiones. El resolver automático de Endorphina necesita `--repo ..` (valor predeterminado) y su catálogo público original fijado por hash. Hacksaw, Pragmatic y Reel Kingdom no requieren ajustes de lanzamiento en el plan. Peter & Sons carga el wallet público, la moneda y las modalidades conciliadas desde bindings/peterandsons.json. Playson requiere configuración revisada explícita.

`run` permite `--parallel-providers 4`, `--timeout-seconds 45`, `--max-steps 3000` y `--relay URL` para un proxy local compatible. Los proveedores distintos pueden operar en paralelo; Pragmatic y Reel Kingdom comparten el mismo lock. La ejecución emite eventos tras persistir cada estado, y termina con código 2 si la campaña quedó incompleta. Ctrl-C impide iniciar nuevas muestras y deja terminar las rondas en curso.

Una solicitud financiera queda registrada antes de enviarse. Si se pierde la respuesta o no se conoce el cierre, la ronda queda pendiente o incierta: no se reenvía automáticamente ni se sustituye el dueño de sesión. `status` muestra pendientes y bloqueos. `release-hold --provider ID --reason TEXTO` registra un desbloqueo manual de proveedor, siempre que no exista una ronda pendiente; no resuelve ni elimina rondas. Los bloqueos no caducan automáticamente.

Una discrepancia de liquidación también bloquea al proveedor hasta revisión. Relanzar el mismo plan conserva las muestras existentes: omite las verificadas y se detiene ante cualquier muestra fallida; no la reemplaza ni salta a la siguiente. Para otra campaña, cree un ID nuevo después de revisar la causa. No se implementa recuperación automática de rondas inciertas: su dueño e intercambios quedan disponibles para diagnóstico.

El ejemplo [campaign-multiple-providers.json](examples/campaign-multiple-providers.json) usa IDs y modalidades del inventario fijado. Cambie el ID de campaña antes de usarlo, compruebe su `inventory_id` con `import` y ejecute `check`. Sus trabajos Hacksaw son secuenciales; los de Pragmatic pueden ejecutarse en paralelo. También puede ejecutar planes distintos en procesos distintos que compartan `--data`: el bloqueo por proveedor se mantiene.

## Cobertura y límites

### Recorrer todos los modos

`plan-all` enumera cada modalidad del inventario seleccionado: normal, compra, ante, booster, variante y especial. Programa un trabajo finito por identidad canónica; Pragmatic y Reel Kingdom conservan sus filas de cobertura, pero una modalidad compartida se ejecuta una sola vez. Los juegos sin modalidades, las pausas, los contratos ausentes y los prerrequisitos sin presupuesto quedan como omisiones explícitas.

Desde `game-runner/`:

```sh
export EVIDENCIA_RUNNER_DATA="$PWD/data"
./target/release/game-runner import

# Todos los modos de un juego, una ronda completa por modo
./target/release/game-runner plan-all --provider hacksaw --game 2405 \
  --samples 1 --id hacksaw-todos-001 --output todos.json
./target/release/game-runner check --plan todos.json
./target/release/game-runner run --plan todos.json
./target/release/game-runner coverage --plan todos.json

# Todo el inventario y contratos adicionales de la suite instalada
./target/release/game-runner plan-all --suite-root .. --python python3 \
  --max-prerequisite-rounds 20 --id suite-todos-001 --output suite-todos.json
```

`--provider` y `--game` pueden repetirse; omitirlos selecciona el inventario completo. El segundo ejemplo prepara el plan: se ejecuta después con `run --plan suite-todos.json`. Una ronda incluye sus continuaciones, elecciones y cobro final. El presupuesto de prerrequisitos es por muestra, entre 0 y 100; el valor predeterminado 0 deja pendientes los modos condicionales. Si el control solicitado no aparece dentro del presupuesto, queda sin completar y conserva las preparaciones pagadas con sus recibos.

Los modos condicionales de Betsoft usan la evidencia auditada de cada opción y verifican una inicialización nueva en EUR, `free`, con el juego esperado y la denominación mínima en el índice que usa el protocolo. El recibo de doblar o elegir carta comienza con el saldo de la oferta. Las tiradas que produjeron esa oferta quedan en recibos de preparación, con su propia conciliación.

`coverage` acepta `--plan ARCHIVO` o `--campaign ID` y separa `runnable_completed` de `all_inventory_modes_completed`. La cobertura completa exige todas las muestras verificadas, ninguna modalidad omitida y ningún juego sin contrato. El plan incluye los motivos en `coverage.omitted_modes`, `coverage.omitted_games` y `coverage.omitted_providers`. La partición se comprueba contra el inventario fijado antes de ejecutar: recortar los trabajos o editar el indicador de cobertura no permite certificar un subconjunto. Un plan sin trabajos puede guardarse para inspeccionar sus omisiones; `check` y `run` rechazan ejecutarlo.

El adaptador nativo tiene prioridad. `--suite-root` permite usar los contratos del recolector Python para los modos restantes. Requiere una instalación completa de esa suite, Python con sus dependencias, los módulos nativos correspondientes y su relay local en `127.0.0.1:8793`. La comprobación de contratos no envía solicitudes a proveedores; comprueba archivos, dependencias y disponibilidad del relay local. No instala módulos ni crea sesiones durante la planificación. `--settings` permite un JSON de configuración pública con la estructura `{ "proveedor": { "*": { ... }, "id-juego": { ... } } }`; el juego prevalece sobre `*`. La moneda y unidad deben venir del contrato nativo o de una configuración pública revisada.

Si `spinomenal-private/` está fuera del checkout que contiene el runner, configure `EVIDENCIA_NATIVE_CASE_ROOT` con la ruta absoluta al directorio que lo contiene. Mantenga ese valor al generar, comprobar y ejecutar el plan. El catálogo y el cliente de Spinomenal se leen de esa ruta. Cada ejecución conserva sus datos en su propia carpeta de intento. En slots y Tower, el cliente comprueba `DemoMode` y que la ronda anterior esté cerrada antes de seleccionar la denominación mínima del modo. El recibo conserva el código de moneda de la inicialización. Si el código viene vacío, registra `DEMO_COINS` en unidades nativas, igual que el adaptador Rust.

El bridge conserva los journals originales, el dueño, los recibos monetarios independientes y el resultado del proceso en `data/suite-attempts/`. Un código de proceso 0 se etiqueta como proceso y no como HTTP 200. Los timeouts terminan el grupo de procesos en Unix; en Windows el worker usa un Job Object para conservar la propiedad de sus descendientes. La incertidumbre financiera bloquea al proveedor y no provoca otro envío.

Para usar el recolector Python y Rust en la misma máquina, ambos deben recibir el mismo `EVIDENCIA_RUNNER_DATA`. Rust acepta además `--data`, que prevalece sobre la variable; usar una raíz distinta rompe esa coordinación. Los locks son canónicos y los intentos pendientes se comparten: Python consulta las retenciones de Rust, y Rust respeta los marcadores pendientes del collector. Los intervalos mínimos de los proveedores se conservan también al elegir el adaptador nativo. En PowerShell puede fijarse la variable con `$env:EVIDENCIA_RUNNER_DATA = Join-Path (Get-Location).Path 'data'` y utilizar `--python python`.

La API existente del collector conserva `targets`; también acepta `all_modes: true` y `rounds_per_mode: 1` para recorrer las modalidades de los proveedores seleccionados, incluyendo `special`. El resumen termina como `partial` si queda alguna omisión. La carga del catálogo identifica entradas cuyos archivos o dependencias faltan, sin sustituirlas por resultados históricos.

La configuración automática de Peter & Sons cubre 70 slots y 223 modalidades conciliadas que coinciden con el inventario publicado. El archivo de bindings cruza el catálogo oficial, el auditor final y el HTTP de autenticación de las demos. Cada ficha conserva los hashes de esas autenticaciones y únicamente los campos públicos necesarios para abrir una sesión nueva. Cinco juegos con rondas retenidas quedan fuera de la configuración automática.

### Prueba puntual de todos los proveedores

`smoke-all --campaign ID --output informe.json` genera una fila por cada proveedor del inventario fijado, sin iniciar solicitudes. Añadir `--execute` autoriza una muestra normal por proveedor con adaptador, binding y objetivo revisados. No sustituye juegos ni repite rondas fallidas; usa los mismos locks, almacenamiento y validación nativa que `run`. Un informe puede reconstruirse después con el mismo ID y una ruta de salida nueva, omitiendo `--execute`.

El comando devuelve código 2 si se solicitó ejecución y no se verificaron todas las selecciones ejecutables. `--require-all-providers` exige además los 35 IDs. El informe conserva ambos indicadores; los estados sin adaptador, sin binding, pausado o no elegible no cuentan como éxitos remotos. El [workflow de prueba puntual](ci/README.md) exige las selecciones ejecutables y conserva el informe de los 35 proveedores junto con diarios privados cifrados en artefactos separados.

Hay adaptadores experimentales para cinco familias y seis IDs de inventario: Hacksaw, Endorphina, Peter & Sons, Pragmatic/Reel Kingdom y Playson. `capabilities` y la validación de cada plan indican qué variantes están implementadas; dependen de identificadores, ofertas y estado demo comprobados en una sesión nueva. Los modos de compra, ante, booster, variante y especial son distintos y solo se ejecutan cuando el adaptador dispone del contrato correspondiente. Los modos que dependen de otra ronda no son inicios independientes. Kendoo permanece pausado. La implementación y sus pruebas locales no son prueba de que una campaña remota haya cerrado correctamente.

## Sesión HTTP y respuestas 403

Para partir de los juegos completos que publica el dashboard, use `bet-collector/dashboard_execution_inventory.py` con `docs/dashboard-recoleccion/datos` y una ruta de salida. Con `--worker-inventory docs/recolector/inventario.json --manifest-dir DIRECTORIO_NUEVO` también genera un manifiesto importable. El exportador conserva el selector nativo, normaliza las operaciones a `bet`, `ante_bet`, `buy_bonus`, `booster`, `variant` y `special`, y comprueba que cada juego y modalidad coincida con el inventario con hash.

Para GPAS en una copia que no contiene el ejecutor local de Playtech, defina `EVIDENCIA_PLAYTECH_ROOT` con la ruta absoluta de la suite activa antes de planificar y ejecutar. La ruta se usa sólo para el catálogo y los archivos del ejecutor de Playtech. El worker conserva cada nuevo recibo en su propio directorio, y los resultados NGM calculados localmente quedan fuera del contrato de liquidación remota.

Importe el manifiesto filtrado con `game-runner import --manifest DIRECTORIO_NUEVO/manifest.json`. Después use `plan-all --output PLAN.json` para ver qué modalidades puede ejecutar el worker y qué falta. El plan agrupa el trabajo por proveedor, conserva las ramas de cada juego y registra los alias y las omisiones. Solo `run --plan PLAN.json` envía solicitudes de juego. Cada resultado incluye la operación normalizada y su selector nativo. Si una ronda falla, el evento de salida identifica la etapa, el estado HTTP disponible y si hubo un envío financiero. `show ID --private --output ARCHIVO.json` guarda los endpoints y payloads reales de cada paso en un archivo privado junto al recibo.

Los binarios autónomos de Playson y Belatra ya tienen rondas demo conciliadas pese a los 403 registrados en recorridos anteriores. El historial aislado conserva una ronda verificada de Playson y tres de Belatra. El ejecutable de Playson pasó la comprobación local de 206 modalidades, incluidas 201 incorporadas por cotejo de las solicitudes XML, la configuración pública y los recibos históricos. Cada modalidad añadida queda ligada a su selector exacto. Si cambia el JavaScript público, la ejecución se detiene antes de abrir sesión. Red Tiger recibió 403 en `/entry` después de que su emisor respondiera 200. Spinomenal volvió a recibir 403 de `awselb/2.0` en `InitClientUrl` con los valores de `Accept`, `Accept-Language` y `Content-Type` observados en el cliente. Se comprobó que el runner los envió y que hubo cero solicitudes de juego.

Una comprobación posterior de Red Tiger usó el enlace principal `entry` emitido para No Brainer y obtuvo la misma secuencia 200 en ficha, 200 en emisor y 403 en entrada. Para Spinomenal, el documento público `generic-play.html` devolvió 200 sin emitir cookies. La solicitud previa `OPTIONS /api/InitClientUrl`, con el origen oficial y sin cuerpo, devolvió 403 de `awselb/2.0`; las capturas exitosas registraban 204. Ese rechazo ocurre antes de que el servidor lea un cuerpo de inicialización. Ambas comprobaciones enviaron cero solicitudes de juego.

### Ejecutables pendientes de validación en vivo

`kagaming.exe`, `netent.exe`, `redtiger.exe` y `spinomenal.exe` están en `Escritorio/Runners autónomos Rust - pendientes`. Los cuatro arrancaron en Windows x64, leyeron el inventario incorporado y solo importan bibliotecas del sistema. `check` verificó localmente la selección de la normal de Bonus Mania, No Brainer y Gangsters Gold. NetEnt ofrece `probe-launch` para diagnosticar el arranque y `audit-geco` para auditar respuestas guardadas. Los cuatro quedan fuera del recuento de 30 proveedores con muestra autónoma conciliada en vivo. Iron Dog está en `Escritorio/Runner Iron Dog - saldo pendiente` y conserva el cierre nativo con saldo final ausente.

La [ficha de Revolvero en Evolution](https://games.evolution.com/slots/revolvero/) también anuncia una demo de Red Tiger. La comprobación directa desde esta PC recibió 403 en la propia ficha, antes de consultar su emisor. El runner ya comprueba el mismo usuario demo en `settings`, `spin`, `choice` y `finish`. Un acuse que corresponde a otro usuario no se acepta aunque coincidan la ronda y los importes.

Una comparación directa de No Brainer el 14 de noviembre confirmó que el acceso difiere entre clientes HTTP. El recolector Python con `requests`, sesión nueva y sin proxy siguió dos respuestas 302 en `/entry` y llegó a `settings` con HTTP 200 y usuario demo confirmado. El binario Rust recibió 403 en el primer `/entry` antes y después de alinearle los encabezados observados del emisor y de la entrada. Se actualizó también la versión con la que Rust pide `setup` y `config`, y el origen de `settings` pasó a ser el host nativo anunciado por el proveedor. La prueba Rust no alcanzó esos tres pasos. Las comprobaciones enviaron cero solicitudes financieras. La causa exacta de la diferencia de acceso sigue sin comprobarse.

El recolector local de Red Tiger usa ahora ese arranque HTTP directo con una
sesión nueva y parámetros públicos incorporados. Una comprobación de No Brainer
obtuvo 302 en ambos saltos de `/entry` y 200 en el frontend, `setup`, `config`
y `settings`, con identidad demo confirmada. La prueba terminó en `settings`.
El runner común selecciona el recolector HTTP directo de Red Tiger si el
directorio indicado en `--suite-root` contiene `bet-collector/collection_redtiger_http.py`.
Desde este checkout local, use `plan-all --suite-root .. --provider redtiger`
con el inventario y el resto de los parámetros habituales. Este transporte
utiliza el diario del worker y el bloqueo por proveedor del runner común.
El ejecutable autónomo de Red Tiger para Windows también puede incorporar
el transporte HTTP directo. Para reproducir esa compilación, ejecute
`python game-runner/ci/pack_redtiger_http.py RUTA_NUEVA.gz`, indique la ruta
absoluta del archivo en `REDTIGER_HTTP_BUNDLE` y compile con
`cargo build --locked --bin redtiger --features redtiger-bundled-http`.
El binario resultante incluye el runtime y conserva el diario Rust, sus
controles y el bloqueo por proveedor. Al ejecutar, no necesita instalar Python.

El cliente HTTP de Windows (`System.Net.Http`) con los encabezados de la misma captura también recibió 200 del emisor y 403 en el primer `/entry`. La comparación aún admite diferencias en la serialización y en el transporte. Se conserva el ejecutable anterior del Escritorio hasta confirmar una mejora en vivo.

La comparación con los intercambios archivados confirmó que Rust preserva el path y la cadena de consulta de `entryEmbedded`. Python alcanzó `settings` tanto con `Accept-Encoding: identity` como con el JSON compacto del emisor. Al omitir `Connection: keep-alive` únicamente en `/entry`, Python obtuvo 403 y al restaurarlo volvió a `settings` 200. Agregar ese encabezado a Rust dejó el mismo 403 en el primer `/entry`, con cero solicitudes financieras. El ajuste se descartó.

[Gangsters Gold](https://spinomenal.com/portfolio/gangsters-gold/) publica una ruta demo alternativa. El enlace del proveedor devolvió `301` en `games.spinomenal.com/Play/Fun`, `301` en `api-ld.spinomenal.com/gamelauncher/demo` y `200` en el documento del CDN. El destino anunciado para el inicio fue `rgs-ld-demo-core.spinomenal.com/api/InitClientUrl` con modo ficticio. Ese segundo host también devolvió `403` de `awselb/2.0` ante la solicitud previa `OPTIONS`. La comprobación terminó sin abrir una sesión ni enviar una jugada.

En Spinomenal, 1.566 historiales registran el uso de una configuración pública guardada para abrir sesiones nuevas directamente con `StartSlotMachine`. Las capturas de 81 Frozen Fruits muestran que ese paso devolvía HTTP 200 y confirmaba `DemoMode=1` e `IsLastRoundFinished=true`. Una comprobación única con un identificador demo nuevo y la misma ruta devolvió HTTP 403 de `awselb/2.0` en `StartSlotMachine`, con cero solicitudes financieras. Incorporar esa configuración al ejecutable no resolvería por sí solo el acceso actual.

La compilación Windows con `--features spinomenal-bundled-http` usa el runtime
HTTP incorporado y 536 configuraciones públicas revisadas. Abre una sesión
ficticia nueva en `StartSlotMachine`. En 81 Frozen Fruits, el arranque y
la normal devolvieron HTTP 200 y el saldo concilió. El recibo del antebet
también registró el cierre y permitió corregir el cálculo del coste: el
proveedor publica `SpecialBetMultiplier` como multiplicador directo. El
intento anterior permanece guardado junto con su auditoría posterior.

KA Gaming ahora abre directamente el cliente demo de Bonus Mania con los parámetros de lanzamiento que publica su ficha y usa el mismo identificador de invitado en `startGame`. La identidad se verifica con el inventario incorporado, los hashes del juego y del motor públicos y los datos que devuelve `startGame`. La consulta de catálogo queda fuera de la ruta de ejecución de este juego. En la prueba con la URL oficial completa, el launcher, el juego y el motor devolvieron HTTP 200 sin emitir cookies. `startGame` devolvió HTTP 403 con `cf-mitigated: challenge`, antes de cualquier apuesta. La sesión histórica que obtuvo 200 se abrió mediante el cliente en navegador.

La auditoría de 190 inicializaciones guardadas de KA Gaming encontró 188 respuestas HTTP 200 con modo demo, sesión emitida, juego correcto y moneda USD. Las otras dos carecen de respuesta HTTP. En las 188 respuestas válidas, el usuario canónico emitido difiere del invitado de la solicitud. Una comprobación `OPTIONS /kaga/rmp/startGame` con el origen demo oficial devolvió 403 con `cf-mitigated: challenge` sin enviar cuerpo ni encabezado firmado. El cliente oficial solo anuncia un host de inicio demo. La variante de producción queda fuera de la prueba.

Spinomenal incorpora 113 modalidades de compra con elección de tiradas gratis. El adaptador comprueba que la sesión ofrezca la rama solicitada y que `PickFreeSpins` devuelva su tipo, cantidad y coste. Cada variante tiene una traza histórica con cierre y saldo conciliado. En 112 hubo premio positivo. Las variantes que necesitan otro menú, varias fases de elección u otro tipo de continuación siguen pendientes.

El ejecutable Rust de KA Gaming integra 885 modalidades de 837 juegos a partir de las capturas, incluyendo 23 compras, 16 antebet y nueve variantes. Antes de enviar una jugada, comprueba el hash del JavaScript del juego y del motor, además del mínimo ofrecido por la nueva sesión demo. Las compras por `atb` de HotCoinBF vuelven a `atb=0` en las continuaciones cuando corresponde. Penalty Shootout comprueba el eco del objetivo solicitado. Space guarda la elección `bonusPick`, comprueba el cierre nativo y concilia el premio de la elección sin volver a sumar el premio de la tirada. El acceso en vivo del ejecutable sigue pendiente por el 403 del arranque.

El diagnóstico GECO sigue el lanzamiento oficial y, si recibe una sesión demo nueva, consulta `/config` de la misma mesa y arma la inicialización de `CasinoGameServlet` con los parámetros de esa sesión. Acepta los identificadores demo con el relleno `=` observado en las capturas y omite cookies en la llamada al servlet, como hace el SDK. El diagnóstico solo envía `action=init`. En Aloha Christmas, el emisor respondió HTTP 200 con `issuer_declined`, por lo que no se alcanzó `/config`.

El runner de Habanero añade 41 modos normales al comparar la configuración de monedas por apuesta del JavaScript oficial con los importes y cierres de los registros históricos. Fija el hash de ese archivo por modalidad y lo comprueba antes de abrir sesión. Before Time Runs Out cerró en demo por HTTP con coste 0,15, premio 0,10 y saldo final 1.999,95. La verificación en vivo de las otras 40 incorporaciones sigue pendiente.

También cerraron y conciliaron por HTTP las tres elecciones de Cake Valley, Christmas Gift Rush, Taberna de los Muertos Ultra y Jellyfish Flow Ultra. En los giros de Jellyfish Flow Ultra, el runner usa `betMode: "ultra"` y las 27 vías del cliente público actual. Christmas Gift Rush admite la continuación `gameMode: "free"` para el estado `respin` observado en su captura. El plan de Habanero contiene 313 modalidades y conserva dos solicitudes de Super Bet pendientes de un contrato nativo. En los clientes públicos de Laughing Buddha y Zeus Deluxe, `callMain` agrega `featureBuy` cuando corresponde y llama al constructor común, que solo incluye `superBet` si el juego lo pasa como extra. Ninguno se lo pasa. Las capturas con `superBet: 1` muestran el precio base, 28 y 25 monedas respectivamente, frente a los factores 50 y 18 definidos en el cliente. Los hashes SHA-256 del JavaScript revisado son `aaaea19ff2ba5d56ea608f3706169b8286b20b28c19e640c882aa004d54ff96d` (Laughing Buddha), `54ab585b1e2222f31481f52137af3f7c10f834b2aeeaa03f31585985ecefa65a` (Zeus Deluxe) y `1bff6fd3ff247f227563d45c627f86599b2e415db683e040a1531cf45e93d2c7` (Slots-Common).

### Qué falta para validar los cinco ejecutables en vivo

El inventario de ejecución representa la compra 101 de Aztec Tribute mediante las tres elecciones conciliadas: Wild Multiplier, Ways Multiplier y Random. Cada variante envía una sola compra y sigue con su elección y cierre. El worker conserva el identificador de la compra original y el hash de la traza correspondiente en la exportación del inventario. Las tres capturas registran un coste de 10 y premios de 4,90, 9,90 y 2,20, respectivamente. El arranque en vivo del ejecutable sigue pendiente por el 403 de la entrada oficial.

| Proveedor | Acceso o dato necesario | Canal oficial |
| --- | --- | --- |
| Red Tiger | Un entorno de integración ficticio que admita el cliente HTTP autónomo, con emisión de sesión y saldo nativo antes y después de una tirada. | [Red Tiger for Developers](https://redtiger.com/back-office/red-tiger-for-developers) · [Soporte técnico](https://redtiger.com/contact) |
| NetEnt | Un emisor de sesiones ficticias operativo que entregue la configuración del juego y el identificador de saldo al cliente. | [Integración de operadores de Evolution, informe anual 2023, p. 15](https://www.evolution.com/wp-content/uploads/2024/04/Evolution_Annual_Report_2023.pdf) |
| KA Gaming | Acceso al entorno de pruebas y al contrato de inicio, ronda y saldo. El proveedor ofrece documentación y sandbox a pedido. Sus términos excluyen la automatización de la demo pública. | [KA Gaming, plataforma y contacto](https://www.kaga88.com/) · [Términos, §4](https://www.kaga88.com/tos.html) |
| Spinomenal | Un inicio de sesión de prueba que permita llegar a `StartSlotMachine` y confirme `DemoMode=1` antes de apostar. | [Contacto de Spinomenal](https://spinomenal.com/contact-us/) |
| Iron Dog | Una respuesta de saldo final del proveedor para la misma sesión ficticia. La evidencia actual solo acredita el cierre nativo, el coste y el premio. | [Contacto de 1X2 Network](https://www.1x2network.com/contact/) |

El arranque de la demo es automático. Cada muestra abre una sesión HTTP aislada, recorre el lanzamiento y la autenticación propios del proveedor y utiliza el mismo cliente y almacén de cookies durante toda la ronda. No se necesita importar cookies ni tokens. Los `Set-Cookie` recibidos se aplican respetando dominio, ruta, expiración y `Secure`; las cookies recibidas al abrir WebSocket también actualizan esa misma sesión. Endorphina sigue las redirecciones iniciales del enlace público `/play` dentro de sus rutas revisadas, y mantiene coherente el `User-Agent` de HTTP, WebSocket y el dato de lanzamiento. Peter & Sons genera la clave anónima en el rango del ejecutor publicado.

Las pruebas locales de Hacksaw y Pragmatic exigen las cookies emitidas por el arranque para inicializar y ejecutar. Sin ellas, el servidor de prueba devuelve 403 antes de aceptar una apuesta. Esto prueba la continuidad de sesión; no acredita que un 403 remoto concreto haya desaparecido. La documentación histórica registra además desafíos `cf-mitigated: challenge` que persistieron con sesiones HTTP nuevas.

Un 403 HTTP completo durante el arranque admite una única sesión nueva, siempre que no exista ninguna intención financiera ni un desafío declarado. El primer intento conserva sus intercambios y su dueño archivado. El segundo rechazo, un 403 financiero, un desafío declarado, 429 o 503 retienen el bloqueo. No se reenvía una apuesta para renovar sesión. Un cuerpo interrumpido o demasiado grande conserva estado, cabeceras, cookies y prefijo recibido; sus metadatos indican que está incompleto y no habilita una repetición financiera. Los rechazos WSS conservan los bytes disponibles como `handshake-buffered`.

Para una raíz interrumpida que nunca tuvo intención financiera, `recover-nonfinancial ROUND_ID --reason TEXTO` registra una recuperación auditada, conserva las evidencias y termina el intento como bloqueado, sin contarlo como éxito. Rechaza raíces financieras y proveedores cuyo lock sigue ocupado. Después de revisar la causa puede liberarse la retención mediante `release-hold` y crearse otra campaña. Las raíces con posible apuesta aceptada conservan su dueño original.

## Exportación y privacidad

`export --output CARPETA` crea una carpeta nueva y falla si ya existe. Por defecto solo incluye rondas verificadas. Los filtros son `--provider`, `--game` y `--kind` (`normal`, `purchase`, `antebet`, `booster`, `variant`, `special`); `--include-unverified` incluye estados incompletos, diferenciados en cada registro.

El árbol agrupa `inventario/proveedor/juego/tipo/modalidad/tiradas.jsonl`; los componentes se codifican para evitar colisiones y traversal, mientras que cada línea conserva los IDs nativos exactos. `manifest.json` contiene grupos, rutas y cantidades. Cada línea pública incluye IDs de ronda y campaña, inventario, muestra, proveedor, juego y modalidad; estado; y, cuando existe, moneda, `monetary_unit`, `currency_source`, saldos, costo, premio y controles. Los importes son cadenas decimales exactas; interprete la unidad y procedencia de moneda con sus campos, no como una unidad supuesta. Se omiten configuración, sesión, errores crudos y payloads nativos.

`currency_source` distingue `native_response`, `launcher_parameter` y `public_binding`. Si Peter & Sons o Playson no publican moneda en la inicialización, el valor proviene de la configuración pública explícita y se etiqueta `public_binding`. Un campo nativo que la contradiga detiene la ronda. `monetary_unit: native` conserva la escala original sin asumir que son unidades mayores de EUR/USD; `major` indica la conversión establecida por el contrato y configuración. No mezcle ambos tipos de importe en agregados sin normalizar su escala.

`--include-wire` incorpora propietario actual, propietarios de bootstrap archivados, solicitudes, respuestas y datos nativos: el resultado es confidencial y puede contener credenciales o URLs autenticadas. `show ROUND_ID --private --output privado.json` guarda una vista privada en un archivo nuevo con permisos restrictivos; no la imprime en consola. Ambos requieren custodiar el archivo como material sensible.

Los frames WebSocket se guardan antes de interpretar su JSON, incluidos los recibidos antes de un error. `--relay http://127.0.0.1:PUERTO` se aplica tanto a HTTP como a WSS mediante CONNECT; no hay salida directa alternativa si el relay falla. Las variables de proxy del entorno no se usan automáticamente.

La integración continua compila y ejecuta pruebas locales en Linux y Windows, y publica un artefacto por plataforma con el ejecutable, inventarios y catálogo. Consulte [VERIFICATION.md](VERIFICATION.md) para el alcance real de las comprobaciones de esta versión.

## Ejecutables Windows por proveedor

Los targets `hacksaw`, `pragmatic`, `reelkingdom`, `endorphina` y
`peterandsons` incluyen su inventario y configuración pública. El ejecutable
se puede copiar solo a una carpeta vacía. `games` lista los juegos,
`check 2405 normal` verifica el plan de Hacksaw sin conexión y
`run 2405 normal` ejecuta una muestra ficticia con conexión a la demo oficial.
Windows guarda el historial bajo `%LOCALAPPDATA%\Evidencia\DemoRunners`;
`--data` selecciona otra carpeta. Conservar esa carpeta después de una ronda
incierta para mantener su evidencia y su bloqueo.

El 14 de noviembre cerraron y conciliaron una normal autónoma Hacksaw 2405,
Pragmatic vs20wildparty, Reel Kingdom vs10gdchalleng y Endorphina 525.
Playson usa el Origin y Referer del lanzador oficial en el adaptador Rust y
carga sus configuraciones públicas desde `bindings/playson.json`.
3 Roaring Bells cerró y concilió por HTTP la normal, el antebet 1.5 y las
compras 0 y 1 con la compilación pública 1.13.0. El primer intento registró
HTTP 200 con JavaScript de una compilación distinta a la fijada y se detuvo
antes de abrir sesión. Se guardaron los hashes de la versión histórica y
la actual. El plan general incluye las 33 modalidades de Playson incorporadas
mediante la revisión de los recibos históricos.

Charge the Clovers cerró y concilió por HTTP sus seis modos en la versión
pública 1.24.0: normal, antebet 2 y 3, y compras 0, 1 y 2. Las compras
enviaron el contador de bono que usa esa versión. El primer intento con el
hash anterior recibió HTTP 200 y se detuvo antes de abrir sesión. El historial
privado conserva el evento de bloqueo y los seis recibos verificados.

Los otros 17 juegos de esta revisión también cambiaron de compilación pública.
Con sus bindings actualizados, el runner concilió 39 casos por HTTP: 17
normales, 5 antebet y 17 compras, incluida la elección de Vegas Glitz. Los 27
modos recuperados en esos juegos están incluidos en los 39 casos.
