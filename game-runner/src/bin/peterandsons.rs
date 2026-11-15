#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "peterandsons",
        include_bytes!("../../../docs/recolector/inventario/peterandsons.json"),
    )
    .await
}
