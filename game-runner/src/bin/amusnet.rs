#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "amusnet",
        include_bytes!("../../../docs/recolector/inventario/amusnet.json"),
    )
    .await
}
