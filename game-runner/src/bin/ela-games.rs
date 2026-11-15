#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "ela-games",
        include_bytes!("../../../docs/recolector/inventario/ela-games.json"),
    )
    .await
}
