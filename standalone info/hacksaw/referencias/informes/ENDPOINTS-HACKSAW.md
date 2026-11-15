# Hacksaw Gaming: endpoints y payloads (demo pública)

Fuente: `evidencia-backup-publish/demo-dashboard/hacksaw_client.py`, `hacksaw_contracts.py` y `hacksaw_protocol.py`. Sin tokens ni sesiones: el token de demo es el literal `demo` y se envía en la autenticación pública.

## Endpoints
- Assets y versión del juego (GET): `https://static-live.hacksawgaming.com/<gameId>/version.json`.
- API de juego (POST JSON): `https://rgs-demo.hacksawgaming.com/api/play/<método>`.
  - `partnerSettings`
  - `authenticate`
  - `bet`
- Catálogo (GET, HTML): `https://www.hacksawgaming.com/games/<slug>`.

Solo se permiten estos tres métodos. El cliente rechaza cualquier otro (`unsupported_demo_method`).

## Flujo
1. **Versión:** GET `version.json` del juego. La versión debe coincidir con `^[0-9]+(\.[0-9]+){1,3}$`.
2. **partnerSettings** (POST):
   ```json
   {"partner": "demo", "currency": "EUR", "gameId": <int>, "usePartnerCurrency": true}
   ```
3. **authenticate** (POST):
   ```json
   {"seq": <n>, "partner": "demo", "gameId": <int>, "gameVersion": "<version>",
    "currency": "EUR", "languageCode": "en-us", "mode": 2, "branding": "default",
    "channel": 1, "userAgent": "Mozilla/5.0", "token": "demo", "currencyMultiplier": 1}
   ```
   La respuesta debe ser una demo nueva: `name: "Demo"`, `roundStatus` vacío, `roundId` `0`. Devuelve `sessionUuid`, `accountBalance` (EUR), `betLevels` (usa la apuesta mínima) y `bonusGames`.
4. **bet, tirada normal** (POST):
   ```json
   {"seq": <n>, "sessionUuid": "<uuid>", "bets": [{"betAmount": "<apuesta mínima>"}],
    "offerId": null, "promotionId": null, "autoplay": false}
   ```
5. **bet, compra de bono** (POST): igual que la tirada normal, con `buyBonus` en la apuesta. El `bonusGameId` tiene que estar en `bonusGames` de la autenticación; si no, se rechaza (`unpublished_bonus_id`).
   ```json
   {"betAmount": "<apuesta>", "buyBonus": "<bonusGameId>"}
   ```
6. **bet, continuación** (POST):
   ```json
   {"seq": <n>, "sessionUuid": "<uuid>", "roundId": "<roundId>",
    "continueInstructions": {"action": "<acción>"}}
   ```
   La acción es una de `possibleActions` de la ronda. Si la ronda tiene `possibleActions`, la acción debe estar en esa lista (`unoffered_native_action`).

## Cierre de ronda
Una ronda está cerrada cuando `status == "completed"` y no hay `possibleActions` (`round_not_closed` si no).

## Errores
- `statusCode != 0` en la respuesta: se registra `provider_error:<código>:<mensaje>`.
- Una solicitud incierta (sin respuesta) no se reenvía.

## Variantes con volatilidad (Beam Boys)
- `customData: {"volatility": "low" | "extreme"}` se agrega a la apuesta.
- Tirada normal: `low`. Variante base: `extreme`.
- Los modos publicados por bono se toman del identificador `bonusGameId` (sufijo `_low` o `_extreme`). Cualquier otro valor se rechaza (`unpublished_or_conflicting_volatility`).

## Cobertura de la corrida
- 142 juegos, 142 tiradas normales completadas, 602 compras completadas, 778 rondas registradas (ver `REPORTE.md`).
- Los scripts de corrida (`hacksaw_run.py`, `hacksaw_audit.py`, `hacksaw_reports.py`) están en `evidencia-backup-publish/demo-dashboard/`.
