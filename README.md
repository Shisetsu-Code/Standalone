# Standalone

## Runner nuevo: captura y WireGuard en paralelo

[capture-runner](capture-runner/README.md) es el runner independiente para una VM Linux, sin interfaz gráfica. Ejecuta un cupo configurable de juegos **por proveedor y por salida WireGuard**, conserva solicitudes/respuestas completas y parciales, y avisa ante eventos nativos desconocidos. Los saldos no determinan si una captura se guarda o si continúa otro juego.

`plan` informa la cobertura ejecutable real de los 35 inventarios; los modos sin un contrato ejecutable completo aparecen explícitamente como pendientes. Ver [puesta en marcha](capture-runner/README.md), [cobertura](capture-runner/docs/COVERAGE.md) y [red WireGuard](capture-runner/docs/WIREGUARD.md).

```bash
cargo build --release --locked --manifest-path capture-runner/Cargo.toml
capture-runner/target/release/capture-runner plan --config capture-runner/examples/direct-explicit.json
```

## Ejecutables anteriores

Ejecutables por proveedor para recopilar rondas de demos públicas con saldo ficticio. El código principal está en [game-runner](game-runner/README.md). BGaming, SmartSoft y Three Oaks usan el [crate de ejecutables adicionales](bet-collector/game-runner/).

## Datos por proveedor

[standalone info](standalone%20info/) contiene 35 carpetas con inventarios, modalidades, configuraciones y evidencia técnica. El [índice](standalone%20info/indice.json) enumera los proveedores. Cada carpeta tiene un manifiesto de archivos con SHA-256.

Las configuraciones usadas al compilar están en [game-runner/bindings](game-runner/bindings/) y [docs/recolector/inventario](docs/recolector/inventario/). La carpeta de datos es una referencia para las integraciones pendientes. Los ejecutables leen sus contratos incorporados, y `--data` selecciona un directorio privado para guardar los recibos localmente.

## Compilar los ejecutables anteriores

Desde la raíz, con Rust 1.99 o posterior:

```powershell
cargo build --locked --release --manifest-path game-runner/Cargo.toml --bins
cargo build --locked --release --manifest-path bet-collector/game-runner/Cargo.toml --bin bgaming-portable --bin smartsoft-portable --bin threeoaks-portable
```

Para compilar las versiones Windows con transporte incorporado de Red Tiger y Spinomenal, prepará el paquete con Python y el módulo `requests` instalados en el equipo de compilación:

```powershell
python game-runner/ci/pack_redtiger_http.py runtime-http.gz
$env:REDTIGER_HTTP_BUNDLE = (Resolve-Path runtime-http.gz).Path
cargo build --locked --release --manifest-path game-runner/Cargo.toml --bin redtiger --features redtiger-bundled-http
cargo build --locked --release --manifest-path game-runner/Cargo.toml --bin spinomenal --features spinomenal-bundled-http
```

Las compilaciones con el transporte incorporado incluyen el runtime en el propio ejecutable. La cobertura y las pruebas en vivo varían por proveedor y modo. Usá `check JUEGO MODO` para validar un caso localmente antes de ejecutar `run`.

Los datos publicados se limitan a documentación técnica y evidencia saneada. Los historiales privados, HAR originales y sesiones quedan en la máquina de trabajo.
