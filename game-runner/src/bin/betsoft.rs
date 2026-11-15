#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "betsoft",
        include_bytes!("../../../docs/recolector/inventario/betsoft.json"),
    )
    .await
}
