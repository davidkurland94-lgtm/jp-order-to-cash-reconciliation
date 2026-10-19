"""
generate_o2c_data.py

Creates a small, messy, realistic ORDER-TO-CASH dataset for practicing dbt.

It writes six CSV files into ./data/  (load these into BigQuery)
and Excel-friendly copies into ./data/excel_view/  (open these to look around)

    Source files (what your dbt project will clean up):
        customers.csv           master list of customers
        crm_orders.csv          what sales recorded       (Salesforce-style)
        erp_invoices.csv        what finance billed       (Visma-style)
        bank_transactions.csv   what money actually arrived

    Answer keys (what a correct dbt project should conclude):
        expected_invoice_status.csv    final status of every invoice
        expected_payment_matches.csv   which payment belongs to which invoice

Because this script PLANTS every problem on purpose, it also knows the right
answer. Copy the two answer keys into your dbt project's seeds/ folder and
write tests that compare your models against them.

Run:   python generate_o2c_data.py
Needs: Python 3.9+ standard library only (nothing to pip install).
"""

import csv
import random
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# SETTINGS YOU CAN CHANGE
# ---------------------------------------------------------------------------

RANDOM_SEED = 42                 # same seed -> exactly the same data every run
NUMBER_OF_ORDERS = 300
FIRST_ORDER_DATE = date(2026, 4, 1)
LAST_ORDER_DATE = date(2026, 9, 15)
AS_OF_DATE = date(2026, 10, 1)   # "today" in the dataset; bank data stops here
OUTPUT_FOLDER = Path("data")

# How often each payment situation happens.
# These are relative weights, so they don't need to add up to 100.
PAYMENT_SCENARIO_WEIGHTS = {
    "clean_with_memo": 40,   # paid in full on time, invoice number in the memo
    "clean_no_memo": 20,     # paid in full on time, memo left empty
    "fee_deducted": 15,      # customer subtracted the bank transfer fee
    "combined": 8,           # one payment covers two invoices
    "partial": 6,            # only part of the amount was paid
    "late": 5,               # paid in full, but after the due date
    "duplicate": 3,          # customer accidentally paid twice
    "never_paid": 3,         # nothing arrived
}

ORDER_WITHOUT_INVOICE_RATE = 0.03   # sales booked it, finance never billed it
INVOICE_WITHOUT_ORDER_COUNT = 5     # manual invoices with no CRM order behind them
AMOUNT_MISMATCH_RATE = 0.04         # invoice amount differs from the CRM amount
UNKNOWN_PAYMENT_COUNT = 4           # money from someone not in the customer list

# Typical Japanese bank transfer fees (振込手数料) that customers deduct
BANK_TRANSFER_FEES = [330, 440, 660, 880]


# ---------------------------------------------------------------------------
# CUSTOMERS
# ---------------------------------------------------------------------------

@dataclass
class Customer:
    customer_id: str
    official_name: str   # the registered legal name
    short_name: str      # how sales people usually type it
    bank_name: str       # how it shows up on a bank statement


# Japanese bank statements use half-width katakana with NO small kana
# (ョ becomes ﾖ, ィ becomes ｲ). The legal-entity marker follows the name:
#     株式会社 BEFORE the name  ->  "ｶ)" at the start    e.g. ｶ)ｻｸﾗﾃﾞﾝｷ
#     株式会社 AFTER the name   ->  "(ｶ" at the end      e.g. ﾎｸﾄｼｽﾃﾑ(ｶ
#     合同会社 BEFORE the name  ->  "ﾄﾞ)" at the start
CUSTOMERS = [
    Customer("C001", "株式会社サクラ電機", "サクラ電機", "ｶ)ｻｸﾗﾃﾞﾝｷ"),
    Customer("C002", "東京ロジスティクス株式会社", "東京ロジスティクス", "ﾄｳｷﾖｳﾛｼﾞｽﾃｲｸｽ(ｶ"),
    Customer("C003", "合同会社ミドリ商事", "ミドリ商事", "ﾄﾞ)ﾐﾄﾞﾘｼﾖｳｼﾞ"),
    Customer("C004", "株式会社アオイ食品", "アオイ食品", "ｶ)ｱｵｲｼﾖｸﾋﾝ"),
    Customer("C005", "大阪精密工業株式会社", "大阪精密工業", "ｵｵｻｶｾｲﾐﾂｺｳｷﾞﾖｳ(ｶ"),
    Customer("C006", "株式会社ヒカリ設計", "ヒカリ設計", "ｶ)ﾋｶﾘｾﾂｹｲ"),
    Customer("C007", "北斗システム株式会社", "北斗システム", "ﾎｸﾄｼｽﾃﾑ(ｶ"),
    Customer("C008", "株式会社ミナトデザイン", "ミナトデザイン", "ｶ)ﾐﾅﾄﾃﾞｻﾞｲﾝ"),
    Customer("C009", "富士メディカル株式会社", "富士メディカル", "ﾌｼﾞﾒﾃﾞｲｶﾙ(ｶ"),
    Customer("C010", "合同会社ソラ企画", "ソラ企画", "ﾄﾞ)ｿﾗｷｶｸ"),
]

