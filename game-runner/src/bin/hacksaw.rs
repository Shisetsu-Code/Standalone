#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "hacksaw",
        include_bytes!("../../../docs/recolector/inventario/hacksaw.json"),
    )
    .await
}
