fn main() {
    // `published`: set only for the build the build script installs and publishes (the
    // `published` feature, with no trial feature). Every other build (cargo build or run,
    // tauri dev, a release built by hand, a trial build) is a trial build: the trial
    // Keychain service, a trial folder of its own, and the trial identifier.
    println!("cargo::rustc-check-cfg=cfg(published)");
    let published = std::env::var_os("CARGO_FEATURE_PUBLISHED").is_some()
        && std::env::var_os("CARGO_FEATURE_VERIFICATION").is_none();
    if published {
        println!("cargo::rustc-cfg=published");
    }
    // The app's own commands, each given an `allow-` permission that a capability must name
    // before any page can call it. Only the onboarding capability names them, and only for
    // the app's own pages.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "onboarding_state",
            "claude_code_detect",
            "claude_code_install",
            "sign_in_start",
            "sign_in_status",
            "sign_in_return",
            "sign_in_cancel",
            "sign_in_in_terminal",
            "store_secret",
            "forget_secret",
            "test_api_key",
            "choose_engine",
            "device_report",
            "intro_seen",
            "finish_onboarding",
        ]),
    ))
    .expect("the app's build configuration is valid");
}
