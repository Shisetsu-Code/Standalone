#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "thunderspin",
        include_bytes!("../../../docs/recolector/inventario/thunderspin.json"),
    )
    .await
}
