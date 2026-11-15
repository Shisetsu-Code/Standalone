#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "rubyplay",
        include_bytes!("../../../docs/recolector/inventario/rubyplay.json"),
    )
    .await
}
