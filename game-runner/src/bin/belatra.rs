#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "belatra",
        include_bytes!("../../../docs/recolector/inventario/belatra.json"),
    )
    .await
}
