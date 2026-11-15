#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "nolimit",
        include_bytes!("../../../docs/recolector/inventario/nolimit.json"),
    )
    .await
}
