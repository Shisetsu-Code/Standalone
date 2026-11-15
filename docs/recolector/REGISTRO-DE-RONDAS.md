# Registro de rondas demo

El recolector debe usar HTTP para los contratos HTTP y WebSocket cuando lo requiera el protocolo nativo. El relay puede transportar esas conexiones. El inventario debe indicar si la prueba salió de un cliente HTTP/WS directo, pasó por el relay o dependió de un navegador. Las simulaciones locales tienen su propia fuente de evidencia.

La implementación en Rust se apoya en `game-runner`. Antes de sustituir un ejecutor existente, hay que comprobar que el runner Rust ejecuta el contrato nativo y conserva su evidencia. Lanzar un adaptador Python desde Rust no equivale a portar el protocolo.

## Inventario por proveedor, juego y modo

| Registro | Campos |
| --- | --- |
| Juego | Proveedor, ID nativo, nombre, enlace demo, familia de protocolo, versión del cliente y fuente del inventario. |
| Modo | ID nativo, etiqueta visible, tipo (normal, antebet, compra, activador o especial), parámetros del selector, líneas aplicables y costo o multiplicador observado. |
| Opciones | Fase, opciones ofrecidas por el servidor o cliente oficial, ID y etiqueta nativos, opción elegida y referencia a su respuesta. Registrar por separado las opciones ofrecidas y las ejecutadas. |
| Endpoint | Etapa, transporte, método HTTP y ruta o mensaje WS, campos del pedido, forma de la respuesta y evidencia del contrato. Las plantillas guardan marcadores para credenciales y valores de sesión. |
| Intento | ID local, modo seleccionado, entorno demo, versión, referencia de ronda nativa, importe y unidad, saldo inicial y final, estado del cierre y resultado de la conciliación. |

Registrar la fuente que demuestra cada modo. Si el juego sólo mostró una tirada normal, la existencia de otros modos queda pendiente hasta revisar un inventario nativo que los confirme o descarte.

## Inicio y cierre de una compra

1. **Oferta y selección.** Guardar el ID de compra, precio o multiplicador, apuesta base, costo total y opciones disponibles. Abrir el menú o seleccionar una oferta es una fase previa.
2. **Envío y aceptación.** Antes de enviar, registrar la operación y su secuencia. Guardar la respuesta que confirma el cargo, el ID de ronda y la primera fase. Si se perdió la respuesta, dejar el intento incierto y conservar el envío original.
3. **Continuaciones.** Guardar en orden cada elección, tirada gratis, giro adicional, reactivación, cobro o confirmación con su solicitud, respuesta y referencia de ronda. Distinguir el cargo inicial de cualquier cargo adicional demostrado.
4. **Cierre.** Guardar la respuesta terminal nativa y, cuando corresponda, el cobro o la actualización de saldo. La última tirada gratis puede preceder al cierre. Si falta la confirmación terminal, registrar la fase pendiente y el último mensaje confirmado.
5. **Conciliación.** Verificar en unidades nativas exactas que el saldo final corresponde al saldo inicial, los débitos y los créditos efectivamente asentados. Registrar premios pendientes de cobro y ajustes documentados por separado. Si la demo omite el saldo, registrar el cierre nativo y marcar el saldo como no publicado.

El resumen debe permitir ir desde el inventario de un juego al intento y a los mensajes que demuestran oferta, aceptación, elecciones y cierre. SQLite ya registra campañas, casos e intentos en el recolector. Los mensajes detallados y su orden quedan en el registro privado del intento. Los informes exportan únicamente campos permitidos y referencias saneadas.

Hacksaw ya tiene un lector Rust de trazas saneadas. `hacksaw audit-trace <archivo.json>` vuelve a calcular el saldo con los importes nativos y devuelve los índices de entrada, aceptación y cierre, las compras publicadas, las opciones de cada respuesta y la acción elegida. El comando lee archivos locales y no abre una sesión.
