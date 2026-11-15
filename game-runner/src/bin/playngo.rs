#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "playngo",
        include_bytes!("../../../docs/recolector/inventario/playngo.json"),
    )
    .await
}
