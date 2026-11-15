#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "playson",
        include_bytes!("../../../docs/recolector/inventario/playson.json"),
    )
    .await
}
