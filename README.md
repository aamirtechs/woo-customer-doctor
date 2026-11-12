# woo-customer-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/woo-customer-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/woo-customer-doctor/issues)

A zero-dependency Python CLI that audits a WooCommerce
customers CSV export for the account problems that pollute a
store's customer list and skew its reports: duplicate accounts
for the same person, accounts that never ordered, spam-pattern
signups, accounts with missing billing details, and customers
whose orders all failed or were cancelled.

Duplicate accounts are the quiet killer. A customer who signs
up twice, once as ALICE@example.com and once as
alice+shop@example.com, shows up as two customers in every
report, gets two copies of every marketing email, and splits
their lifetime value across two records. WooCommerce looks
customers up by email case-insensitively, so two accounts
that differ only in casing are the same customer twice, and
this tool catches both forms before they spread further.

## Install

Requires Python 3.10 or newer. No dependencies beyond the
standard library.

```bash
pip install woo-customer-doctor
```

Or run it straight from the source checkout:

```bash
python3 woo_customer_doctor.py examples/customers.csv
```

## Input format

A CSV export with a header row. Columns used: `id`, `email`,
`username`, `first_name`, `last_name`, `registered`,
`billing_first_name`, `billing_last_name`,
`billing_address_1`, `billing_city`, `billing_postcode`,
`billing_country`, `billing_phone`, `orders_count`,
`total_spent`, `last_order_status`, and `last_order_date`.
Extra columns are ignored. A UTF-8 BOM header is handled.

```csv
id,email,username,first_name,last_name,registered,billing_first_name,billing_last_name,billing_address_1,billing_city,billing_postcode,billing_country,billing_phone,orders_count,total_spent,last_order_status,last_order_date
1,alice@example.com,alice,Alice,Carter,2026-01-05,Alice,Carter,12 Oak Street,Springfield,62701,US,555-0101,3,120.50,completed,2026-10-02
2,ALICE@example.com,alice2,Alice,Carter,2026-02-11,Alice,Carter,12 Oak Street,Springfield,62701,US,555-0101,1,45.00,completed,2026-09-18
3,alice+shop@example.com,alice_shop,Alice,Carter,2026-03-20,Alice,Carter,12 Oak Street,Springfield,62701,US,555-0101,0,0.00,,2026-03-20
```

## How email identity is normalized

Before any comparison, each email is lowercased, surrounding
whitespace is stripped, and any plus tag in the local part is
removed. `ALICE@example.com` and `alice+shop@example.com`
both normalize to `alice@example.com`, so both are flagged as
duplicates of the first account that used that mailbox. The
first account seen for a normalized email is treated as the
canonical one; later accounts are the findings.

## What it checks

Errors, the ones that corrupt the customer list or the order
reports:

* `duplicate-email`: an email that normalizes to one already
  used by another customer, through different casing or a plus
  tag, so this is the same customer twice.
* `missing-email`: an account with no email address, so it
  cannot be contacted or logged in to.
* `invalid-email`: an email that is not a valid address.
* `missing-billing`: an account that has placed orders but is
  missing billing details (address, city, postcode, or
  country), so invoices and tax records are incomplete.
* `only-failed-orders`: an account that placed orders and
  every one failed or was cancelled, with nothing spent, so
  the customer never completed a purchase.
* `negative-total`: a total spent below zero, so the order
  totals do not add up.
* `missing-id`: a row with no customer id, so the account
  cannot be matched to a store record.
* `malformed-row`: a row with the wrong number of fields. The
  row is skipped and reported, never a crash.

Warnings, hygiene issues worth cleaning up:

* `zero-order-account`: an account that has placed no orders,
  so it is either a new signup or a dead account to clean up.
* `spam-signup`: a signup that looks like spam, because its
  email domain is a known disposable mailbox service, its
  username carries a run of five or more digits, or its email
  local part is eight or more characters with four or more
  digits and no vowel, which is the shape of a generated
  address.
* `test-account`: a username or email starting with `test`,
  so this looks like a test account left in the store.
* `missing-billing`: an account with no orders that is
  missing billing details. Same rule name as the error, but a
  warning when the account has never ordered.
* `missing-name`: an account with no first or last name, so
  order emails and invoices have nobody to address.
* `invalid-orders-count`: an orders count that is not a
  number, so the account cannot be counted as a buyer or a
  non-buyer.
* `invalid-total-spent`: a total spent that is not a number,
  so the account value cannot be counted.

## Usage

```bash
python3 woo_customer_doctor.py examples/customers.csv
```

Captured output:

