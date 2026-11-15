# Hacksaw Gaming y Playson: reporte (demo pública)

Alcance: demos públicas, saldo ficticio. Sin tokens, sesiones ni HAR en este reporte.

## 1. Hacksaw Gaming: completo

Estado: catálogo completo (142 de 142), todas las rondas `completed`, conciliación de saldo `match` en todas.

| Concepto | Valor |
|---|---|
| Juegos | 142 |
| Tiradas normales | 142 (todas `completed`, `wallet_check: match`) |
| Compras (bonos y activadores) | 602 (417 en lote 1-100, 185 en lote 101-142) |
| Identificadores de bono/activador publicados | 601 |
| Modificadores `mod_` (publicados por separado) | 313 |
| Elecciones internas observadas y verificadas | 54 (46 + 8) |
| Rondas de elección adicionales | 34 (30 + 4) |
| Rondas registradas en auditoría | 778 (547 + 231) |

Auditorías: `batches/1-100/audit.json` y `batches/101-142/audit.json` ambas `passed: true`, sin incidencias. `catalog-coverage.json`: `all_catalog_games_completed: true`.

**Nota de conteo:** `hacksaw-rondas.csv` tiene 744 filas. Las 34 rondas de elección adicionales (778 − 744) no están en `rounds.json` ni `purchases.json`; están en los `choices.json`. No las incluí.

### Archivos
- `hacksaw-rondas.csv`: 744 filas (142 normales y 602 compras) con juego, tipo, caso, identificador de bono, multiplicador publicado, costo, premio, saldo antes y después, conciliación y round_id.
- Fuente: `evidencia-backup-publish/demo-dashboard/hacksaw/` (`catalog.json`, `batches/*/rounds.json`, `batches/*/purchases.json`, `batches/*/choices.json`, `batches/*/audit.json`, `catalog-coverage.json`, `README.md`).

### Endpoints y método (según `README.md`)
- Dashboard de la suite: `http://127.0.0.1:8787/hacksaw/` (local).
- API pública de demostración de Hacksaw con `partner=demo` y `mode=2`. Abre sesiones nuevas y usa la apuesta mínima publicada por cada sesión. No usa cuentas ni sesiones capturadas.
- Comandos:
  ```bash
  python hacksaw_run.py --batch 1-100 --phase inventory --workers 4
  python hacksaw_run.py --batch 1-100 --phase purchases --workers 4
  python hacksaw_run.py --batch 1-100 --phase choices --workers 4
  python hacksaw_audit.py --batch 1-100
  python hacksaw_reports.py --batch 1-100
  ```
  (Ejecutar desde `demo-dashboard`. Los scripts `hacksaw_run.py`, `hacksaw_audit.py` y `hacksaw_reports.py` no están en esta copia; hay que tomarlos de la carpeta original antes de repetir.)
- Regla: se guarda un registro antes de enviar cada entrada; una solicitud incierta no se reenvía.
- Beam Boys usa `customData.volatility` (`low` para la tirada normal y `extreme` como variante base).

### Limitaciones
- Verifica las opciones de los menús observados; no certifica todos los resultados aleatorios ni las animaciones.
- Los importes se guardan en unidades nativas de la API, sin reescalar.

## 2. Playson: no hay tiradas verificadas

Estado: no completo y sin tiradas cerradas en la evidencia revisada.

- Cobertura del adaptador (`bet-collector/collection-coverage.json`): 114 juegos de catálogo, 114 ejecutables, 0 bloqueados, 242 modos nativos. Eso es cobertura del adaptador, no tiradas verificadas.
- Última muestra aleatoria (`bet-collector/reports/random-five-20261111T085916Z.md`): 5 juegos de Playson, **todos bloqueados** con `remote_http_403`:
  - 4 Chili Pots: Hold and Win
  - Royal Joker: Hold and Win
  - 4 Scarab Coins: Hold and Win
  - Hot Coins: Hold and Win
  - Luxor Gold: Hold and Win
- Hay una carpeta `playson-private-root/` (1.358 archivos, incluye capturas y "resolved-launches") y `bet-collection-private/attempts/` con intentos de Playson. Es material privado: no lo revisé ni lo incluí. Antes de cualquier entrega hay que sanearlo.

Para Playson falta:
1. Determinar si el 403 es un bloqueo temporal del lanzador o un bloqueo de la demo.
2. Un resumen de tiradas verificadas (que hoy no existe).

## 3. Próximos pasos
- Hacksaw: el reporte está completo. Falta copiar los scripts `hacksaw_*.py` a esta carpeta si se quiere replicar sin la carpeta original.
- Playson: pedirle a la sesión [escala-playson](#local_bfc35490-6274-4931-8b9a-c8f2cac50ce3) su estado, o repetir la muestra cuando el lanzador responda.