# Payers that match NO customer (refunds to individuals, bank interest, etc.)
UNKNOWN_PAYERS = ["ﾔﾏﾀﾞ ﾀﾛｳ", "ｶ)ﾌﾞﾙｰｵｰｼﾔﾝ", "ｽｽﾞｷ ﾊﾅｺ", "ﾘｿｸ"]


# ---------------------------------------------------------------------------
# SMALL HELPERS
# ---------------------------------------------------------------------------

def random_date_between(start: date, end: date) -> date:
    """Pick a random day from start to end (both included)."""
    days_between = (end - start).days
    return start + timedelta(days=random.randint(0, days_between))


def end_of_next_month(any_day: date) -> date:
    """
    Standard Japanese payment terms: 月末締め翌月末払い
    (close the books at month end, payment due at the end of the NEXT month).
    """
    first_of_next_month = (any_day.replace(day=1) + timedelta(days=32)).replace(day=1)
    first_of_month_after = (first_of_next_month + timedelta(days=32)).replace(day=1)
    return first_of_month_after - timedelta(days=1)


def erp_style_name(customer: Customer) -> str:
    """Finance staff type the same company several different ways (planted problem)."""
    with_symbol = customer.official_name.replace("株式会社", "㈱")
    return random.choice([customer.official_name, with_symbol, customer.short_name])


def write_csv(filename: str, rows: list, columns: list) -> None:
    """
    Write a list of dictionaries to CSV TWICE, keeping only the listed columns:

      data/<file>             plain utf-8      -> load THESE into BigQuery / dbt
      data/excel_view/<file>  utf-8 with BOM   -> open THESE in Excel, just to look

    Why two copies? A BOM is an invisible marker at the very start of a file
    that tells Excel "this is UTF-8". Without it, Excel guesses the wrong
    encoding and Japanese text turns into garbage. But BigQuery treats that
    same marker as part of the first column name, so it must NOT be in the
    files you load.
    """
    copies = [
        (OUTPUT_FOLDER / filename, "utf-8"),
        (OUTPUT_FOLDER / "excel_view" / filename, "utf-8-sig"),   # "-sig" adds the BOM
    ]
    for path, encoding in copies:
        with open(path, "w", newline="", encoding=encoding) as file:
            writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    print(f"  wrote {len(rows):>4} rows -> {filename}  (+ excel_view copy)")


# ---------------------------------------------------------------------------
# STEP 1: CRM ORDERS (what sales recorded)
# ---------------------------------------------------------------------------

def make_crm_orders() -> list:
    order_dates = sorted(
        random_date_between(FIRST_ORDER_DATE, LAST_ORDER_DATE)
        for _ in range(NUMBER_OF_ORDERS)
    )

    orders = []
    for order_number, order_date in enumerate(order_dates, start=1001):
        customer = random.choice(CUSTOMERS)
        orders.append({
            "order_id": f"O-{order_number}",
            "account_name": customer.short_name,
            "amount_jpy": random.randint(5, 200) * 11_000,   # ¥55,000 – ¥2,200,000
            "order_date": order_date,
            "customer": customer,   # helper for later steps; not written to the CSV
        })
    return orders


# ---------------------------------------------------------------------------
# STEP 2: ERP INVOICES (what finance billed)
# ---------------------------------------------------------------------------

def build_invoice(customer, order_id, amount, invoice_date, invoice_problem) -> dict:
    return {
        "invoice_id": None,   # numbered later, after sorting by date
        "order_id": order_id,
        "customer_name": erp_style_name(customer),
        "invoice_date": invoice_date,
        "due_date": end_of_next_month(invoice_date),
        "amount_jpy": amount,
        "customer": customer,
        "invoice_problem": invoice_problem,
    }


