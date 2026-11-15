#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "egt-digital",
        include_bytes!("../../../docs/recolector/inventario/egt-digital.json"),
    )
    .await
}
