# Sesiones y ejecución de demos

El inventario está en [Proveedores y juegos](PROVEEDORES.md). Cada ficha identifica el adaptador de la suite que implementa la familia y el criterio de cierre. El [registro de rondas](REGISTRO-DE-RONDAS.md) define los campos comunes para pedidos, respuestas, controles, saldos y evidencia.

## Flujo para cada juego

1. Resolver el enlace público y comprobar el ID nativo, la familia de protocolo y la versión actual del cliente. El catálogo se conserva con las fichas pendientes.
2. Abrir una sesión nueva de saldo ficticio por HTTP o WebSocket. Usar el relay local en las rutas donde esté validado. Cuando el proveedor requiera el navegador, obtener la sesión en un contexto aislado y mantener las llamadas en ese contexto.
3. Leer el estado inicial, la moneda, los niveles de apuesta, las líneas y las opciones nativas. Vincular la modalidad elegida a su selector y su precio actuales.
4. Crear el intento en SQLite y guardar el pedido antes de enviarlo. Mantener el mismo dueño, identificador de ronda y contador durante el bono. Si una respuesta se pierde, retener el intento para revisión.
5. Completar las fases que publica el servidor. Guardar cada elección y su lista de opciones. Confirmar el cierre y conciliar el saldo con los premios nativos. Si el saldo no está publicado, registrar por separado el cierre observado.
6. Guardar el resultado y el registro común en el directorio privado del intento. Publicar el inventario de cobertura y referencias saneadas.

## Obtención de sesión por contrato

| Familia | Secuencia comprobada o estado |
| --- | --- |
| Hacksaw | `GET /{game_id}/version.json` en el CDN, `POST /api/play/authenticate` con el perfil público demo y `POST /api/play/bet`. La autenticación devuelve saldo, niveles y compras. Las continuaciones usan la misma ronda y el cierre llega como `completed`. Rust verificó una normal y la compra `fs` de Power of Ten por HTTP a través del relay. |
| SmartSoft | Ficha oficial → `/GameLauncher/Loader.aspx` → documento `/SlotsDemo/`. Se valida portal DEMO y moneda DMO. `CustomEvent/{game_id}/{session_token}` con `update.balance` y `Events/{game_id}/{session_token}/0` leen el estado `start.game`. Las acciones nativas usan `Event/2/{game_id}/{session_token}`. Rust verificó el inventario inicial de MultiHot40. |
| Belatra | Lanzador oficial `/belatra/demo` → contexto de navegador propio → `POST /game` con `enter`. La respuesta debe devolver moneda FUN y fase `toIdle`. Las solicitudes posteriores mantienen la identidad emitida y el historial de la ronda hasta `finish`. El recolector ya cerró una normal de Chef’s Fruits con este transporte. |
| Playson | Enlace público `/launch` → documento y scripts del juego → XML `/connect` y `/reconnect`. HardFire confirmó perfil TEST y estado `idle` para Lucky Pots x1000. El intento por relay recibió 403 en `/connect`. |
| Endorphina | Launcher oficial y transporte nativo con mensajes protobuf. El relay ya resolvió la conexión IPv4 cuando falló IPv6. El recolector cerró y concilió una normal. |
| Red Tiger | `POST /api/v1/oss/token/demo` con el `tableId` publicado → entrada emitida por el proveedor → `/game/settings` para validar la identidad demo. El recolector recibió 403 en la entrada. |
| Iron Dog | Lanzador → `getGuestID.jsp` → `/gateway/init` → setup del motor. El cliente HTTP del recolector fue rechazado en `init`. La ruta pública en navegador llegó al aviso de sonido. Algunos motores antiguos publican cierre sin un saldo independiente. |
| Pragmatic y Reel Kingdom | Runner compartido, con identidad canónica de Pragmatic. El flujo usa sesión demo y acciones nativas hasta el último estado y su cobro. El inventario conserva Reel Kingdom como alias de sus juegos. |
| Playtech | GPAS se ejecuta por protocolo remoto. Los perfiles NGM con motor local quedan identificados como cálculo local en el inventario. Cada familia conserva sus condiciones de sesión y cierre. |

Las fichas de [todos los proveedores](PROVEEDORES.md) incluyen su familia, controles inventariados, adaptador de referencia y criterio de cierre cuando están identificados. Las familias sin clasificación quedan pendientes. Los ejemplos usan parámetros de sesión simbólicos. El operador debe obtener una sesión nueva al ejecutar.

## Servicios y ejecución

- Dashboard local en `127.0.0.1:8787`, relay explícito en `127.0.0.1:8793` y recolector en `127.0.0.1:8796`.
- El ejecutable Rust `game-runner` permite consultar proveedores, previsualizar un juego o modalidad y consultar una campaña. Las familias migradas ejecutan su protocolo en Rust. Las demás siguen usando los adaptadores indicados por el inventario.
- En la suite de trabajo, `bet-collector/overnight-run.ps1` verifica el plan sin enviarlo. El parámetro `-Start` es el que inicia la campaña.
- Los journals y capturas originales contienen datos de sesión. La documentación se reproduce con una sesión propia nueva. Los archivos de publicación incluyen sólo el catálogo, controles y referencias revisados.
