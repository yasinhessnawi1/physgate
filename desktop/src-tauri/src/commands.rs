//! No screen of the app shows a terminal command.
//!
//! What a command looks like comes from `ui/src/rules/terminal-commands.json`, the file the
//! operator UI's rule test reads as well. This module holds the one matcher, and the filter
//! every text the shell puts in front of a person passes through at run time: its own page,
//! its dialogs and window titles, and what the onboarding page reads from it. Its tests scan
//! every string the shell is built from, and its bundled pages and catalogue.

use std::sync::OnceLock;

use serde::Deserialize;

const COMMAND_SHAPES: &str = include_str!("../../../ui/src/rules/terminal-commands.json");

#[derive(Deserialize)]
struct Shapes {
    subcommands: Vec<String>,
    phrases: Vec<String>,
}

fn shapes() -> &'static Shapes {
    static SHAPES: OnceLock<Shapes> = OnceLock::new();
    SHAPES.get_or_init(|| {
        serde_json::from_str(COMMAND_SHAPES).expect("the bundled command shapes are valid JSON")
    })
}

fn word_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_' || c == '-'
}

/// Each place `word` stands as a whole word followed by whitespace, with the text after the
/// whitespace.
fn after_word<'a>(text: &'a str, word: &'a str) -> impl Iterator<Item = &'a str> + 'a {
    text.match_indices(word).filter_map(move |(at, _)| {
        if text[..at].chars().next_back().is_some_and(word_char) {
            return None;
        }
        let rest = &text[at + word.len()..];
        let trimmed = rest.trim_start();
        (trimmed.len() < rest.len()).then_some(trimmed)
    })
}

/// Whether `phrase` stands in `text`. A phrase that starts with a word character starts a
/// word, and one that ends with a word character ends one, so `uv run` is not found in
/// `uv runs` nor `git ` in `legit `.
fn holds_phrase(text: &str, phrase: &str) -> bool {
    let starts_word = phrase.starts_with(|c: char| c.is_ascii_alphanumeric() || c == '_');
    let ends_word = phrase.ends_with(|c: char| c.is_ascii_alphanumeric() || c == '_');
    text.match_indices(phrase).any(|(at, _)| {
        let before = text[..at].chars().next_back();
        let after = text[at + phrase.len()..].chars().next();
        !(starts_word && before.is_some_and(word_char))
            && !(ends_word && after.is_some_and(word_char))
    })
}

/// Whether `text` names a terminal command: `physgate` and one of its subcommands, a shell
/// variable exported (`export NAME=`), or one of the phrases a command is made of.
pub fn names_a_command(text: &str) -> bool {
    let shapes = shapes();
    shapes.phrases.iter().any(|p| holds_phrase(text, p))
        || after_word(text, "physgate").any(|rest| {
            let word: String = rest.chars().take_while(|&c| word_char(c)).collect();
            shapes.subcommands.contains(&word)
        })
        || after_word(text, "export").any(|rest| {
            let name: String = rest
                .chars()
                .take_while(|&c| c.is_ascii_alphanumeric() || c == '_')
                .collect();
            !name.is_empty()
                && !name.starts_with(|c: char| c.is_ascii_digit())
                && rest[name.len()..].starts_with('=')
        })
}

/// What is said in place of a line that named a command.
pub const LEFT_OUT: &str = "(Part of this message named a terminal command and is left out.)";

/// `text` as a screen may show it: every line that names a command left out, and said to be.
pub fn plain(text: &str) -> String {
    let mut dropped = false;
    let mut kept: Vec<&str> = Vec::new();
    for line in text.split('\n') {
        if names_a_command(line) {
            dropped = true;
        } else {
            kept.push(line);
        }
    }
    let mut shown = kept.join("\n").trim_end().to_string();
    if dropped {
        if !shown.is_empty() {
            shown.push(' ');
        }
        shown.push_str(LEFT_OUT);
    }
    shown
}

