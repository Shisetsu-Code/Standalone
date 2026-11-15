#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "kendoo",
        include_bytes!("../../../docs/recolector/inventario/kendoo.json"),
    )
    .await
}
