use std::{path::Path, process::Command};
fn run(data: &Path, args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_game-runner"))
        .arg("--data")
        .arg(data)
        .args(args)
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()
        .unwrap()
}
#[test]
fn offline_cli_import_plan_check_and_no_overwrite() {
    let temp = tempfile::tempdir().unwrap();
    let data = temp.path().join("data");
    let imported = run(&data, &["import"]);
    assert!(
        imported.status.success(),
        "{}",
        String::from_utf8_lossy(&imported.stderr)
    );
    let inv: serde_json::Value = serde_json::from_slice(&imported.stdout).unwrap();
    assert_eq!(inv["providers"], 35);
    let path = temp.path().join("plan.json");
    let output = path.to_str().unwrap();
    let args = [
        "plan",
        "--provider",
        "hacksaw",
        "--game",
        "2405",
        "--mode",
        "normal",
        "--samples",
        "1",
        "--output",
        output,
    ];
    let planned = run(&data, &args);
    assert!(
        planned.status.success(),
        "{}",
        String::from_utf8_lossy(&planned.stderr)
    );
    let original = std::fs::read(&path).unwrap();
    let checked = run(&data, &["check", "--plan", output]);
    assert!(
        checked.status.success(),
        "{}",
        String::from_utf8_lossy(&checked.stderr)
    );
    let value: serde_json::Value = serde_json::from_slice(&checked.stdout).unwrap();
    assert_eq!(value["network_requests"], 0);
    assert!(!run(&data, &args).status.success());
    assert_eq!(original, std::fs::read(path).unwrap());
    let status = run(&data, &["status"]);
    assert!(status.status.success());
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&status.stdout).unwrap()["total"],
        0
    );
}

#[test]
fn smoke_all_reports_the_inventory_without_sending_requests_by_default() {
    let temp = tempfile::tempdir().unwrap();
    let data = temp.path().join("data");
    assert!(run(&data, &["import"]).status.success());
    let path = temp.path().join("preflight.json");
    let args = [
        "smoke-all",
        "--campaign",
        "offline-smoke-fixture",
        "--output",
        path.to_str().unwrap(),
    ];
    let output = run(&data, &args);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let bytes = std::fs::read(&path).unwrap();
    let report: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(report["provider_count"], 35);
    assert_eq!(report["ready_provider_count"], 5);
    assert_eq!(report["attempted_provider_count"], 0);
    assert_eq!(report["verified_provider_count"], 0);
    assert_eq!(report["execution_requested"], false);
    assert_eq!(report["all_providers_verified"], false);
    assert_eq!(report["providers"].as_array().unwrap().len(), 35);
    assert!(!run(&data, &args).status.success());
    assert_eq!(std::fs::read(path).unwrap(), bytes);
    let status = run(&data, &["status"]);
    let status: serde_json::Value = serde_json::from_slice(&status.stdout).unwrap();
    assert_eq!(status["total"], 0);
}

#[test]
fn plan_all_retains_every_declared_mode_without_execution() {
    let temp = tempfile::tempdir().unwrap();
    let data = temp.path().join("data");
    assert!(run(&data, &["import"]).status.success());
    let path = temp.path().join("all-modes.json");
    let output = run(
        &data,
        &[
            "plan-all",
            "--provider",
            "hacksaw",
            "--game",
            "2405",
            "--output",
            path.to_str().unwrap(),
        ],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let plan: serde_json::Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    let jobs = plan["jobs"].as_array().unwrap();
    assert!(jobs.len() > 1);
    assert!(jobs.iter().any(|j| j["mode"] == "normal"));
    assert!(jobs.iter().any(|j| j["mode"] != "normal"));
    assert_eq!(
        plan["coverage"]["inventory_mode_count"].as_u64().unwrap(),
        jobs.len() as u64 + plan["coverage"]["omitted_mode_count"].as_u64().unwrap()
    );
    assert!(
        run(&data, &["check", "--plan", path.to_str().unwrap()])
            .status
            .success()
    );
    let coverage = run(&data, &["coverage", "--plan", path.to_str().unwrap()]);
    assert!(coverage.status.success());
    let coverage: serde_json::Value = serde_json::from_slice(&coverage.stdout).unwrap();
    assert_eq!(coverage["verified_samples"], 0);
    assert_eq!(coverage["all_inventory_modes_completed"], false);
    assert!(
        !run(
            &data,
            &[
                "plan-all",
                "--provider",
                "does-not-exist",
                "--output",
                temp.path().join("bad.json").to_str().unwrap()
            ]
        )
        .status
        .success()
    );
}

#[test]
fn portable_hacksaw_contains_its_inventory_and_validates_a_plan() {
    let temp = tempfile::tempdir().unwrap();
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_hacksaw"))
        .current_dir(temp.path())
        .args(["check", "2405", "normal"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["provider"], "hacksaw");
    assert_eq!(result["network_requests"], 0);
}
