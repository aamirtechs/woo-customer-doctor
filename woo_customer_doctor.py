"""WooCommerce customers audit CLI.

Reads a CSV export of WooCommerce customers and audits it for
the account problems that pollute a store's customer list and
skew its reports: duplicate accounts for the same person (the
same email with different casing, or with a plus tag added),
accounts that never ordered, spam-pattern signups, accounts
with missing billing details, and customers whose orders all
failed or were cancelled.

Email identity is normalized before comparison: the address is
lowercased, surrounding whitespace is stripped, and any plus
tag in the local part is removed (alice+shop@example.com is
the same mailbox as alice@example.com). WooCommerce itself
treats email addresses case-insensitively when it looks up a
customer, so two accounts that differ only in casing are the
same customer twice.

Each problem is a finding with a customer, a rule name, a
severity (error or warning), and a message. Errors are the ones
that corrupt the customer list or the order reports; warnings
are hygiene issues worth cleaning up. --check exits 1 when any
error is found, and --strict also fails on warnings.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 woo_customer_doctor.py examples/customers.csv
    python3 woo_customer_doctor.py customers.csv --json --check
"""

import argparse
import csv
import json
import re
import sys

__version__ = "1.0.0"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DIGIT_RUN_RE = re.compile(r"\d{5,}")
NO_VOWEL_DIGITS_RE = re.compile(r"^(?=[^aeiou]*\d{4,})[a-z0-9]{8,}$")

DISPOSABLE_DOMAINS = {
    "mailinator.com",
    "tempmail.com",
    "guerrillamail.com",
    "10minutemail.com",
    "yopmail.com",
    "sharklasers.com",
    "maildrop.cc",
    "trashmail.com",
}

FAILED_STATUSES = {"failed", "cancelled"}

BILLING_FIELDS = ("billing_address_1", "billing_city",
                  "billing_postcode", "billing_country")


class Finding:
    """One audit finding for one customer or one file row."""

    def __init__(self, customer, detail, rule, severity, message):
        self.customer = customer
        self.detail = detail
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"customer": self.customer, "detail": self.detail,
                "rule": self.rule, "severity": self.severity,
                "message": self.message}

    def __str__(self):
        target = self.customer
        if self.detail is not None:
            target = "%s [%s]" % (self.customer, self.detail)
        return "%s [%s] %s: %s" % (self.severity.upper(), self.rule,
                                   target, self.message)


def normalize_email(email):
    """Normalize an email for identity comparison.

    Lowercase it, strip surrounding whitespace, and drop any
    plus tag in the local part, so ALICE@example.com and
    alice+shop@example.com both normalize to alice@example.com.
    Returns None when the value is blank.
    """
    if email is None:
        return None
    email = email.strip().lower()
    if not email:
        return None
    local, sep, domain = email.partition("@")
    if sep:
        local = local.split("+", 1)[0]
        email = local + "@" + domain
    return email


def parse_int(value):
    """Parse an integer string, or return None.

    Accepts "3" and "3.0". A blank value returns None without
    an error; the caller decides what a blank count means.
    """
    if value is None:
        return None
    value = value.strip().replace(",", "")
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        try:
            number = float(value)
        except ValueError:
            return None
        if number.is_integer():
            return int(number)
        return None


def parse_money(value):
    """Parse a money string to a float, or return None.

    A blank value returns None without an error. A leading
    currency symbol and thousands separators are stripped.
    """
    if value is None:
        return None
    value = value.strip().replace(",", "").lstrip("$")
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


