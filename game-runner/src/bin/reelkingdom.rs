#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "reelkingdom",
        include_bytes!("../../../docs/recolector/inventario/reelkingdom.json"),
    )
    .await
}
