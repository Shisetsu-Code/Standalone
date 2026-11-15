# Relevo de Playtech y publicación de la suite

Estado del 1 de noviembre de 2026. El usuario pidió documentar y actualizar el repositorio para que otro chat pueda retomar. Este paso no ejecuta nuevas rondas ni admite candidatos. Los tres trabajadores dejaron checkpoints estables y quedaron en standby.

## Lectura inicial

1. `demo-dashboard/docs/relay-qa/ESTADO-2026-11-01.md` y `PROMPT-CONTINUIDAD.md`.
2. El final de `provider-work/playtech-root/CONTINUITY.md`.
3. `docs/superpowers/plans/2026-10-31-ngm-family-loader.md`.
4. `provider-work/coordination/resume-checkpoint-2026-11-01.json` y sus huellas antes de reutilizar un resultado.

En esta PC la suite vive en `C:/Users/Shisetsu/Documents/ChatGPT/Final`. Su raíz no tiene Git. `evidencia-backup-publish/` es el checkout que se publica en `Shisetsu-Code/Evidencia`. El repositorio contiene informes y código seleccionados; fuentes nativas, perfiles, fixtures y sesiones privadas permanecen locales.

## Estado que no hay que reconstruir

- Dashboard de 14 proveedores, con Peter & Sons incorporado y los otros trece conservados.
- Playtech NGM: 85 NORMAL locales; 41 cotización y 17 reproducción; 28 slots sin fuente/manifiesto completo. Quedan 86 slots por habilitar NORMAL. Bonos, compras y ciclos se miden aparte.
- Registro SHA256 `ef5828a70f72e0ce05e1477dc297fa0296692904d9ebd49a8ee92364a7f94d7f`, 143 perfiles y 92 trabajos conservados.
- ASHAMW está admitido y ejecutado una sola vez. Cualquier mensaje antiguo de un trabajador que diga pendiente está desactualizado: mandan el registro, la revisión Root y los diarios.
- GPAS conserva el 403 y las raíces abiertas. No reenviar operaciones ni evadir el bloqueo.
- Chrome visible en standby; no headless. No recrear la automatización horaria desactivada.

## Próximo trabajo de implementación

| Prioridad | Trabajo | Punto de entrada | Condición |
|---|---|---|---|
| 1 | Revisar SAMZ V3 | `reviews/ngm-samz-production-host-fixture-fix-v3.json` | El host V2 falló antes de cualquier original; perfil anterior restaurado. V3 no está admitido |
| 2 | Revisar EPA | `reviews/ngm-sourceonly-epa-native-normal-inventory-candidate.json` | Candidato con ocho suites y oráculo propio, sin admisión ni original |
| 3 | Completar AOGMT | `reviews/ngm-sourceonly-aogmt-work-checkpoint.json` | WIP con cap propio; no copiar EPA ni declarar listo |
| 4 | Implementar FRTLGSK | `reviews/ngm-frtlgsk-native-normal-static-checkpoint.json` | Solo checkpoint estático, no adaptador NORMAL nuevo |
| 5 | Completar JDLO | `reviews/ngm-jdlo-source-only-handoff-checkpoint.json` | WIP; falta prueba del readset y negativos |

Los agentes anteriores ya entregaron; sus IDs no son un requisito de reanudación. Se pueden repartir carpetas independientes a trabajadores nuevos cuando se retome la implementación autorizada. El coordinador integra y es el único escritor del registro y del dashboard. Ningún trabajador ejecuta el caso original ni modifica otro proveedor.

## Comprobaciones locales antes de continuar

```powershell
python -B -m unittest discover -s playtech-private-root/ngm-families -p "test_audit*.py"
python -B playtech-private-root/ngm-families/audit_registered_profiles.py --incremental
```

La segunda usa insumos privados y reproduce fixtures guardadas, sin generar resultados nuevos ni tráfico remoto. El clon del repo no contiene los insumos para correrla: documentar esa falta y volver a la PC original. No arrancar `run_registered_profiles.py` para una comprobación de documentación o de publicación.

Para admitir un candidato: verificar pins propios, cotización y fixture mediante `profile-worker.cjs`/loader común y controles del flujo nativo. Para un caso nuevo autorizado, primero `matching_prior`, intents y resultados históricos; fsync de intención antes de sortear; un solo intento, retención de crudos y ningún reintento de una fase incierta. Sin `canary_parameters` automático. Una fuente nueva no invalida ni vuelve a ejecutar silenciosamente un caso antiguo.

## Publicación y coordinación

Usar `provider-work/coordination/publication.lock`. No borrar un lock sin revisar dueño y proceso. `playtech-private-root/ngm-families/publish_summary.py` y `playtech-private-root/publish_reports.py` publican informes; el wrapper del coordinador mantiene el lock durante ambos. No anidar un lock alrededor de un publicador que ya lo adquiere.

Peter & Sons: `reviews/publish-peterandsons-dashboard.py` valida la entrega Root y publica metadatos saneados. `reviews/audit-peterandsons-chat4-delivery.py` revisa solo archivos guardados; no ejecuta el generador ni cambia los archivos del otro chat. La página Inks muestra siete operaciones posteriores completadas y las incidencias históricas separadas. No decirle al usuario que deba completar su sesión manual.

Un servidor para leer los informes se inicia solo si no existe el servicio esperado:

```powershell
python -m http.server 8787 --bind 127.0.0.1 --directory demo-dashboard
```

Verificar `http://127.0.0.1:8787/providers.html` y el JSON de cada proveedor. Documentación o respaldo nunca justifican una apuesta nueva. Conservar los cuatro informes NetEnt por sus hashes congelados.