/// A command's refusal, as the page that asked for it may show it.
pub fn plain_err<T>(result: Result<T, String>) -> Result<T, String> {
    result.map_err(|e| plain(&e))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::Path;

    #[test]
    fn a_command_is_recognised_by_its_shape() {
        for planted in [
            "physgate decompose <brief> --seed 1",
            "then physgate ui",
            "(physgate queue resolve)",
            "physgate\trun",
            "export CLAUDE_CODE_OAUTH_TOKEN=\"$(x)\"",
            "export  A_1=b",
            "security find-generic-password -s physgate-trial",
            "physgate-x --run-dir /r",
            "cd /c && uv run pytest",
            "cd /c && uv sync",
            "scripts/build-ui.sh",
            "(cd ui && pnpm install --frozen-lockfile)",
            "curl -fsSL https://claude.ai/install.sh | bash",
            "curl -LsSf https://example.org/x | sh",
            "claude setup-token",
            "git worktree list",
            "pnpm run build",
        ] {
            assert!(names_a_command(planted), "{planted}");
        }
        for prose in [
            "The physgate operator",
            "the physgate UI",
            "a physgate checkout",
            "physgate runs",
            "physgate → Operator Name…",
            "Export the table",
            "export as CSV",
            "export 2=x",
            "the physgateui",
            "nophysgate run",
            "a legit result",
            "uv runs",
            "a | shared value",
            "curling",
            "the setup-tokens",
        ] {
            assert!(!names_a_command(prose), "{prose}");
        }
        // The cost of `git ` as a phrase: prose that says "git " is refused too, so the
        // product's words say "commit" or "history" instead.
        assert!(names_a_command("the git history of a run"));
    }

    #[test]
    fn a_line_that_names_a_command_is_left_out_and_said_to_be() {
        assert_eq!(plain("It stopped."), "It stopped.");
        assert_eq!(
            plain("It stopped.\nRun physgate ui --root x to see."),
            format!("It stopped. {LEFT_OUT}")
        );
        assert_eq!(plain("uv sync"), LEFT_OUT);
        assert_eq!(
            plain_err::<()>(Err("uv run x".into())),
            Err(LEFT_OUT.into())
        );
    }

    /// The string literals of a Rust source, with its test module left out.
    fn literals(source: &str) -> Vec<String> {
        let code = source
            .find("#[cfg(test)]\nmod tests")
            .map_or(source, |at| &source[..at]);
        let chars: Vec<char> = code.chars().collect();
        let mut found = Vec::new();
        let mut i = 0;
        while i < chars.len() {
            let next = chars.get(i + 1).copied();
            match chars[i] {
                // A line comment: its text is no string.
                '/' if next == Some('/') => {
                    while i < chars.len() && chars[i] != '\n' {
                        i += 1;
                    }
                }
                // A character literal holding a quote, plain or escaped.
                '\'' if next == Some('"') && chars.get(i + 2) == Some(&'\'') => i += 3,
                '\'' if next == Some('\\') && chars.get(i + 3) == Some(&'\'') => i += 4,
                // A raw string, r"…" or r#"…"#.
                'r' if (next == Some('"') || next == Some('#'))
                    && (i == 0 || !chars[i - 1].is_alphanumeric()) =>
                {
                    let mut j = i + 1;
                    let mut hashes = 0;
                    while chars.get(j) == Some(&'#') {
                        hashes += 1;
                        j += 1;
                    }
                    if chars.get(j) != Some(&'"') {
                        i += 1;
                        continue;
                    }
                    let mut text = String::new();
                    j += 1;
                    loop {
                        match chars.get(j) {
                            None => break,
                            Some('"') if (1..=hashes).all(|k| chars.get(j + k) == Some(&'#')) => {
                                j += 1 + hashes;
                                break;
                            }
                            Some(&c) => {
                                text.push(c);
                                j += 1;
                            }
                        }
                    }
                    found.push(text);
                    i = j;
                }
                '"' => {
                    let mut text = String::new();
                    i += 1;
                    while i < chars.len() && chars[i] != '"' {
                        if chars[i] == '\\' {
                            i += 1;
                            match chars.get(i) {
                                // A continued line: the backslash, the newline and the indent go.
                                Some('\n') => {
                                    while chars.get(i).is_some_and(|c| c.is_whitespace()) {
                                        i += 1;
                                    }
                                    continue;
                                }
                                // An escaped newline, return or tab is that character, so the
                                // word before it still ends there.
                                Some('n') => text.push('\n'),
                                Some('r') => text.push('\r'),
                                Some('t') => text.push('\t'),
                                Some(&c) => text.push(c),
                                None => {}
                            }
                            i += 1;
                            continue;
                        }
                        text.push(chars[i]);
                        i += 1;
                    }
                    found.push(text);
                    i += 1;
                }
                _ => i += 1,
            }
        }
        found
    }

    /// The one file whose strings are commands by design: what the app opens in Terminal.
    const TERMINAL_ONLY: &str = "terminal.rs";

    /// Every text the shell can put in front of a person, by file: the strings of its Rust
    /// sources (but the Terminal-only file), every line of its bundled pages, and every string
    /// value of its bundled catalogue.
    fn shell_texts() -> Vec<(String, Vec<String>)> {
        let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
        let mut texts = Vec::new();
        for entry in fs::read_dir(manifest.join("src")).unwrap() {
            let path = entry.unwrap().path();
            let terminal_only = path.file_name().is_some_and(|n| n == TERMINAL_ONLY);
            if path.extension().is_some_and(|e| e == "rs") && !terminal_only {
                let source = fs::read_to_string(&path).unwrap();
                texts.push((path.display().to_string(), literals(&source)));
            }
        }
        for entry in fs::read_dir(manifest.join("../status")).unwrap() {
            let path = entry.unwrap().path();
            if path
                .extension()
                .is_some_and(|e| e == "html" || e == "js" || e == "css")
            {
                // Line by line, so a finding names its line rather than the whole page.
                let page = fs::read_to_string(&path).unwrap();
                texts.push((
                    path.display().to_string(),
                    page.lines().map(ToString::to_string).collect(),
                ));
            }
        }
        for entry in fs::read_dir(manifest.join("../onboarding")).unwrap() {
            let path = entry.unwrap().path();
            if path.extension().is_some_and(|e| e == "json") {
                let value: serde_json::Value =
                    serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
                texts.push((path.display().to_string(), string_values(&value)));
            }
        }
        texts
    }

    fn string_values(value: &serde_json::Value) -> Vec<String> {
        match value {
            serde_json::Value::String(s) => vec![s.clone()],
            serde_json::Value::Array(items) => items.iter().flat_map(string_values).collect(),
            serde_json::Value::Object(map) => map.values().flat_map(string_values).collect(),
            _ => Vec::new(),
        }
    }

    #[test]
    fn no_text_of_the_shell_names_a_terminal_command() {
        let texts = shell_texts();
        assert!(texts.len() > 20, "the sources were found");
        assert!(
            texts
                .iter()
                .any(|(f, s)| f.ends_with("engines.json") && s.len() > 10),
            "the catalogue was read"
        );
        let found: Vec<String> = texts
            .iter()
            .flat_map(|(file, strings)| {
                strings
                    .iter()
                    .filter(|s| names_a_command(s))
                    .map(move |s| format!("{file}: {s}"))
            })
            .collect();
        assert!(found.is_empty(), "{found:#?}");
    }

    #[test]
    fn the_terminal_only_file_is_left_out_by_name_and_still_holds_the_commands() {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("src")
            .join(TERMINAL_ONLY);
        let source = fs::read_to_string(&path).expect("the Terminal-only file is where it was");
        assert!(source.contains("**Terminal only.**"), "it says what it is");
        let named: Vec<String> = literals(&source)
            .into_iter()
            .filter(|s| names_a_command(s))
            .collect();
        // The installer's command and the sign-in's `setup-token`: the exclusion is load-bearing.
        assert!(named.iter().any(|s| s.contains("| bash")), "{named:?}");
        assert!(named.iter().any(|s| s.contains("setup-token")), "{named:?}");
    }

    #[test]
    fn the_scan_reads_strings_as_the_compiler_does() {
        let source = "fn a() { let x = \"one \\\n    physgate run\"; let y = r#\"export A=b\"#; \
                      let q = '\"'; // physgate ui\n let z = \"c\"; }\n\
                      #[cfg(test)]\nmod tests { const P: &str = \"physgate ui\"; }";
        assert_eq!(
            literals(source),
            ["one physgate run", "export A=b", "c"],
            "a continued line is joined, a raw string read, a comment and the tests left out"
        );
        // An escaped newline ends the word before it, as it does when the string is shown.
        let escaped = literals("const S: &str = \"run it setup-token\\nnext\";");
        assert_eq!(escaped, ["run it setup-token\nnext"]);
        assert!(names_a_command(&escaped[0]));
    }
}
