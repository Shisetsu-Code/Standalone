#[tokio::main]
async fn main() -> std::process::ExitCode {
    game_runner::portable::entry(
        "gamesglobal",
        include_bytes!("../../bindings/gamesglobal-inventory.json"),
    )
    .await
}
