#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "redtiger",
        include_bytes!("../../../docs/recolector/inventario/redtiger.json"),
    )
    .await
}
