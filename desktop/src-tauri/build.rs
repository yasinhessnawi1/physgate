fn main() {
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
