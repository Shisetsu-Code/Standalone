#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "pragmatic",
        include_bytes!("../../../docs/recolector/inventario/pragmatic.json"),
    )
    .await
}
