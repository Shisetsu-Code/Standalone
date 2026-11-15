#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "amigogaming",
        include_bytes!("../../../docs/recolector/inventario/amigogaming.json"),
    )
    .await
}