class Customer:
    """One customer row from the export."""

    def __init__(self, record, line_no):
        self.line = line_no
        self.id = (record.get("id") or "").strip()
        self.email = (record.get("email") or "").strip()
        self.username = (record.get("username") or "").strip()
        self.first_name = (record.get("first_name") or "").strip()
        self.last_name = (record.get("last_name") or "").strip()
        self.record = record
        self.orders_count = parse_int(record.get("orders_count"))
        self.orders_raw = (record.get("orders_count") or "").strip()
        self.total_spent = parse_money(record.get("total_spent"))
        self.total_raw = (record.get("total_spent") or "").strip()
        self.last_order_status = (
            (record.get("last_order_status") or "").strip().lower())

    def label(self):
        """Return the display label for this customer."""
        if self.id:
            return "customer %s" % self.id
        if self.email:
            return "customer (%s)" % self.email
        return "row %d" % self.line

    def billing_missing(self):
        """Return the billing fields that are blank."""
        missing = []
        for field in BILLING_FIELDS:
            if not (self.record.get(field) or "").strip():
                missing.append(field)
        return missing


def load_customers(path):
    """Read the customers CSV and return (customers, findings).

    A row with the wrong number of fields is reported as a
    malformed-row error and skipped, never a crash. Blank
    lines are skipped silently. A UTF-8 BOM header is handled.
    """
    customers = []
    findings = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return customers, findings
        expected = len(header)
        for line_no, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != expected:
                findings.append(Finding(
                    "(file)", "row %d" % line_no, "malformed-row",
                    "error",
                    "row has %d fields but the header has %d, so the "
                    "row was skipped" % (len(row), expected)))
                continue
            record = dict(zip(header, row))
            customers.append(Customer(record, line_no))
    return customers, findings


def spam_reasons(customer):
    """Return the spam-pattern reasons for one customer.

    A signup looks like spam when its email domain is a known
    disposable mailbox service, when its username carries a
    run of five or more digits, or when its email local part is
    eight or more characters with four or more digits and no
    vowel, which is the shape of a generated address.
    """
    reasons = []
    email = customer.email.strip().lower()
    if "@" in email:
        domain = email.rsplit("@", 1)[1]
        if domain in DISPOSABLE_DOMAINS:
            reasons.append("email domain %s is a disposable "
                           "mailbox service" % domain)
    if DIGIT_RUN_RE.search(customer.username):
        reasons.append("username %r contains a run of five or "
                       "more digits" % customer.username)
    local = email.split("@", 1)[0] if "@" in email else ""
    if NO_VOWEL_DIGITS_RE.match(local):
        reasons.append("email local part %r has four or more "
                       "digits and no vowel, which looks "
                       "generated" % local)
    return reasons


