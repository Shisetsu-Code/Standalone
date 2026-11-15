#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "hardfire-kalamba",
        include_bytes!("../../../docs/recolector/inventario/hardfire-kalamba.json"),
    )
    .await
}
