# Ejecutar en GitHub Actions

En **Actions → Rust demo runner**, el workflow compila el ejecutable en Linux y Windows, corre las pruebas locales y valida los datos del dashboard. El artefacto incluye el ejecutable, los inventarios, los bindings publicados y la copia de consulta del dashboard. Conservá la estructura del artefacto al extraerlo.

En **Actions → Prueba manual de demos → Run workflow**, seleccioná main. El workflow prepara un informe para los 35 IDs de inventario y prueba una normal en cada proveedor que tenga un objetivo y una configuración revisados. Las respuestas y rondas verificadas se exportan a un artefacto saneado. El diario privado se cifra con el certificado público del repositorio. La clave privada correspondiente queda bajo custodia de su titular. Un reintento del mismo run omite el job de demo.

## Alcance

El runner autónomo cubre los protocolos implementados en game-runner. La prueba manual es una muestra de tiradas normales. Las campañas de modalidades específicas usan los comandos plan, check y run descritos en el [manual del runner](../README.md). La automatización de toda la lista del dashboard sigue dependiendo de adaptadores, configuraciones y transportes de la suite local. El [mapa por proveedor](../../docs/recolector/reproduccion/mapa.json) conserva esas referencias y dependencias. El [dashboard de consulta](../../docs/dashboard-recoleccion/README.md) funciona desde los archivos del repo.
### Evidencia de modalidades Playson

`python ci/audit_playson_modes.py ARCHIVO CONTRATOS BINDINGS PLAN SALIDA` revalida los modos omitidos de Playson contra la inicialización TEST, el cliente archivado y el XML privado. Solo agrega una modalidad si coinciden su selector, el coste mínimo, las continuaciones y el cierre del saldo. La salida es un candidato para `bindings/playson.json`. Las solicitudes y los recibos originales permanecen en el historial privado.

`python ci/probe_playson_builds.py CONTRATOS BINDINGS PLAN DIRECTORIO_NUEVO` consulta el lanzador público y sus dos archivos JavaScript. Guarda los hashes y el formato de los selectores, junto con la etapa de cualquier error HTTP. La comprobación no abre una sesión de juego. Un cambio de versión requiere contrastar los selectores y volver a verificar los modos antes de publicar el binding actualizado.

### Recibos NetEnt del protocolo Red Tiger HTTP

`python ci/audit_netent_redtiger.py ARCHIVO CONTRATOS LANZAMIENTOS PLAN SALIDA` comprueba los modos pendientes de esta familia con las capturas archivadas. Vincula el lanzamiento público, la mesa demo, la inicialización, el POST de cada tirada y su recibo. El informe incluye identificadores públicos, precios, moneda y hashes. La ejecución en vivo requiere que el runner implemente el arranque NetEnt para esta familia.
