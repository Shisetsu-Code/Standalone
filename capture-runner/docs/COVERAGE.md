# Cobertura de protocolos

Resultado de `capture-runner plan --details` sobre el inventario publicado. «Ejecutable» significa que existe un selector y flujo implementado; no certifica disponibilidad remota actual ni éxito de una captura. Los modos pendientes se enumeran en [coverage.json](coverage.json).

| Proveedor | Juegos con modo ejecutable | Modos ejecutables | Modos identificados | Pendientes |
|---|---:|---:|---:|---:|
| 1spin4win | 225 | 265 | 283 | 18 |
| amigogaming | 156 | 207 | 207 | 0 |
| amusnet | 466 | 759 | 763 | 4 |
| belatra | 117 | 302 | 302 | 0 |
| betsoft | 3 | 3 | 574 | 571 |
| bgaming | 215 | 787 | 808 | 21 |
| egt-digital | 231 | 331 | 331 | 0 |
| ela-games | 68 | 134 | 134 | 0 |
| elk | 159 | 803 | 803 | 0 |
| endorphina | 238 | 563 | 563 | 0 |
| evoplay | 238 | 591 | 1.080 | 489 |
| gamesglobal | 2 | 2 | 2 | 0 |
| habanero | 205 | 313 | 315 | 2 |
| hacksaw | 142 | 744 | 744 | 0 |
| hardfire-kalamba | 1 | 1 | 66 | 65 |
| irondog | 2 | 3 | 379 | 376 |
| kagaming | 837 | 885 | 885 | 0 |
| kendoo | 2 | 2 | 76 | 74 |
| mascot | 117 | 180 | 211 | 31 |
| microgaming | 1 | 1 | 49 | 48 |
| netent | 197 | 373 | 440 | 67 |
| nolimit | 141 | 1.147 | 1.147 | 0 |
| peterandsons | 70 | 223 | 223 | 0 |
| playngo | 476 | 493 | 493 | 0 |
| playson | 114 | 242 | 242 | 0 |
| playtech | 1 | 1 | 3.940 | 3.939 |
| pragmatic | 656 | 1.665 | 1.687 | 22 |
| redtiger | 361 | 609 | 610 | 1 |
| reelkingdom | 73 | 183 | 183 | 0 |
| rubyplay | 1 | 1 | 262 | 261 |
| smartsoft | 41 | 66 | 66 | 0 |
| spinomenal | 536 | 1.343 | 1.581 | 238 |
| threeoaks | 103 | 234 | 234 | 0 |
| thunderspin | 60 | 84 | 84 | 0 |
| yggdrasil | 138 | 301 | 301 | 0 |
| **Total** | **6.393** | **13.841** | **20.068** | **6.227** |

Los 648 juegos del inventario común sin modos permanecen en el catálogo y no originan apuestas inventadas. Dos de ellos reciben los selectores suplementarios publicados para Games Global.

Se reconstruyeron los contratos adicionales conservados en referencias: NoLimit, ELK, BGaming legacy/RPC/Cocos, mesas y juegos clásicos de Play’n GO, y Yggdrasil. En Yggdrasil se incluyen los 18 rechazos históricos que sí tienen todos los parámetros: un resultado anterior fallido no excluye un intento conocido.

RubyPlay y Playtech tienen cobertura muy parcial porque los índices exportados apuntan a decodificadores y motores que no se incluyeron en el repositorio. [MISSING-EVIDENCE.md](MISSING-EVIDENCE.md) identifica las rutas concretas de cada familia. Los cupos se calculan independientemente de esta cobertura, y `plan` también limita la concurrencia máxima al número de juegos ejecutables elegidos.

Las elecciones condicionales sólo se marcan completas si se ejerció la acción solicitada. Si la ronda cierra sin ofrecer esa rama conocida, el intento conserva su captura y el motivo `target_not_observed`; no se inventa la elección.

Los bindings y protocolos tienen procedencia verificable en [PROVENANCE.md](PROVENANCE.md). Las pruebas de esta entrega son locales: no se establecieron túneles reales ni se contactaron proveedores.
