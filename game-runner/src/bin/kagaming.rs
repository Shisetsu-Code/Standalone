#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "kagaming",
        include_bytes!("../../../docs/recolector/inventario/kagaming.json"),
    )
    .await
}
