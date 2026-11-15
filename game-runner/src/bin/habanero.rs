#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "habanero",
        include_bytes!("../../../docs/recolector/inventario/habanero.json"),
    )
    .await
}
