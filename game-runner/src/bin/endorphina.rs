#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "endorphina",
        include_bytes!("../../../docs/recolector/inventario/endorphina.json"),
    )
    .await
}
