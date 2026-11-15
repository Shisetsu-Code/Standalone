#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "1spin4win",
        include_bytes!("../../../docs/recolector/inventario/1spin4win.json"),
    )
    .await
}
