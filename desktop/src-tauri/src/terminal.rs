//! What the app runs in a terminal: the scripts it opens in Terminal (Claude Code's installer,
//! and the sign-in fallback), and the sign-in it runs in a pseudo-terminal of its own.
//!
//! **Terminal only.** What is written here runs in a terminal: a Terminal window the person
//! opened with a click, where every line is printed before it runs, or the sign-in's own
//! pseudo-terminal, whose output the page shows filtered. None of it is ever shown on a screen
//! of the app. That is why this one file holds commands, and why the shell's no-command scan
//! leaves it out by name (and checks that it is still here, and still holds them): nothing
//! else can pass that scan by sitting in this file by accident.

/// The Claude Code subcommand that prints a long-lived token for runs.
pub const SIGN_IN: &str = "setup-token";

/// Claude Code's official installer, as its documentation gives it.
pub const INSTALL_COMMAND: &str = "curl -fsSL https://claude.ai/install.sh | bash";

/// The installer: it prints the command, waits for Return, and only then runs it, so the
/// person sees what will run and agrees to it in Terminal itself.
pub fn install_script() -> String {
    format!(
        "#!/bin/zsh\n\
         echo 'Installing Claude Code with its official installer. This is the command it runs:'\n\
         echo\n\
         echo '  {INSTALL_COMMAND}'\n\
         echo\n\
         echo 'Press Return to run it, or close this window to stop.'\n\
         read -r _\n\
         {INSTALL_COMMAND}\n\
         echo\n\
         echo 'When it says it is done, go back to the physgate app and choose Check Again.'\n"
    )
}

/// The sign-in fallback: `claude setup-token`, then the clipboard and the window cleared.
pub fn sign_in_script(claude: &str) -> String {
    format!(
        "#!/bin/zsh\n\
         echo 'Signing Claude Code in for physgate runs.'\n\
         echo 'Your browser opens; sign in there. Then copy the token printed here,'\n\
         echo 'paste it into the physgate app, and close this window.'\n\
         echo\n\
         '{}' setup-token\n\
         echo\n\
         echo 'When the app says the token is kept, press Return here.'\n\
         echo 'That empties the clipboard and clears this window, so the token is left in neither.'\n\
         read -r _\n\
         printf '' | pbcopy\n\
         clear && printf '\\033[3J'\n\
         echo 'Clipboard emptied and window cleared. You can close this window.'\n",
        claude.replace('\'', r"'\''")
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_installer_shows_its_command_and_waits_for_return_before_it_runs_it() {
        let install = install_script();
        assert!(install.starts_with("#!/bin/zsh\n"));
        let shown = install
            .find(&format!("echo '  {INSTALL_COMMAND}'"))
            .unwrap();
        let waits = install.find("read -r _\n").unwrap();
        let runs = install.find(&format!("\n{INSTALL_COMMAND}\n")).unwrap();
        assert!(shown < waits && waits < runs, "{install}");
        // It runs once, and only the command it showed.
        assert_eq!(install.matches(INSTALL_COMMAND).count(), 2);
    }

    #[test]
    fn the_sign_in_runs_only_what_it_says_and_clears_after() {
        let sign_in = sign_in_script("/Users/me/it's/claude");
        assert!(sign_in.contains(r"'/Users/me/it'\''s/claude' setup-token"));
        // The token is pasted through the clipboard and printed here: both are emptied after.
        assert!(sign_in.contains("printf '' | pbcopy"));
        assert!(sign_in.contains("clear && printf"));
    }
}
