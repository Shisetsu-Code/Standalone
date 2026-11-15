#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "irondog",
        include_bytes!("../../../docs/recolector/inventario/irondog.json"),
    )
    .await
}
