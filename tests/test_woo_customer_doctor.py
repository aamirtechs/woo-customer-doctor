"""Tests for woo-customer-doctor."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import woo_customer_doctor as wcd

HEADER = ("id,email,username,first_name,last_name,registered,"
          "billing_first_name,billing_last_name,billing_address_1,"
          "billing_city,billing_postcode,billing_country,"
          "billing_phone,orders_count,total_spent,last_order_status,"
          "last_order_date\n")


def row(customer_id, email, username="user", first="First",
        last="Last", orders="1", total="10.00", status="completed",
        billing=True, billing_city="Springfield"):
    """Build one CSV row with sane defaults."""
    if billing:
        bill = "First,Last,12 Oak Street,%s,62701,US,555-0101" % billing_city
    else:
        bill = "First,Last,,,62701,US,555-0101"
    return ("%s,%s,%s,%s,%s,2026-01-05,%s,%s,%s,%s,2026-10-02\n"
            % (customer_id, email, username, first, last, bill,
               orders, total, status))


def audit_text(text):
    """Audit CSV text and return (customers, findings)."""
    with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                     delete=False) as handle:
        handle.write(text)
        path = handle.name
    try:
        return wcd.audit(path)
    finally:
        os.unlink(path)


def rules(findings):
    """Return the sorted rule names of a findings list."""
    return sorted(f.rule for f in findings)


class NormalizeEmailTests(unittest.TestCase):
    """Email normalization for duplicate detection."""

    def test_lowercases(self):
        self.assertEqual(wcd.normalize_email("ALICE@Example.COM"),
                         "alice@example.com")

    def test_strips_plus_tag(self):
        self.assertEqual(
            wcd.normalize_email("alice+shop@example.com"),
            "alice@example.com")

    def test_strips_whitespace(self):
        self.assertEqual(wcd.normalize_email("  alice@example.com  "),
                         "alice@example.com")

    def test_blank_returns_none(self):
        self.assertIsNone(wcd.normalize_email("   "))
        self.assertIsNone(wcd.normalize_email(None))

    def test_no_at_sign_unchanged(self):
        self.assertEqual(wcd.normalize_email("not-an-email"),
                         "not-an-email")


class ParseTests(unittest.TestCase):
    """Number parsing helpers."""

    def test_parse_int_plain(self):
        self.assertEqual(wcd.parse_int("3"), 3)

    def test_parse_int_float_form(self):
        self.assertEqual(wcd.parse_int("3.0"), 3)

    def test_parse_int_bad(self):
        self.assertIsNone(wcd.parse_int("three"))

    def test_parse_int_blank(self):
        self.assertIsNone(wcd.parse_int(""))

    def test_parse_money_plain(self):
        self.assertEqual(wcd.parse_money("120.50"), 120.50)

    def test_parse_money_symbol_and_commas(self):
        self.assertEqual(wcd.parse_money("$1,200.00"), 1200.00)

    def test_parse_money_bad(self):
        self.assertIsNone(wcd.parse_money("abc"))

    def test_parse_money_blank(self):
        self.assertIsNone(wcd.parse_money(""))


class DuplicateTests(unittest.TestCase):
    """Duplicate account detection."""

    def test_case_only_duplicate(self):
        _c, findings = audit_text(HEADER + row(1, "alice@example.com")
                                  + row(2, "ALICE@example.com",
                                        username="alice2"))
        self.assertEqual(rules(findings), ["duplicate-email"])
        self.assertIn("customer 1", findings[0].message)

    def test_plus_tag_duplicate(self):
        _c, findings = audit_text(HEADER + row(1, "alice@example.com")
                                  + row(2, "alice+shop@example.com",
                                        username="alice_shop"))
        self.assertEqual(rules(findings), ["duplicate-email"])

    def test_first_occurrence_not_flagged(self):
        _c, findings = audit_text(HEADER + row(1, "alice@example.com"))
        self.assertEqual(findings, [])

    def test_different_emails_not_duplicates(self):
        _c, findings = audit_text(HEADER + row(1, "alice@example.com")
                                  + row(2, "bob@example.com",
                                        username="bob"))
        self.assertEqual(findings, [])

    def test_three_way_duplicate_flags_two(self):
        _c, findings = audit_text(
            HEADER + row(1, "alice@example.com")
            + row(2, "ALICE@example.com", username="alice2")
            + row(3, "alice+news@example.com", username="alice3"))
        self.assertEqual(rules(findings),
                         ["duplicate-email", "duplicate-email"])


class EmailValidityTests(unittest.TestCase):
    """Missing and invalid email addresses."""

    def test_missing_email_is_error(self):
        _c, findings = audit_text(HEADER + row(1, ""))
        self.assertEqual(rules(findings), ["missing-email"])

    def test_invalid_email_is_error(self):
        _c, findings = audit_text(HEADER + row(1, "not-an-email"))
        self.assertEqual(rules(findings), ["invalid-email"])

    def test_email_without_domain_dot_is_invalid(self):
        _c, findings = audit_text(HEADER + row(1, "alice@example"))
        self.assertEqual(rules(findings), ["invalid-email"])

    def test_valid_email_passes(self):
        _c, findings = audit_text(HEADER + row(1, "alice@example.com"))
        self.assertEqual(findings, [])


class ZeroOrderTests(unittest.TestCase):
    """Zero-order accounts."""

    def test_zero_orders_is_warning(self):
        _c, findings = audit_text(HEADER + row(1, "alice@example.com",
                                               orders="0", total="0.00",
                                               status=""))
        self.assertEqual(rules(findings), ["zero-order-account"])
        self.assertEqual(findings[0].severity, "warning")

    def test_one_order_is_not_flagged(self):
        _c, findings = audit_text(HEADER + row(1, "alice@example.com"))
        self.assertEqual(findings, [])


class SpamTests(unittest.TestCase):
    """Spam-pattern signup detection."""

    def test_disposable_domain(self):
        _c, findings = audit_text(
            HEADER + row(1, "spamuser@mailinator.com",
                         username="spamuser"))
        self.assertEqual(rules(findings), ["spam-signup"])

    def test_digit_run_username(self):
        _c, findings = audit_text(
            HEADER + row(1, "bob@example.org", username="bob1234567"))
        self.assertEqual(rules(findings), ["spam-signup"])

    def test_four_digits_not_spam(self):
        _c, findings = audit_text(
            HEADER + row(1, "bob@example.org", username="bob1234"))
        self.assertEqual(findings, [])

    def test_generated_local_part(self):
        _c, findings = audit_text(
            HEADER + row(1, "qzxw9876@example.com", username="qzxw9876"))
        self.assertIn("spam-signup", rules(findings))

    def test_normal_signup_not_spam(self):
        _c, findings = audit_text(
            HEADER + row(1, "alice@example.com", username="alice"))
        self.assertEqual(findings, [])


class TestAccountTests(unittest.TestCase):
    """Test accounts left in the store."""

    def test_username_starting_with_test(self):
        _c, findings = audit_text(
            HEADER + row(1, "user@example.com", username="testuser",
                         orders="0", total="0.00", status=""))
        self.assertIn("test-account", rules(findings))

    def test_email_starting_with_test(self):
        _c, findings = audit_text(
            HEADER + row(1, "testuser@example.com", username="user"))
        self.assertIn("test-account", rules(findings))

    def test_latest_not_flagged(self):
        _c, findings = audit_text(
            HEADER + row(1, "contest@example.com", username="contest"))
        self.assertEqual(findings, [])


class BillingTests(unittest.TestCase):
    """Missing billing details."""

    def test_missing_billing_with_orders_is_error(self):
        _c, findings = audit_text(
            HEADER + row(1, "carol@example.com", billing=False))
        self.assertEqual(rules(findings), ["missing-billing"])
        self.assertEqual(findings[0].severity, "error")

    def test_missing_billing_without_orders_is_warning(self):
        _c, findings = audit_text(
            HEADER + row(1, "carol@example.com", billing=False,
                         orders="0", total="0.00", status=""))
        self.assertEqual(rules(findings),
                         ["missing-billing", "zero-order-account"])
        billing = [f for f in findings if f.rule == "missing-billing"]
        self.assertEqual(billing[0].severity, "warning")

    def test_full_billing_passes(self):
        _c, findings = audit_text(HEADER + row(1, "carol@example.com"))
        self.assertEqual(findings, [])

    def test_missing_city_only(self):
        _c, findings = audit_text(
            HEADER + row(1, "carol@example.com",
                         billing_city=""))
        self.assertEqual(rules(findings), ["missing-billing"])
        self.assertIn("billing_city", findings[0].message)


class FailedOrdersTests(unittest.TestCase):
    """Customers whose orders all failed or were cancelled."""

    def test_failed_only_is_error(self):
        _c, findings = audit_text(
            HEADER + row(1, "dave@example.net", orders="2",
                         total="0.00", status="failed"))
        self.assertEqual(rules(findings), ["only-failed-orders"])
        self.assertEqual(findings[0].severity, "error")

    def test_cancelled_only_is_error(self):
        _c, findings = audit_text(
            HEADER + row(1, "dave@example.net", orders="1",
                         total="0.00", status="cancelled"))
        self.assertEqual(rules(findings), ["only-failed-orders"])

    def test_failed_but_spent_something_passes(self):
        _c, findings = audit_text(
            HEADER + row(1, "dave@example.net", orders="2",
                         total="40.00", status="failed"))
        self.assertEqual(findings, [])

    def test_completed_with_zero_total_passes(self):
        _c, findings = audit_text(
            HEADER + row(1, "dave@example.net", orders="1",
                         total="0.00", status="completed"))
        self.assertEqual(findings, [])


class MoneyAndCountTests(unittest.TestCase):
    """Totals and order counts."""

    def test_negative_total_is_error(self):
        _c, findings = audit_text(
            HEADER + row(1, "henry@example.com", total="-5.00"))
        self.assertEqual(rules(findings), ["negative-total"])

    def test_invalid_orders_count_is_warning(self):
        _c, findings = audit_text(
            HEADER + row(1, "grace@example.com", orders="three"))
        self.assertEqual(rules(findings), ["invalid-orders-count"])
        self.assertEqual(findings[0].severity, "warning")

    def test_invalid_total_is_warning(self):
        _c, findings = audit_text(
            HEADER + row(1, "grace@example.com", total="abc"))
        self.assertEqual(rules(findings), ["invalid-total-spent"])

    def test_missing_id_is_error(self):
        _c, findings = audit_text(HEADER + row("", "alice@example.com"))
        self.assertEqual(rules(findings), ["missing-id"])

    def test_missing_name_is_warning(self):
        _c, findings = audit_text(
            HEADER + row(1, "alice@example.com", first="", last=""))
        self.assertEqual(rules(findings), ["missing-name"])

    def test_last_name_only_passes_name_check(self):
        _c, findings = audit_text(
            HEADER + row(1, "alice@example.com", first=""))
        self.assertEqual(findings, [])


class FileHandlingTests(unittest.TestCase):
    """Malformed rows, BOM headers, and blank lines."""

    def test_malformed_row_is_error_and_skipped(self):
        text = HEADER + row(1, "alice@example.com") + "2,bob@example.com\n"
        customers, findings = audit_text(text)
        self.assertEqual(len(customers), 1)
        self.assertEqual(rules(findings), ["malformed-row"])

    def test_blank_lines_skipped(self):
        text = HEADER + "\n" + row(1, "alice@example.com") + "\n"
        customers, findings = audit_text(text)
        self.assertEqual(len(customers), 1)
        self.assertEqual(findings, [])

    def test_bom_header(self):
        text = "\ufeff" + HEADER + row(1, "alice@example.com")
        _c, findings = audit_text(text)
        self.assertEqual(findings, [])

    def test_empty_file(self):
        customers, findings = audit_text("")
        self.assertEqual(customers, [])
        self.assertEqual(findings, [])

    def test_header_only(self):
        customers, findings = audit_text(HEADER)
        self.assertEqual(customers, [])
        self.assertEqual(findings, [])


class OutputTests(unittest.TestCase):
    """Summary, JSON output, and CLI exit codes."""

    def test_summarize_counts(self):
        customers, findings = audit_text(
            HEADER + row(1, "alice@example.com")
            + row(2, "ALICE@example.com", username="alice2"))
        summary = wcd.summarize(customers, findings)
        self.assertEqual(summary, {"customers": 2, "findings": 1,
                                   "errors": 1, "warnings": 0})

    def test_json_output_shape(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "customers.csv")
        customers, findings = wcd.audit(path)
        summary = wcd.summarize(customers, findings)
        data = json.loads(wcd.format_json(customers, findings, summary))
        self.assertEqual(data["summary"]["customers"], 12)
        self.assertEqual(data["summary"]["findings"], 19)
        self.assertEqual(data["summary"]["errors"], 8)
        self.assertEqual(data["summary"]["warnings"], 11)
        self.assertEqual(len(data["findings"]), 19)
        self.assertEqual(data["findings"][0]["rule"], "malformed-row")

    def test_text_output_ends_with_summary(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        customers, findings = wcd.audit(path)
        summary = wcd.summarize(customers, findings)
        output = wcd.format_text(customers, findings, summary)
        self.assertIn("Customers: 3, findings: 0, errors: 0, "
                      "warnings: 0", output)
        self.assertIn("All customers clean.", output)

    def test_check_exits_1_on_errors(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "customers.csv")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(wcd.main([path, "--check"]), 1)

    def test_check_exits_0_on_clean(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(wcd.main([path, "--check"]), 0)

    def test_check_passes_warnings_but_strict_fails(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "warnings-only.csv")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(wcd.main([path, "--check"]), 0)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(wcd.main([path, "--check", "--strict"]), 1)

    def test_missing_file_exits_2(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(wcd.main(["no-such-file.csv"]), 2)

    def test_out_flag_writes_file(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as handle:
            out_path = handle.name
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    wcd.main([path, "--out", out_path]), 0)
            with open(out_path, encoding="utf-8") as handle:
                self.assertIn("All customers clean.", handle.read())
        finally:
            os.unlink(out_path)


class SampleTests(unittest.TestCase):
    """Sample file counts."""

    def test_bad_sample_counts(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "customers.csv")
        customers, findings = wcd.audit(path)
        summary = wcd.summarize(customers, findings)
        self.assertEqual(summary, {"customers": 12, "findings": 19,
                                   "errors": 8, "warnings": 11})

    def test_clean_sample_counts(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        customers, findings = wcd.audit(path)
        self.assertEqual(wcd.summarize(customers, findings),
                         {"customers": 3, "findings": 0, "errors": 0,
                          "warnings": 0})

    def test_warnings_only_sample_counts(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "warnings-only.csv")
        customers, findings = wcd.audit(path)
        self.assertEqual(wcd.summarize(customers, findings),
                         {"customers": 2, "findings": 3, "errors": 0,
                          "warnings": 3})


if __name__ == "__main__":
    unittest.main()