def audit_customers(customers):
    """Run the customer rules and return a list of findings."""
    findings = []
    seen_emails = {}
    for customer in customers:
        label = customer.label()
        if not customer.id:
            findings.append(Finding(
                label, None, "missing-id", "error",
                "row has no customer id, so the account cannot be "
                "matched to a store record"))
        if not customer.email:
            findings.append(Finding(
                label, None, "missing-email", "error",
                "account has no email address, so it cannot be "
                "contacted or logged in to"))
        else:
            if not EMAIL_RE.match(customer.email):
                findings.append(Finding(
                    label, customer.email, "invalid-email", "error",
                    "email %r is not a valid email address"
                    % customer.email))
            normalized = normalize_email(customer.email)
            if normalized in seen_emails:
                findings.append(Finding(
                    label, customer.email, "duplicate-email", "error",
                    "email normalizes to %r, which already belongs "
                    "to %s, so this is the same customer twice"
                    % (normalized, seen_emails[normalized])))
            else:
                seen_emails[normalized] = label
        if not customer.first_name and not customer.last_name:
            findings.append(Finding(
                label, None, "missing-name", "warning",
                "account has no first or last name, so order emails "
                "and invoices have nobody to address"))
        if customer.orders_raw and customer.orders_count is None:
            findings.append(Finding(
                label, customer.orders_raw, "invalid-orders-count",
                "warning",
                "orders count %r is not a number, so the account "
                "cannot be counted as a buyer or a non-buyer"
                % customer.orders_raw))
        if customer.total_raw and customer.total_spent is None:
            findings.append(Finding(
                label, customer.total_raw, "invalid-total-spent",
                "warning",
                "total spent %r is not a number, so the account "
                "value cannot be counted" % customer.total_raw))
        if (customer.total_spent is not None
                and customer.total_spent < 0):
            findings.append(Finding(
                label, customer.total_raw, "negative-total", "error",
                "total spent %.2f is negative, so the order totals "
                "do not add up" % customer.total_spent))
        if customer.orders_count == 0:
            findings.append(Finding(
                label, None, "zero-order-account", "warning",
                "account has placed no orders, so it is either a "
                "new signup or a dead account to clean up"))
        if (customer.orders_count is not None
                and customer.orders_count > 0
                and customer.total_spent == 0
                and customer.last_order_status in FAILED_STATUSES):
            findings.append(Finding(
                label, customer.last_order_status,
                "only-failed-orders", "error",
                "account placed %d order(s) and every one failed or "
                "was cancelled, with nothing spent, so the customer "
                "never completed a purchase"
                % customer.orders_count))
        missing = customer.billing_missing()
        if missing:
            if customer.orders_count is not None \
                    and customer.orders_count > 0:
                findings.append(Finding(
                    label, ", ".join(missing), "missing-billing",
                    "error",
                    "account has placed orders but is missing billing "
                    "details (%s), so invoices and tax records are "
                    "incomplete" % ", ".join(missing)))
            else:
                findings.append(Finding(
                    label, ", ".join(missing), "missing-billing",
                    "warning",
                    "account is missing billing details (%s)"
                    % ", ".join(missing)))
        for reason in spam_reasons(customer):
            findings.append(Finding(
                label, None, "spam-signup", "warning",
                "signup looks like spam: %s" % reason))
        local = customer.email.split("@", 1)[0].lower() \
            if "@" in customer.email else ""
        if (customer.username.lower().startswith("test")
                or local.startswith("test")):
            findings.append(Finding(
                label, None, "test-account", "warning",
                "username or email starts with 'test', so this "
                "looks like a test account left in the store"))
    return findings


def audit(path):
    """Audit one customers file and return (customers, findings)."""
    customers, load_findings = load_customers(path)
    findings = load_findings + audit_customers(customers)
    return customers, findings


def summarize(customers, findings):
    """Build the summary dict for one audit."""
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    return {"customers": len(customers), "findings": len(findings),
            "errors": errors, "warnings": warnings}


def format_text(customers, findings, summary):
    """Render the audit as plain text."""
    lines = [str(f) for f in findings]
    lines.append("")
    lines.append("Customers: %d, findings: %d, errors: %d, "
                 "warnings: %d" % (summary["customers"],
                                   summary["findings"],
                                   summary["errors"],
                                   summary["warnings"]))
    if not findings:
        lines.append("All customers clean.")
    return "\n".join(lines) + "\n"


def format_json(customers, findings, summary):
    """Render the audit as JSON."""
    return json.dumps({"summary": summary,
                       "findings": [f.as_dict() for f in findings]},
                      indent=2) + "\n"


def main(argv=None):
    """Entry point for the woo-customer-doctor CLI."""
    parser = argparse.ArgumentParser(
        description="Audit a WooCommerce customers CSV export for "
                    "duplicate accounts, zero-order accounts, spam "
                    "signups, missing billing details, and failed "
                    "only order histories.")
    parser.add_argument("path", help="CSV file of customers")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", help="write the report to a file")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    args = parser.parse_args(argv)
    try:
        customers, findings = audit(args.path)
    except FileNotFoundError:
        print("error: file not found: %s" % args.path, file=sys.stderr)
        return 2
    except OSError as exc:
        print("error: cannot read %s: %s" % (args.path, exc),
              file=sys.stderr)
        return 2
    summary = summarize(customers, findings)
    if args.json:
        output = format_json(customers, findings, summary)
    else:
        output = format_text(customers, findings, summary)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output, end="")
    if args.check:
        if summary["errors"]:
            return 1
        if args.strict and summary["warnings"]:
            return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
