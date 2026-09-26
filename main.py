import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from dotenv import load_dotenv
from flask import Flask, request
from google.oauth2.service_account import Credentials
from twilio.twiml.messaging_response import MessagingResponse


load_dotenv()


# ============================================================
# Configuration
# ============================================================

JAKARTA_TZ = ZoneInfo("Asia/Jakarta")

ALLOWED_CATEGORIES = {
    "makan",
    "transportasi",
    "tagihan",
    "keluarga",
    "donasi",
    "personal",
    "lainnya",
}

EXPENSE_PATTERN = re.compile(
    r"^(\d+)\s*(k|rb|ribu)?\s+(\S+)\s+(.+?)(?:\s+@(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?)?$",
    re.IGNORECASE,
)

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ============================================================
# Expense Parser
# ============================================================

def parse_expense(raw_text):
    """
    Parse a WhatsApp expense message.

    Supported formats:
        25k makan nasi goreng
        25rb makan nasi goreng
        25ribu makan nasi goreng

        25k makan nasi goreng @2026-09-25
        25k makan nasi goreng @2026-09-25 19:30

    If no date/time is provided, the current Jakarta time is used.

    Returns:
        (expense_dict, None) on success
        (None, error_message) on failure
    """

    match = EXPENSE_PATTERN.match(raw_text.strip())

    if not match:
        return None, (
            "⚠️ Invalid format. Use: <amount> <category> <description>\n"
            "Example: 25k makan nasi goreng"
        )

    amount_str, unit, category, description, date_str, time_str = match.groups()

    category = category.lower()

    if category not in ALLOWED_CATEGORIES:
        allowed_categories = "\n".join(
            f"• {category}"
            for category in sorted(ALLOWED_CATEGORIES)
        )

        return None, (
            f"❌ Category '{category}' is invalid.\n"
            f"Allowed categories:\n"
            f"{allowed_categories}"
        )

    amount = int(amount_str)

    if unit:
        amount *= 1000

    now = datetime.now(JAKARTA_TZ)

    if date_str:
        try:
            if time_str:
                expense_datetime = datetime.strptime(
                    f"{date_str} {time_str}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=JAKARTA_TZ)

            else:
                expense_datetime = datetime.strptime(
                    date_str,
                    "%Y-%m-%d",
                ).replace(
                    hour=now.hour,
                    minute=now.minute,
                    second=now.second,
                    microsecond=0,
                    tzinfo=JAKARTA_TZ,
                )

        except ValueError:
            return None, (
                "⚠️ Invalid date/time. Use:\n"
                "@YYYY-MM-DD\n"
                "or\n"
                "@YYYY-MM-DD HH:MM\n"
                "Example: @2026-09-25 19:30"
            )

    else:
        expense_datetime = now

    return {
        "amount": amount,
        "category": category,
        "item": description.strip().capitalize(),
        "expense_datetime": expense_datetime,
    }, None


# ============================================================
# Google Sheets
# ============================================================

def get_google_sheet():
    """
    Authenticate with Google and return Sheet1.
    """

    spreadsheet_id = os.environ["SPREADSHEET_ID"]

    credentials = Credentials.from_service_account_file(
        "credentials.json",
        scopes=GOOGLE_SCOPES,
    )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet("Sheet1")

    return worksheet


def build_sheet_row(raw_text, expense):
    """
    Convert a parsed expense into the exact Google Sheet row format.

    Column order:
        A Timestamp
        B Day
        C Month
        D Year
        E Day_of_Week
        F Raw_Text
        G Item
        H Amount_IDR
        I Category
    """

    expense_datetime = expense["expense_datetime"]

    return [
        expense_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        expense_datetime.day,
        expense_datetime.strftime("%b"),
        expense_datetime.year,
        expense_datetime.strftime("%A"),
        raw_text,
        expense["item"],
        expense["amount"],
        expense["category"],
    ]


def append_expense(raw_text, expense):
    """
    Append one parsed expense to Google Sheets.
    """

    worksheet = get_google_sheet()

    row = build_sheet_row(raw_text, expense)

    worksheet.append_row(
        row,
        value_input_option="USER_ENTERED",
    )


# ============================================================
# Flask / Twilio Webhook
# ============================================================

app = Flask(__name__)


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Receive an incoming WhatsApp message from Twilio.
    """

    raw_text = request.form.get("Body", "").strip()

    response = MessagingResponse()

    if not raw_text:
        response.message(
            "⚠️ Empty message. Use: <amount> <category> <description>\n"
            "Example: 25k makan nasi goreng"
        )

        return str(response)

    expense, error = parse_expense(raw_text)

    if error:
        response.message(error)
        return str(response)

    try:
        append_expense(raw_text, expense)

    except Exception:
        app.logger.exception(
            "Failed to append expense to Google Sheets"
        )

        response.message(
            "⚠️ Something went wrong while saving your expense. "
            "Please try again."
        )

        return str(response), 500

    response.message(
        f"✅ Added: Rp{expense['amount']:,}\n"
        f"Category: {expense['category']}\n"
        f"Item: {expense['item']}"
    )

    return str(response)


# ============================================================
# Health Check
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    """
    Simple health check for deployment monitoring.
    """

    return {"status": "ok"}, 200


# ============================================================
# Local Development
# ============================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
    )