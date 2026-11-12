# Changelog

## 1.0.0 - 2026-11-11

Initial release.

* Customers audit over a WooCommerce customers CSV export:
  duplicate accounts (same email with different casing or
  plus addressing), zero-order accounts, spam-pattern
  signups, missing billing details, customers with only
  failed or cancelled orders, missing or invalid emails,
  test accounts, missing names and ids, and negative or
  unparseable totals and order counts.
* Email identity normalized before comparison: lowercased,
  whitespace stripped, and plus tags removed, so
  ALICE@example.com and alice+shop@example.com are the same
  mailbox as alice@example.com. The first account seen for a
  normalized email is canonical; later accounts are flagged.
* Missing billing details are an error when the account has
  placed orders and a warning when it has not. A failed-only
  account is flagged only when nothing was spent, so a
  customer who failed once and then bought is not flagged.
* Spam detection covers disposable mailbox domains, usernames
  with a run of five or more digits, and generated-looking
  email local parts (eight or more characters, four or more
  digits, no vowel).
* Malformed CSV rows are reported as data errors and skipped,
  never a crash. UTF-8 BOM headers and extra columns handled.
  Blank lines skipped silently.
* Findings carry a customer, a detail, a rule name, a severity
  (error or warning), and a message; errors and warnings are
  counted in the summary.
* Text and --json output, --out file output, and a --check CI
  gate that exits 1 on errors (and on warnings with --strict).
* Zero dependencies, Python 3.10 or newer.
