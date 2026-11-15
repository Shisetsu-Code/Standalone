# Standalone info

Datos técnicos de 35 proveedores. El índice resume las carpetas y sus manifiestos identifican cada archivo por SHA-256.

- inventario.json contiene juegos y modos.
- bindings contiene las configuraciones ya incorporadas en el código de los ejecutables, donde existen.
- evidencia, dashboard y referencias conservan auditorías y fuentes disponibles.
- plan-revisado.json conserva la cobertura y las omisiones del plan del worker común.

El plan común puede depender de módulos locales o de transportes específicos. Los ejecutables actuales usan sus propios contratos incorporados. La opción --data sigue apuntando al historial de ejecución.

La carpeta excluye HAR originales, sesiones activas, cookies, bases privadas y archivos de credenciales.
