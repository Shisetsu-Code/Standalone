# Verificación de la entrega

Verificado el 15 de noviembre de 2026 en Linux x86_64, con `rustc 1.100.0 (0ef1bc386 2026-11-09)`. La base del repositorio es `749ae8e4ca8e50326cc756fda8efb916c47b0be8`.

## Resultado

| Comprobación | Resultado |
|---|---|
| `cargo fmt --manifest-path capture-runner/Cargo.toml --check` | Correcto |
| `cargo test --offline --locked --manifest-path capture-runner/Cargo.toml` | 182 pruebas de biblioteca y 3 de CLI; ninguna fallida ni ignorada |
| `cargo clippy --offline --locked --manifest-path capture-runner/Cargo.toml --all-targets -- -D warnings` | Correcto, sin advertencias |
| `cargo build --release --offline --locked --manifest-path capture-runner/Cargo.toml` | Correcto |
| Plan del binario release frente a `docs/coverage.json` | Idénticos, byte a byte |

Los comandos se ejecutaron desde la raíz del repositorio. `--offline` usó dependencias previamente descargadas; no es un requisito para la primera compilación en la VM.

El plan final contiene 35 proveedores, 9.874 juegos inventariados y 20.068 modos. Hay 13.841 modos con contrato ejecutable, distribuidos en 6.393 juegos, y 6.227 modos pendientes. [COVERAGE.md](COVERAGE.md) desglosa las cifras y [MISSING-EVIDENCE.md](MISSING-EVIDENCE.md) identifica los contratos ausentes.

## Qué prueban las comprobaciones

Las pruebas de biblioteca y CLI cubren los contratos nativos implementados, selección de modos, cierres y continuaciones conocidas, eventos desconocidos, preservación de respuestas parciales, aislamiento de cookies, límites de concurrencia independientes, cancelación y reanudación sin reenviar intentos inciertos. También ejercitan configuración de 30 salidas, argumentos de administración de WireGuard, propiedad de recursos y rollback mediante comandos simulados. Las pruebas de transporte usan servidores de loopback.

La revisión independiente incluyó los conectores, el supervisor y el manejo de namespaces. Las correcciones derivadas de la revisión están incluidas en los resultados anteriores. Los inventarios y archivos de evidencia existentes permanecen sin cambios; los bindings incorporados tienen procedencia y hashes en [PROVENANCE.md](PROVENANCE.md).

## Límites de esta verificación

No se realizaron solicitudes a proveedores ni se levantaron túneles WireGuard reales. No se ha medido el consumo de la VM con 30 túneles ni con miles de juegos simultáneos. La disponibilidad remota, autenticación demo, handshake de los peers, salida geográfica y capacidad efectiva deben comprobarse en la VM con sus configuraciones. Un modo con contrato ejecutable puede recibir un rechazo remoto o alcanzar un límite de pasos; esos resultados conservan su captura.

## Binario local

SHA-256 de `capture-runner/target/release/capture-runner`:

```text
93df29372bd55f3e0a125c1d975b6809156a63bcd45f04875a97a9e9ad7f7fec
```

Este hash identifica la compilación local, no promete builds reproducibles entre entornos. El ejecutable es x86_64 y enlaza dinámicamente con glibc, libm y libgcc_s de Linux. Para otra arquitectura o distribución, compilar en la VM. El workflow de GitHub Actions compila y adjunta su propio artefacto Linux.
