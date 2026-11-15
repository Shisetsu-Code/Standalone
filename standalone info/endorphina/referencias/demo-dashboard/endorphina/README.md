# Endorphina · Demos públicas

Dashboard por proveedor: http://127.0.0.1:8787/providers.html

Catálogo: http://127.0.0.1:8787/endorphina/

Primer lote: http://127.0.0.1:8787/endorphina/batches/1-100/

Segundo lote: http://127.0.0.1:8787/endorphina/batches/101-200/

Último lote: http://127.0.0.1:8787/endorphina/batches/201-240/

Los datos de Endorphina se guardan dentro de esta carpeta. Los informes y
registros de Pragmatic mantienen sus rutas anteriores y su propia navegación.

El adaptador Python usa el protocolo JSON WebSocket nativo de la demo oficial.
Abre sesiones nuevas desde los enlaces del catálogo de endorphina.com. No usa
cuentas de casino ni reproduce sesiones del HAR. Este adaptador de pruebas es
independiente del relay HTTP de Pragmatic del puerto 8788; no implementa la
simulación proporcional de ese relay ni sirve un cliente Endorphina local.

Los HAR aportaron 216 títulos y dos muestras de cliente. Se añadieron las dos
páginas públicas faltantes para obtener 240 títulos únicos. Las primeras 100
entradas se conservan en batches/1-100/catalog.json, con orden y fuentes.

Cada ronda tiene un registro de mensajes en batches/1-100/traces. El detalle
round.html muestra los pasos por separado: tiradas gratis, cascadas, elecciones,
juego de riesgo y cierre. Los intentos de diagnóstico se conservan en attempts;
no cuentan como cobertura correcta por sí solos.

Las firmas temporales de las sesiones se guardan fuera de la carpeta servida por
HTTP, en ../endorphina-private respecto del directorio demo-dashboard.

Comandos desde demo-dashboard:

```powershell
python endorphina_run.py --phase inventory
python endorphina_config.py
python endorphina_rounds.py --phase normal
python endorphina_rounds.py --phase purchases --limit 500
python endorphina_risk.py
python endorphina_branches.py
python endorphina_audit.py
python provider_reports.py
```

`--fresh-incomplete` archiva un intento incompleto antes de iniciar una compra
ficticia nueva; conserva las entradas ya completadas. No reintenta una solicitud
de apuesta dentro del transporte. Una sesión desconectada puede dejar de
admitir reapertura.

El alcance cubre los controles publicados y las elecciones internas observadas,
con cierre y saldo verificados a partir de mensajes nativos. No certifica todas
las animaciones ni todos los resultados aleatorios posibles.

Para seleccionar otro lote sin modificar los anteriores:

```powershell
$env:ENDORPHINA_BATCH="101-200"
python endorphina_run.py --with-normal --workers 6
```

El visor acepta `?batch=101-200&case=...`. Las demos sin destino en el lanzador oficial se documentan con sus páginas originales y no cuentan como tiradas probadas.

Para los últimos 40 títulos, usar `ENDORPHINA_BATCH="201-240"`. Las respuestas
oficiales que indican indisponibilidad temporal también se conservan como
evidencia y se muestran como excepciones, sin contarlas como rondas aprobadas.
Los selectores antiguos de Durga y Chunjie se identifican por los valores de
los eventos `FREEGAMES_SELECT` publicados en la configuración de sus botones.
