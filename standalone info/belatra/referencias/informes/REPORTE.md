# Belatra: reporte de lo verificado (demo ficticia)

Alcance: solo lo que está verificado y lo que está retenido. No incluye payloads ni tokens: esos viven en `provider-work/belatra-chat4/private/` y requieren saneo antes de cualquier entrega.

## 1. Estado
- Estado de la suite: `realizable_first_pass_audited_original_incidents_unresolved`. **No está completo.**
- Catálogo: 117 slots de juego.
- Tirada normal verificada: 111 de 117.
  - 107 sin pendientes.
  - 4 con compras retenidas (Brother CrossBolt, Penalty Blast, Yo-ho-ho 2048, Cyber Gypsies).
- Retenidos sin tirada normal verificada: 6 juegos (Cops vs Robs, Slattors Battle, Fortune Mummy, New York, Green Grocery, The Smart Rabbit). Causa: HTTP 500 al entrar o al leer estado.
- Excluidos (no son slots): 9 (Crash, Sic Bo, Golden Plinko y otros). Lista en `results/excluded-games.json`.
- Cobertura de ramas completa: en ningún juego (`full_branch_coverage: false` en los 117).

## 2. Regla de seguridad
Las transacciones inciertas (HTTP 500 en cierre, o lecturas 200 que no resuelven) están marcadas `no repetir`. Repetirlas puede duplicar un movimiento de saldo. Las compras de `vampire` (PURCHASE_0 y PURCHASE_1) quedaron bloqueadas por una ronda original sin conciliar.

## 3. Archivos
- `belatra-juegos.csv`: una fila por juego (117 + 9 excluidos), con estado, modos verificados, modos pendientes y motivo de retención.
- Fuentes (no copiadas aquí):
  - `demo-dashboard/belatra/summary.json` (estado por juego).
  - `provider-work/belatra-chat4/results/` (`catalogue.json`, `final-root-reaudit.json`, `excluded-games.json`, `captured-round-audit.json`).
  - `provider-work/belatra-chat4/code/` (scripts del transporte HTTP, `run_http_case.cjs`, `native.py`, `http_campaign.py`).

## 4. Endpoints observados en el código
- Sitio público: `https://belatragames.com`.
- Lanzamiento demo: `https://demo.bltrm.com/belatra/demo?game=<game>&language=es`.

No extraje aquí el cuerpo de las solicitudes de juego (acciones, payloads, cierre de ronda). Eso está en `provider-work/belatra-chat4/private/` y hay que revisarlo antes de incluirlo.

## 5. Método (según el código)
- Transporte HTTP: `code/browser_http_transport.cjs`.
- Caso de prueba: `code/run_http_case.cjs`, con guardas de retención en `hold_guard.cjs` y `bound_recovery_gate.cjs`.
- Modelo nativo: `code/native.py` y `native_crypto.cjs`.
- Campaña: `code/http_campaign.py`.

## 6. Limitaciones
- 6 juegos sin tirada normal verificada y 4 con compras retenidas.
- Las compras pendientes no se repiten sin una conciliación oficial previa.
- No se verificaron todas las ramas de bonos.
- La última verificación de lanzamiento del brand devolvió HTTP 403 (`collection-coverage.json`).
