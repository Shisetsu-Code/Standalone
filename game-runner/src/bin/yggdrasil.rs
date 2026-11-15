#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "yggdrasil",
        include_bytes!("../../../docs/recolector/inventario/yggdrasil.json"),
    )
    .await
}