```
ERROR [malformed-row] (file) [row 14]: row has 18 fields but the header has 17, so the row was skipped
ERROR [duplicate-email] customer 2 [ALICE@example.com]: email normalizes to 'alice@example.com', which already belongs to customer 1, so this is the same customer twice
ERROR [duplicate-email] customer 3 [alice+shop@example.com]: email normalizes to 'alice@example.com', which already belongs to customer 1, so this is the same customer twice
WARNING [zero-order-account] customer 3: account has placed no orders, so it is either a new signup or a dead account to clean up
WARNING [zero-order-account] customer 4: account has placed no orders, so it is either a new signup or a dead account to clean up
WARNING [spam-signup] customer 4: signup looks like spam: username 'bob1234567' contains a run of five or more digits
WARNING [missing-name] customer 5: account has no first or last name, so order emails and invoices have nobody to address
WARNING [zero-order-account] customer 5: account has placed no orders, so it is either a new signup or a dead account to clean up
WARNING [missing-billing] customer 5 [billing_address_1, billing_city, billing_postcode, billing_country]: account is missing billing details (billing_address_1, billing_city, billing_postcode, billing_country)
WARNING [spam-signup] customer 5: signup looks like spam: email domain mailinator.com is a disposable mailbox service
ERROR [missing-billing] customer 6 [billing_address_1]: account has placed orders but is missing billing details (billing_address_1), so invoices and tax records are incomplete
ERROR [only-failed-orders] customer 7 [failed]: account placed 2 order(s) and every one failed or was cancelled, with nothing spent, so the customer never completed a purchase
ERROR [invalid-email] customer 8 [not-an-email]: email 'not-an-email' is not a valid email address
ERROR [missing-email] customer 9: account has no email address, so it cannot be contacted or logged in to
WARNING [zero-order-account] customer 9: account has placed no orders, so it is either a new signup or a dead account to clean up
WARNING [zero-order-account] customer 10: account has placed no orders, so it is either a new signup or a dead account to clean up
WARNING [test-account] customer 10: username or email starts with 'test', so this looks like a test account left in the store
WARNING [invalid-orders-count] customer 11 [three]: orders count 'three' is not a number, so the account cannot be counted as a buyer or a non-buyer
ERROR [negative-total] customer 12 [-5.00]: total spent -5.00 is negative, so the order totals do not add up

Customers: 12, findings: 19, errors: 8, warnings: 11
```

The sample has one customer, Alice Carter, split across
three accounts: the original, a casing duplicate, and a plus
tag duplicate. Customer 5 signed up from a disposable mailbox
with no name and no billing details. Customer 7 placed two
orders and both failed, so the customer never completed a
purchase. Customer 9 has no email at all.

Use it as a CI gate: `--check` exits 1 when any error is
found, and 0 otherwise. On the sample above it exits 1:

```bash
python3 woo_customer_doctor.py examples/customers.csv --check
```

On `examples/clean.csv`, three real customers with complete
billing and completed orders, it exits 0:

```
Customers: 3, findings: 0, errors: 0, warnings: 0
All customers clean.
```

With `--strict`, `--check` also fails on warnings.
`examples/warnings-only.csv` has three warnings and no
errors, two zero-order accounts and one missing billing city,
so it passes `--check` (exit 0) and fails `--check --strict`
(exit 1).

`--json` emits the summary and findings as JSON, and `--out`
writes the report to a file.

## Options

| Flag | Meaning |
| --- | --- |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

## Edge cases

* Email comparison is case-insensitive and plus-tag aware,
  so `ALICE@example.com` and `alice+shop@example.com` are the
  same mailbox. The first account seen is canonical; only
  later accounts are flagged.
* A missing billing detail is an error when the account has
  placed orders and a warning when it has not, because an
  invoice cannot be issued for a buyer without an address,
  while a never-ordered signup is only incomplete.
* A customer with failed orders is only flagged when they
  spent nothing; a customer who failed once and then bought
  successfully is a real customer, not a failed-only account.
* A spam-signup finding can carry more than one reason, but
  it is reported once per reason, so a disposable domain plus
  a digit-run username is two findings for one account.
* A row with too many or too few fields is a malformed-row
  error and is skipped; the rest of the file is still audited.
  A blank line is skipped silently.
* Order counts accept `3` and `3.0`. Totals accept a leading
  `$` and thousands separators. Anything else unparseable is
  a warning, never a crash.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

62 tests, all passing: email normalization (casing, plus
tags, whitespace), duplicate detection including three-way
duplicates, missing and invalid emails, zero-order accounts,
spam patterns (disposable domains, digit-run usernames,
generated local parts), test accounts, missing billing as an
error and as a warning, failed-only and cancelled-only order
histories, negative and unparseable totals and counts, missing
ids and names, malformed rows, BOM headers, blank lines,
empty files, sample counts, JSON output shape, and `--check`
and `--strict` exit codes.

## License

MIT. See [LICENSE](LICENSE).