def make_erp_invoices(orders: list) -> list:
    invoices = []

    for order in orders:
        if random.random() < ORDER_WITHOUT_INVOICE_RATE:
            continue   # PLANTED: finance never billed this order

        amount = order["amount_jpy"]
        problem = ""
        if random.random() < AMOUNT_MISMATCH_RATE:
            # PLANTED: a discount was applied in the ERP but never updated in the CRM
            amount -= random.choice([1_100, 5_500, 11_000])
            problem = "amount_differs_from_order"

        invoice_date = order["order_date"] + timedelta(days=random.randint(0, 5))
        invoices.append(build_invoice(order["customer"], order["order_id"], amount, invoice_date, problem))

    for _ in range(INVOICE_WITHOUT_ORDER_COUNT):
        # PLANTED: a manual invoice with no CRM order behind it
        customer = random.choice(CUSTOMERS)
        invoice_date = random_date_between(FIRST_ORDER_DATE, LAST_ORDER_DATE)
        amount = random.randint(1, 10) * 11_000
        invoices.append(build_invoice(customer, "", amount, invoice_date, "no_matching_order"))

    # Number the invoices in date order, like a real ERP would
    invoices.sort(key=lambda invoice: invoice["invoice_date"])
    for invoice_number, invoice in enumerate(invoices, start=2001):
        invoice["invoice_id"] = f"INV-{invoice_number}"
    return invoices


# ---------------------------------------------------------------------------
# STEP 3: BANK PAYMENTS (what money actually arrived) + the answer key
# ---------------------------------------------------------------------------

def add_payment(payments, paid_on, amount, payer_name, memo, invoices_covered, note):
    payments.append({
        "paid_on": paid_on,
        "amount_jpy": amount,
        "payer_name": payer_name,
        "memo": memo,
        "invoice_ids": [invoice["invoice_id"] for invoice in invoices_covered],
        "note": note,   # only used in the answer key
    })


def record_status(invoice_status, invoice, expected_status, open_amount, scenario):
    invoice_status.append({
        "invoice_id": invoice["invoice_id"],
        "expected_status": expected_status,
        "expected_open_amount_jpy": open_amount,
        "planted_scenario": scenario,
        "invoice_problem": invoice["invoice_problem"],
    })


def pay_one_invoice(invoice, scenario, payments, invoice_status):
    """Create the bank row(s) for a single invoice, based on its scenario."""
    amount = invoice["amount_jpy"]
    payer = invoice["customer"].bank_name
    on_time_date = invoice["due_date"] - timedelta(days=random.randint(0, 5))

    if scenario == "clean_with_memo":
        memo = invoice["invoice_id"]
        if random.random() < 0.3:
            memo = memo.replace("-", "")   # PLANTED: "INV2045" instead of "INV-2045"
        add_payment(payments, on_time_date, amount, payer, memo, [invoice], scenario)
        record_status(invoice_status, invoice, "paid", 0, scenario)

    elif scenario == "clean_no_memo":
        add_payment(payments, on_time_date, amount, payer, "", [invoice], scenario)
        record_status(invoice_status, invoice, "paid", 0, scenario)

    elif scenario == "fee_deducted":
        fee = random.choice(BANK_TRANSFER_FEES)
        add_payment(payments, on_time_date, amount - fee, payer, "", [invoice], scenario)
        # The fee is booked as an expense, so the invoice counts as settled
        record_status(invoice_status, invoice, "paid_fee_deducted", 0, scenario)

    elif scenario == "partial":
        share_paid = random.choice([0.3, 0.5, 0.7])
        paid_amount = int(amount * share_paid)
        paid_amount -= paid_amount % 1_000   # round down to the nearest ¥1,000
        memo = f"{invoice['due_date'].month}ｶﾞﾂﾌﾞﾝ"   # "the payment for month X"
        add_payment(payments, on_time_date, paid_amount, payer, memo, [invoice], scenario)
        record_status(invoice_status, invoice, "partial", amount - paid_amount, scenario)

    elif scenario == "late":
        late_date = invoice["due_date"] + timedelta(days=random.randint(10, 60))
        if late_date <= AS_OF_DATE:
            add_payment(payments, late_date, amount, payer, "", [invoice], scenario)
            record_status(invoice_status, invoice, "paid", 0, scenario)
        else:
            # The payment will come someday, but it hasn't arrived as of today
            record_status(invoice_status, invoice, "unpaid_overdue", amount, scenario)

    elif scenario == "duplicate":
        memo = invoice["invoice_id"]
        second_date = on_time_date + timedelta(days=random.randint(0, 1))
        add_payment(payments, on_time_date, amount, payer, memo, [invoice], scenario)
        add_payment(payments, second_date, amount, payer, memo, [invoice], scenario)
        # Negative open amount = we owe the customer a refund
        record_status(invoice_status, invoice, "overpaid", -amount, scenario)

    elif scenario == "never_paid":
        record_status(invoice_status, invoice, "unpaid_overdue", amount, scenario)


def pay_two_invoices_together(first, second, payments, invoice_status):
    """PLANTED: one bank transfer covering two invoices from the same customer."""
    later_due_date = max(first["due_date"], second["due_date"])
    paid_on = later_due_date - timedelta(days=random.randint(0, 5))
    total = first["amount_jpy"] + second["amount_jpy"]
    add_payment(payments, paid_on, total, first["customer"].bank_name, "",
                [first, second], "combined")
    record_status(invoice_status, first, "paid", 0, "combined")
    record_status(invoice_status, second, "paid", 0, "combined")


