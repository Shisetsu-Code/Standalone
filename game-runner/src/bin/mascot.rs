#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "mascot",
        include_bytes!("../../../docs/recolector/inventario/mascot.json"),
    )
    .await
}
