# Repetir rondas de demo

Empezá por [el mapa de los 35 proveedores](mapa.json). Identifica inventario, evidencia histórica, punto de entrada Python, dependencias locales conocidas y adaptador Rust autónomo cuando existe. Las rutas de inventario, evidencia y código son relativas a este directorio. Las rutas de dependencias se resuelven desde la raíz del repo. Una dependencia presente puede requerir otros archivos de la suite.

- [Inventarios y modalidades](../PROVEEDORES.md) con 9.874 fichas y 20.063 modalidades registradas. Incluye ramas y alias.
- [Arranque y sesiones](../SESIONES-Y-EJECUCION.md) para localizar los lanzadores y validar que la sesión es ficticia.
- [Esquema de captura](../REGISTRO-DE-RONDAS.md) para guardar la solicitud antes de enviarla, las opciones ofrecidas y elegidas, el débito, cada continuación, el cierre y la conciliación.
- [Código del recolector Python](../../../bet-collector/collection_worker.py), [dependencias Python](../../../bet-collector/requirements.txt) y [módulos Rust integrados](../../../bet-collector/game-runner/src). El punto de entrada del mapa indica el código que prepara las solicitudes y reconoce las respuestas. Los adaptadores pueden cargar controladores, catálogos y perfiles adicionales de la suite. La mera presencia del punto de entrada indica que existe un camino de ejecución para alguna parte del proveedor.
- [Runner Rust autónomo](../../../game-runner/README.md) para cinco familias y seis IDs. Requiere Rust 1.99. El [informe de CI](../../runner-results/2026-11-12-actions-43302603557.json) acredita una normal cerrada para Pragmatic, Reel Kingdom, Hacksaw y Endorphina. Peter & Sons carga su configuración pública para 70 slots y 223 modalidades conciliadas. Playson requiere configuración explícita. Usá primero import, inventory, capabilities, plan y check. El comando run envía acciones de demo.
- [Ciclos históricos saneados](ciclos-historicos.json) con seis muestras de Hacksaw, SmartSoft, 3 Oaks y BGaming. Incluyen modo, fases disponibles en el registro original y saldo. El SHA256 apunta al registro original. Son ejemplos de validación del resultado, con cobertura parcial del protocolo.

## Cómo portar una modalidad

1. Elegí el ID nativo y la clave exacta del inventario. Abrí el adaptador indicado y seguí su arranque y serialización. Revisá el historial del mismo juego si hay versiones o familias diferentes.
2. Obtené una sesión pública ficticia nueva. Conservá su contexto, cookies y orden de mensajes hasta el cierre. Confirmá la moneda y el modo demo según el contrato del proveedor.
3. Leé los controles vigentes en la inicialización. La normal, cada antebet y cada compra llevan su propia clave y precio. Para líneas configurables, guardá la opción elegida y su efecto sobre el costo. Tratá las elecciones de un bono como continuaciones cuando el servidor las ofrece dentro de la ronda.
4. Registrá método y ruta o tipo de mensaje WS, campos requeridos, unidades monetarias e identificadores dinámicos. Guardá el pedido antes del envío y enlazá las respuestas a la raíz. Si hay una respuesta perdida después de un posible débito, retené la ronda con su contexto.
5. Verificá el cierre según la familia. Cuando existe un saldo independiente, verificá saldo inicial menos costo más premios nativos igual a saldo final. Registrá el origen de los premios y conservá la secuencia de fases hasta finalizar. Playtech NGM con motor local queda identificado como cálculo local. GPAS se valida contra la respuesta remota.

## Qué queda por recuperar

El mapa cubre los 35 inventarios. 34 IDs tienen un punto de entrada Python y Games Global sigue sin adaptador ejecutable. Kendoo está pausado. Las compras de Microgaming y Kalamba tienen verificación pendiente. Para una modalidad cuya evidencia publicada sólo contiene un puntero y un hash, recuperá el archivo original de la suite y extraé un ejemplo saneado, o validá el flujo en una sesión ficticia nueva cuando esté autorizado. Los originales con identificadores de sesión se conservan localmente. La instalación portable para todos los proveedores aún requiere recuperar dependencias y bindings de la suite y comprobarlos en un checkout limpio.

El [ejemplo HTTP de Hacksaw](hacksaw-http.json) conserva el arranque, los campos de apuesta y continuación y una proyección de las respuestas de dos rondas. Los valores entre ángulos se obtienen en ejecución.
