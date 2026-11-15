#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "evoplay",
        include_bytes!("../../../docs/recolector/inventario/evoplay.json"),
    )
    .await
}
