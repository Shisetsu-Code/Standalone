#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "playtech",
        include_bytes!("../../../docs/recolector/inventario/playtech.json"),
    )
    .await
}
