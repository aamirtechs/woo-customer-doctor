# Good first issues

Seeded issues for new contributors. File each one on GitHub with
the `good first issue` and `help wanted` labels.

## 1. Add a duplicate merge suggestion

Title: Suggest which duplicate account to keep

Description: After the findings, print a short table of each
duplicate email group with the canonical account (the first
one seen) and the duplicate accounts, plus which one has the
most orders and the highest total spent, so a store owner can
pick the account to keep before merging. The tool itself must
never change anything in the store.

Difficulty: Easy

Acceptance criteria: the table for the sample file shows the
alice@example.com group with customer 1 canonical and
customers 2 and 3 as duplicates, with customer 1 having the
most orders; JSON output is unchanged; a test checks the table
rows.

## 2. Add a --disposable-domains file flag

Title: Let stores supply their own disposable domain list

Description: Add a --disposable-domains flag that takes a text
file with one domain per line and uses it instead of the
built-in list for the spam-signup check, so a store can add
the disposable services it actually sees. The built-in list
stays the default when the flag is not given.

Difficulty: Easy

Acceptance criteria: a custom list containing example.net
flags an account at that domain; the default list still flags
mailinator.com; a test covers both cases; README documents the
flag.

## 3. Add a --since flag to ignore old zero-order accounts

Title: Only flag zero-order accounts registered recently

Description: Add a --since flag that takes a date
(YYYY-MM-DD) and skips the zero-order-account warning for
accounts registered before that date, so a store doing a
first cleanup can focus on recent signups and leave old
accounts for a separate purge. Other rules are unchanged.

Difficulty: Medium

Acceptance criteria: with --since 2026-04-01, the sample file
no longer flags customer 3 (registered 2026-03-20) as
zero-order but still flags customer 4 (registered 2026-04-02);
a test checks the cutoff; README documents the flag.

## 4. Add a per-rule summary table

Title: Show a count of findings per rule

Description: Add a --by-rule flag that prints, after the
summary, a table of each rule with its severity and how many
findings it produced, so a store owner can see at a glance
whether duplicates or spam are the bigger problem without
reading every finding.

Difficulty: Easy

Acceptance criteria: the table for the sample file shows
duplicate-email with 2 findings and zero-order-account with
4; a test checks the table rows; README documents the flag.
