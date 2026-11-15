#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "elk",
        include_bytes!("../../../docs/recolector/inventario/elk.json"),
    )
    .await
}
