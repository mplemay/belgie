/// Substring present in Deno and Belgie age-policy resolution failures.
const MINIMUM_DEPENDENCY_AGE_MARKER: &str = "minimum dependency date";

const MINIMUM_DEPENDENCY_AGE_HINT: &str = concat!(
    "\n\nhint: This version is blocked by the minimum dependency age policy, ",
    "which avoids installing recently published versions to reduce supply ",
    "chain risk (the default is 24 hours). To use this version now, pass ",
    "--minimum-dependency-age=0 (or --min-dep-age=0), set a shorter duration, ",
    "or set [tool.belgie].minimum-dependency-age / EnvironmentOptions.",
    "minimum_dependency_age (for example \"0\" to disable, or \"60\" minutes)."
);

/// Appends Deno-style override guidance when `message` is an age-policy block.
pub(crate) fn with_minimum_dependency_age_hint(message: String) -> String {
    if !message.contains(MINIMUM_DEPENDENCY_AGE_MARKER)
        || message.contains("blocked by the minimum dependency age policy")
    {
        return message;
    }
    format!("{message}{MINIMUM_DEPENDENCY_AGE_HINT}")
}

#[cfg(test)]
mod tests {
    use super::{MINIMUM_DEPENDENCY_AGE_MARKER, with_minimum_dependency_age_hint};

    #[test]
    fn appends_hint_for_age_policy_errors() {
        let message = format!("failed: {MINIMUM_DEPENDENCY_AGE_MARKER} of 2025-01-01");
        let hinted = with_minimum_dependency_age_hint(message);
        assert!(hinted.contains("blocked by the minimum dependency age policy"));
        assert!(hinted.contains("--minimum-dependency-age=0"));
    }

    #[test]
    fn leaves_unrelated_errors_unchanged() {
        let message = "package not found".to_string();
        assert_eq!(with_minimum_dependency_age_hint(message.clone()), message);
    }

    #[test]
    fn does_not_duplicate_hint() {
        let message =
            with_minimum_dependency_age_hint(format!("failed: {MINIMUM_DEPENDENCY_AGE_MARKER}"));
        let again = with_minimum_dependency_age_hint(message.clone());
        assert_eq!(
            again
                .matches("blocked by the minimum dependency age policy")
                .count(),
            1
        );
    }
}
