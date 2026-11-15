# Arranque directo de Densho en HardFire

Se verificó el 12 de noviembre de 2026 en una pestaña aislada. La página del juego se abrió directamente, sin pasar por el catálogo en esa pestaña.

El launcher público de Hacksaw consulta `GET https://static-live.hacksawgaming.com/1348/version.json` y construye `https://static-live.hacksawgaming.com/1348/<version>/index.html`. La versión observada fue `1.27.0`. Usar la versión anunciada por el proveedor y validar el formato antes de construir la ruta.

| Parámetro del iframe | Valor observado |
|---|---|
| `gameid` | `1348` |
| `partner` | `demo` |
| `mode` | `2` |
| `token` | `123131`, literal del launcher público |
| `channel` | `desktop` |
| `language` | `en` |
| `currency` | `EUR` |
| `lobbyurl` | `https://www.hacksawgaming.com` |
| `env` | `https://rgs-demo.hacksawgaming.com/api` |
| `realmoneyenv` | `https://` |

El `POST /api/play/authenticate` respondió HTTP 200 con `statusCode: 0`, cuenta `Demo`, sesión recién emitida y `roundId: 0`. El literal público del iframe y el identificador que emite la autenticación son campos distintos. Usar la identidad recién emitida en el mismo contexto de navegador.

Evidencia privada local en `Downloads/HardFire-HARs/static-live.hacksawgaming.com-2026-11-12T11-54-25-904Z.har`, SHA-256 `0DB72B5A0B3330FEDE57FFEA5AE6B24C8FD752A40F899561415B02E27EDCED7D`. Entrada 4 de `log.entries` para la autenticación, con índice desde cero. En esa captura, `partnerSettings` quedó con estado HAR 0. La autenticación demuestra el arranque. No hay solicitudes a `/bet`.

Los mensajes y las reglas de conciliación están en [Endpoints y payloads](ENDPOINTS-HACKSAW.md) y [rondas históricas](hacksaw-rondas.csv). El arranque directo está probado para Densho. Para el recolector queda pendiente conectar el transporte a ese contexto y verificar una ronda normal de control con cierre y saldo.
