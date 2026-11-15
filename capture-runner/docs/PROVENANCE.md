# Procedencia y alcance

## Base publicada

El punto de partida es [Standalone, commit 749ae8e4ca8e50326cc756fda8efb916c47b0be8](https://github.com/Shisetsu-Code/Standalone/tree/749ae8e4ca8e50326cc756fda8efb916c47b0be8).

Se preserva `standalone info/` sin modificaciones. Contiene 35 inventarios, 9.874 registros de juegos y 20.066 modos. El cargador verifica los hashes de inventario y plan contra el manifiesto de cada proveedor. El inventario individual publicado de Games Global aporta otros dos selectores, por lo que la unión utilizada por el nuevo runner tiene 20.068 modos.

La fuente de los protocolos son las copias de `standalone info/*/codigo`, los adaptadores de referencia de `game-runner/src/adapters`, los módulos portables de `bet-collector/game-runner/src` y los protocolos Python completos conservados dentro de `referencias`. Se reconstruyeron los conectores sobre un transporte y un motor independientes. No existe dependencia de ejecución con los crates anteriores, su `Store`, sus recibos financieros o la suite Python externa.

Los bindings públicos utilizados al compilar están incluidos en este crate. [binding-provenance.json](binding-provenance.json) distingue copias exactas y datos derivados, e identifica sus fuentes, tamaño y SHA-256. Los fixtures derivados omiten sesiones privadas y campos financieros innecesarios. Para comprobar sus bytes, ejecutar desde la raíz:

```bash
sha256sum -c capture-runner/docs/BINDINGS.sha256
```

Las fórmulas que permanecen en los conectores sirven para formar parámetros nativos de solicitudes. No se exige que un saldo concilie para aceptar un cierre o continuar otro juego.

## Traspaso aportado el 14 de noviembre de 2026

Archivo: `traspaso-claude-20261114.zip`.

SHA-256: `fbec4dffd86c4df04dc7a7f9ece4f4efd922b61d74afd194384e1d8679836a9f`.

Sus 15 entradas de manifiesto coinciden en hash y tamaño. Aporta protocolo y resultados agregados de Habanero, Mascot y Yggdrasil. Se utiliza como evidencia adicional y para construir pruebas sin sesiones reales; el ZIP y los históricos privados no se incorporan al repositorio.

- **Habanero:** `PROTOCOL.md`, las pasadas y el plan de 475 operaciones sustentan elecciones y continuaciones adicionales. La aceptación depende del cierre nativo; los flags históricos de saldo no se convierten en bloqueos.
- **Mascot:** los 129 registros comprenden 117 slots ya identificados por los bindings y 12 juegos de otros tipos. Los resultados ayudan a verificar acciones y cierres; no se inventan selectores para los juegos restantes.
- **Yggdrasil:** el checkpoint especifica la construcción de `play` y `cont`. Su unión con el CSV publicado permite reconstruir los 301 selectores únicos: 138 normales, 135 compras y 28 antebets. Se deduplican cuatro observaciones equivalentes. Se incluyen los 18 intentos históricamente rechazados porque sus parámetros están completos: el resultado anterior es metadata, no un bloqueo. La oferta actual se valida antes de enviar; un rechazo se captura como `provider_error` y una continuación nueva como `unknown_event`.

El traspaso no contiene los decodificadores por juego de RubyPlay. Tampoco entrega los archivos de resultados de Microgaming o Games Global que su informe menciona como pendientes de localizar.

## Cobertura ejecutable

La tabla de conectores es única para planificación y ejecución. `plan --details` enumera cada modo sin implementación disponible. Los nombres `ready`, `campaign_eligible`, `verified` y los conteos históricos no amplían esa cobertura por sí solos.

NoLimit reconstruye los 1.147 selectores de sus 141 juegos y sus contratos de elección publicados. ELK reconstruye los 803 selectores de 159 fichas, con ECF clásico/moderno, variantes y progreso nativo Boss. BGaming incorpora legacy v2/v1, variantes, elecciones y las familias RPC/Cocos reconstruibles: 787 modos de 215 juegos. Comprueba la fuente y el menú activo antes de enviar la apuesta. Play’n GO agrega las 18 mesas y juegos clásicos cuyos contratos Python sí estaban publicados. Las pruebas de los selectores usan inicializaciones y contratos de la evidencia.

RubyPlay dispone del índice del decodificador de African Cats (`rp_47`); sus otros decodificadores no están publicados. Playtech también conserva los índices de sus motores genéricos sin los programas correspondientes. [MISSING-EVIDENCE.md](MISSING-EVIDENCE.md) lista rutas concretas y diferencia los archivos ausentes de las familias aún no portadas. No se extrapola un selector o decodificador a otro juego por pertenecer al mismo proveedor.

Una captura local clasificada como `complete` significa que el conector reconoció el cierre nativo observado. Las pruebas automatizadas validan parsers, transiciones, journal, planificación y aislamiento de procesos con fixtures locales. La disponibilidad actual de los servidores, los cambios de JavaScript y la conectividad de túneles reales se verifican al ejecutar en la VM.

## WireGuard

La red sigue el modelo oficial de [WireGuard y namespaces](https://www.wireguard.com/netns/): crear la interfaz en el namespace original y moverla al del worker conserva el socket UDP en el original. Las rutas del worker sólo incluyen su interfaz WireGuard y loopback. Los detalles de instalación se basan en la [guía oficial](https://www.wireguard.com/quickstart/).

Las claves son archivos operativos externos, nunca bindings del repositorio. Las pruebas de setup, rollback y cierre usan comandos simulados y no requieren peers reales.
