# ELK Studios · demos oficiales

Catálogo completo: **159/159 fichas**, correspondientes a **157 demos distintos**. Ambos lotes están auditados y no tienen casos pendientes.

| Lote | Fichas con normal | Pruebas verificadas | Compras/modos | RESULT individuales |
|---|---:|---:|---:|---:|
| 1–100 | 100 | 666 | 555 | 5.537 |
| 101–159 | 59 | 137 | 78 | 1.153 |
| Total | 159 | 803 | 633 | 6.690 |

Los casos incluyen 170 normales por variante. Las tres fichas de Pirots 4 comparten el mismo demo y selector; su relación se conserva en el catálogo.

## Pirots 5 · Boss

Se completaron DEF y X01–X05 después de reunir los nueve tokens mediante el progreso nativo del demo. La campaña seleccionada contiene **330 compras de progresión X04 y seis pruebas Boss**, con 8.399 RESULT conservados. Las compras de progresión se muestran aparte y no inflan las 803 pruebas del catálogo.

Campaña: `61e0737f933b4da1878a664c7e6680a0`. Temple terminó sus tokens en la ronda 103, Ship en la 266 y Nest en la 330. Las seis entradas Boss son las rondas 331–336; las tres máscaras valían siete antes de cada una. Los 53 RESULT de esas seis pruebas se incorporaron al primer lote.

El auditor reconstruye toda la campaña desde una inicialización fresca y comprueba cada coste, premio, saldo incremental, acumulado de sesión, identificador de ronda, RESULT y estado de tokens. No se alteraron estados ni se usaron resultados forzados.

Los seis fallos originales y el resumen anterior están archivados en `batches/1-100/attempts/`. El snapshot original de 677 archivos del segundo lote se conserva como `prior-providers-proof-before-boss-*.json`; su actualización documentada cambia exactamente siete archivos: las seis trazas Boss y el resumen de rondas del primer lote. Los otros 670 hashes coinciden con el snapshot original.

## Protocolo y reproducción

Solo se usan los hosts oficiales de demo y saldo EUR ficticio. Los HAR sirven como evidencia del catálogo/protocolo, no como credenciales. El cliente conserva las renovaciones de sesión, usa un ID distinto por solicitud y respeta el intervalo mínimo publicado. No reintenta automáticamente compras inciertas. Las claves de campañas nuevas se guardan únicamente fuera del servidor HTTP, en `../elk-private/`, para conservar el progreso; las evidencias públicas están anonimizadas.

Los formatos ECF 1, 2 y 3 y XML clásico se validan con sus campos nativos. El total acumulado no se suma como si fueran premios independientes. Cada RESULT de cascada o bonus tiene su propio registro. Los contadores pendientes y formatos desconocidos impiden certificar el cierre.

Desde la raíz del proyecto, sin generar solicitudes al proveedor:

```powershell
python elk_boss_audit.py 61e0737f933b4da1878a664c7e6680a0
python elk_reconcile.py --batch 1-100
python elk_audit.py --batch 1-100
python elk_audit.py --batch 101-159
python elk_reports.py --batch 1-100
python elk_reports.py --batch 101-159
python -m unittest discover -q
```

Dashboard: http://127.0.0.1:8787/providers.html

Recorrido Boss: http://127.0.0.1:8787/elk/boss.html
