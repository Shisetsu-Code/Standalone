# RubyPlay: reporte (demos públicas oficiales, saldo ficticio)

Fuente: `provider-work/rubyplay-chat2/results/` (`provider-report.json`, `coverage-final.json`, `monitoring.json`, `batch-progress.json`, `ruby-events.jsonl`). Sin tokens, sesiones ni HAR en este reporte.

**Nota:** `CONTINUITY.md` describe un estado anterior ("rondas no ejecutadas, gate cerrado"). El estado vigente es el de `provider-report.json` y `coverage-final.json`, que registran rondas ejecutadas y conciliadas.

## 1. Estado
- Estado del reporte: `official_demo_baseline_completed_ruby_extension_needs_review`.
- Catálogo oficial de RubyPlay: 180 entradas en 6 páginas, completo y verificado (`termination_verified: true`).
- Identidades nativas resueltas: 179 de 180. Una entrada próxima no tiene metadatos de demo utilizables.
- Juegos verificados en tirada normal: **179**.
- Modos verificados liquidados: **257**.
- Compras ofrecidas por el servidor verificadas: **78** (`missing_offered_purchase_modes: []`).
- Solicitudes de juego enviadas: **1.413**.

## 2. Compras de Ruby (extensión)
- Verificadas (4): `rp_65`, `rp_57`, `rp_37`, `rp_29`. Acumulación de raíces verificada en 9.729 casos.
- Pendiente (1): `rp_26`, por una raíz incierta.
- Raíz incierta `ruby-probe-214-0001`: timeout sin respuesta. **No se reenvió.**
- Compras "legacy Ruby" no probadas en 5 juegos (`rp_65`, `rp_57`, `rp_37`, `rp_26`, `rp_29`): saldo Ruby inicial 0. No se inventaron monedas.

## 3. Fuentes de catálogo
- **RubyPlay oficial:** completa y requerida para jugar.
- **SlotCatalog:** solo 2 de 18 páginas; HTTP 403 (acceso detenido). Diferida por decisión del usuario.
- **SlotTemple:** HTTP 403. Diferida por decisión del usuario.
- Registros de fuente: 229; 179 identidades resueltas; 49 sin resolver; 31 coincidencias de título entre fuentes (no se deduplicaron).

## 4. Método
- Se usaron solo enlaces de demo públicos y oficiales.
- Modo `fun` y modo `offline` según la pestaña de cada juego.
- Las rondas se conciliaron con matemática nativa (costos y premios).
- Política de cero reintentos ante solicitudes inciertas.
- Un cambio resuelto en TLS: cadena intermedia oficial alternativa, validación de hostname y cadena completa conservadas.

## 5. Limitaciones (según el reporte)
- Solo se verificaron las variantes de sesión declaradas. Continuaciones y elecciones alternativas no están cubiertas por completo.
- Las características naturales no disparadas no están verificadas.
- Los identificadores nativos y los enlaces de demo no equivalen a cobertura de rondas.
- `rp_90` (SlotCatalog) solo se observó en modo "offline": no hay liquidación remota demostrada.
- `rp_240` solo tiene inicialización capturada con estado HAR 0: no prueba una ronda pagada.

## 6. Endpoints y protocolo

Endpoints (de los scripts de `rubyplay-chat2/`):
- Sesión de demo (GET): `https://srv.prrpeu3.com/init-session/demo?gamename=<rp_id>&operator=rubyplay.com&mode=fun&currency=EUR&playerSession=...`. Devuelve `sessionKey` y `funModeData`.
- Inicialización del juego (POST): `https://srv.prrpeu3.com/gameserver/demo` con `action: "init"`, `v_protocol`, `v_math`, `key` (sessionKey), `device_type: "desktop"` y `funModeData`.
- Juego (POST): `https://srv.prrpeu3.com/gameserver/demo`, con `action` de juego (ver abajo). Solo se permiten las acciones revisadas en `binding`: `spin`, `respin` y `buy_feature` (en `rp_222`).
- Lanzador público: `https://prrpeu3.com/launcher?gamename=<rp_id>&operator=rubyplay.com&server_url=https://srv.prrpeu3.com&currency=EUR&mode=fun`.
- Catálogo: `https://rubyplay.com/reel-winners/` (6 páginas).

Códigos de acción observados en los resultados (`results/rp_*-normal.json`, `results/rp_*-purchase-*.json`):
- `1`: tirada normal (`spin`). Costo = apuesta mínima nativa en la primera ronda.
- `2`: continuación de bono (`next_action: 2`), costo 0.
- `10`: compra de bono (`buy_feature:freespin`), costo = precio de compra.

Formato de cada paso en los resultados: `key`, `action`, `cost`, `before_balance`, `total_win`, `paid_win`, `expected_balance`, `server_balance`, `wallet_matches`, `next_action`.

## 7. Lo que no está en este reporte
- **Cuerpos de solicitud completos** (campos de la apuesta, `v_protocol`, `v_math` exactos y `binding`): los resultados solo guardan la acción y el resumen del paso. Los cuerpos sanitizados no están en `results/`; los scripts los usan desde `rubyplay-chat2/*.py` y `binding`. Para replicar, hay que tomarlos de la carpeta original o de `private/` (que no se incluye aquí).
- **Compras Ruby**: `results/ruby-events.jsonl` registra eventos de acumulación y compra, no solicitudes.

## 8. Archivos clave
- `results/provider-report.json` (resumen estructurado).
- `results/coverage-final.json` (cobertura final y limitaciones).
- `results/rp_<id>-normal.json`, `results/rp_<id>-purchase-*.json` (rondas por juego).
- `results/ruby-events.jsonl` (eventos de compras Ruby).
- `results/evidence-manifest.json` (evidencia saneada y código; no incluye `private/`).
