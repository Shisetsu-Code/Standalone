#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "netent",
        include_bytes!("../../../docs/recolector/inventario/netent.json"),
    )
    .await
}
