#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "microgaming",
        include_bytes!("../../../docs/recolector/inventario/microgaming.json"),
    )
    .await
}
