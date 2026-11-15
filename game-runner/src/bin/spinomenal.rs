#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "spinomenal",
        include_bytes!("../../../docs/recolector/inventario/spinomenal.json"),
    )
    .await
}
