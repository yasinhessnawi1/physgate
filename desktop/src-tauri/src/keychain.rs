//! Credentials, kept in the macOS Keychain and nowhere else.
//!
//! The shell writes a credential straight from where it arrives (the sign-in's output, or
//! the key field) into the Keychain. It never writes one to a file, a log or the settings,
//! and no command hands one back to a page. Each item is a generic password under the
//! service `physgate`, with the account named after the variable a run reads it from, so
//! the line that hands it to a run is obvious.

use security_framework::item::{ItemClass, ItemSearchOptions, Limit};
use security_framework::passwords;
use serde::{Deserialize, Serialize};

/// The two credentials the harness can run on today.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Secret {
    /// The long-lived token `claude setup-token` prints, for runs with `auth: subscription`.
    SubscriptionToken,
    /// An Anthropic API key, for runs with `auth: api_key`.
    ApiKey,
}

impl Secret {
    /// The Keychain account, which is also the variable a run reads.
    pub fn account(self) -> &'static str {
        match self {
            Self::SubscriptionToken => "CLAUDE_CODE_OAUTH_TOKEN",
            Self::ApiKey => "ANTHROPIC_API_KEY",
        }
    }

    /// Whether `value` has the shape of this credential. It says nothing of whether it works.
    pub fn plausible(self, value: &str) -> bool {
        let prefix = match self {
            Self::SubscriptionToken => "sk-ant-oat",
            Self::ApiKey => "sk-ant-api",
        };
        value.starts_with(prefix)
            && value.len() >= 40
            && value
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    }
}

/// The Keychain service: `physgate`, or `PHYSGATE_DESKTOP_KEYCHAIN_SERVICE` for a trial run
/// that must not touch the real items.
pub fn service() -> String {
    std::env::var("PHYSGATE_DESKTOP_KEYCHAIN_SERVICE").unwrap_or_else(|_| "physgate".into())
}

/// Keep `value` as `secret`, replacing any earlier one.
pub fn store(secret: Secret, value: &str) -> Result<(), String> {
    if !secret.plausible(value) {
        return Err(format!(
            "that does not look like a {}",
            match secret {
                Secret::SubscriptionToken => "Claude Code token",
                Secret::ApiKey => "Claude API key",
            }
        ));
    }
    passwords::set_generic_password(&service(), secret.account(), value.as_bytes())
        .map_err(|e| format!("the Keychain refused it: {e}"))
}

/// Whether a credential is kept, asked without reading it.
pub fn is_stored(secret: Secret) -> bool {
    ItemSearchOptions::new()
        .class(ItemClass::generic_password())
        .service(&service())
        .account(secret.account())
        .load_attributes(true)
        .limit(Limit::Max(1))
        .search()
        .is_ok_and(|found| !found.is_empty())
}

/// The credential itself, for the one request the operator may ask for. Never logged.
pub fn read(secret: Secret) -> Result<String, String> {
    let bytes = passwords::get_generic_password(&service(), secret.account())
        .map_err(|_| "no credential is kept".to_string())?;
    String::from_utf8(bytes).map_err(|_| "the kept credential is not text".to_string())
}

/// Remove a credential; removing one that is not there is not an error.
pub fn forget(secret: Secret) {
    let _ = passwords::delete_generic_password(&service(), secret.account());
}

/// The line that puts a credential into a Terminal session for a run. It names the item;
/// it holds no secret, so it can be shown and copied.
pub fn handover_line(secret: Secret) -> String {
    format!(
        "export {account}=\"$(security find-generic-password -s {service} -a {account} -w)\"",
        account = secret.account(),
        service = service()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn credentials_are_recognised_by_shape_only() {
        let token = format!("sk-ant-oat01-{}", "a".repeat(40));
        let key = format!("sk-ant-api03-{}", "b".repeat(40));
        assert!(Secret::SubscriptionToken.plausible(&token));
        assert!(
            !Secret::SubscriptionToken.plausible(&key),
            "a key is not a token"
        );
        assert!(Secret::ApiKey.plausible(&key));
        assert!(!Secret::ApiKey.plausible("sk-ant-api03-short"));
        assert!(!Secret::ApiKey.plausible(&format!("{key} trailing")));
        assert!(!Secret::ApiKey.plausible(&format!("{key}\n")));
    }

    #[test]
    fn the_handover_line_names_the_item_and_holds_no_secret() {
        let line = handover_line(Secret::SubscriptionToken);
        assert!(
            line.starts_with("export CLAUDE_CODE_OAUTH_TOKEN=\"$(security find-generic-password")
        );
        assert!(line.contains("-a CLAUDE_CODE_OAUTH_TOKEN -w"));
        assert!(!line.contains("sk-ant-"));
    }

    #[test]
    fn a_credential_goes_into_the_keychain_and_out_again() {
        // A service of its own, removed at the end, so the real items are never touched.
        std::env::set_var(
            "PHYSGATE_DESKTOP_KEYCHAIN_SERVICE",
            format!("physgate-desktop-test-{}", std::process::id()),
        );
        let key = format!("sk-ant-api03-test-{}", "c".repeat(40));
        forget(Secret::ApiKey);
        assert!(!is_stored(Secret::ApiKey));
        assert!(store(Secret::ApiKey, "not a key").is_err());
        assert!(!is_stored(Secret::ApiKey), "a refused value is not kept");
        store(Secret::ApiKey, &key).unwrap();
        assert!(is_stored(Secret::ApiKey));
        assert_eq!(read(Secret::ApiKey).unwrap(), key);
        forget(Secret::ApiKey);
        assert!(!is_stored(Secret::ApiKey));
    }
}