def make_bank_payments(invoices: list):
    payments = []
    invoice_status = []
    waiting_for_partner = {}   # customer_id -> a "combined" invoice waiting for a second one

    scenario_names = list(PAYMENT_SCENARIO_WEIGHTS.keys())
    scenario_weights = list(PAYMENT_SCENARIO_WEIGHTS.values())

    for invoice in invoices:
        if invoice["due_date"] > AS_OF_DATE:
            # Not due yet, so no payment is expected
            record_status(invoice_status, invoice, "not_yet_due", invoice["amount_jpy"], "")
            continue

        scenario = random.choices(scenario_names, weights=scenario_weights)[0]

        if scenario == "combined":
            customer_id = invoice["customer"].customer_id
            if customer_id in waiting_for_partner:
                partner = waiting_for_partner.pop(customer_id)
                pay_two_invoices_together(partner, invoice, payments, invoice_status)
            else:
                waiting_for_partner[customer_id] = invoice
            continue

        pay_one_invoice(invoice, scenario, payments, invoice_status)

    # Any "combined" invoice that never found a partner is just paid normally
    for leftover_invoice in waiting_for_partner.values():
        pay_one_invoice(leftover_invoice, "clean_no_memo", payments, invoice_status)

    # PLANTED: money from people who are not customers at all
    for _ in range(UNKNOWN_PAYMENT_COUNT):
        payer = random.choice(UNKNOWN_PAYERS)
        amount = random.randint(1, 500) if payer == "ﾘｿｸ" else random.randint(1, 50) * 1_000
        paid_on = random_date_between(FIRST_ORDER_DATE, AS_OF_DATE)
        add_payment(payments, paid_on, amount, payer, "", [], "unknown_payer")

    invoice_status.sort(key=lambda row: row["invoice_id"])
    return payments, invoice_status


# ---------------------------------------------------------------------------
# STEP 4: NUMBER THE BANK ROWS + BUILD THE PAYMENT ANSWER KEY
# ---------------------------------------------------------------------------

def finalize_bank_transactions(payments: list):
    """Sort payments by date like a bank statement, then give each a transaction id."""
    payments.sort(key=lambda payment: payment["paid_on"])
    payment_matches = []

    for number, payment in enumerate(payments, start=1):
        payment["txn_id"] = f"T-{number:05d}"

        if payment["invoice_ids"]:
            for invoice_id in payment["invoice_ids"]:
                payment_matches.append({
                    "txn_id": payment["txn_id"],
                    "invoice_id": invoice_id,
                    "note": payment["note"],
                })
        else:
            payment_matches.append({
                "txn_id": payment["txn_id"],
                "invoice_id": "",
                "note": payment["note"],
            })

    return payments, payment_matches


# ---------------------------------------------------------------------------
# RUN EVERYTHING
# ---------------------------------------------------------------------------

def main():
    random.seed(RANDOM_SEED)
    (OUTPUT_FOLDER / "excel_view").mkdir(parents=True, exist_ok=True)

    orders = make_crm_orders()
    invoices = make_erp_invoices(orders)
    payments, invoice_status = make_bank_payments(invoices)
    bank_transactions, payment_matches = finalize_bank_transactions(payments)

    print("Writing source files:")
    write_csv("customers.csv", [asdict(customer) for customer in CUSTOMERS],
              ["customer_id", "official_name", "short_name", "bank_name"])
    write_csv("crm_orders.csv", orders,
              ["order_id", "account_name", "amount_jpy", "order_date"])
    write_csv("erp_invoices.csv", invoices,
              ["invoice_id", "order_id", "customer_name", "invoice_date", "due_date", "amount_jpy"])
    write_csv("bank_transactions.csv", bank_transactions,
              ["txn_id", "paid_on", "amount_jpy", "payer_name", "memo"])

    print("Writing answer keys:")
    write_csv("expected_invoice_status.csv", invoice_status,
              ["invoice_id", "expected_status", "expected_open_amount_jpy",
               "planted_scenario", "invoice_problem"])
    write_csv("expected_payment_matches.csv", payment_matches,
              ["txn_id", "invoice_id", "note"])

    invoiced_order_ids = {invoice["order_id"] for invoice in invoices}
    never_invoiced = [order for order in orders if order["order_id"] not in invoiced_order_ids]

    print("\nInvoice status counts:")
    for status, count in Counter(row["expected_status"] for row in invoice_status).most_common():
        print(f"  {status:<20} {count}")
    print(f"\nOrders never invoiced: {len(never_invoiced)}")


if __name__ == "__main__":
    main()
