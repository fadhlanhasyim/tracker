import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
import requests
from dotenv import load_dotenv
from flask import Flask, request
from google.oauth2.service_account import Credentials


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

STATS_PATTERN = re.compile(
    r"^/stats(?:\s+(\d{4}-\d{2}-\d{2}))?(?:\s+(\d{4}-\d{2}-\d{2}))?$",
    re.IGNORECASE,
)

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

TELEGRAM_API_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
)


# ============================================================
# Expense Parser
# ============================================================

def parse_expense(raw_text):
    """
    Parse a Telegram expense message.

    Supported formats:
        25k makan nasi goreng
        25rb makan nasi goreng
        25ribu makan nasi goreng

        25k makan nasi goreng @2026-09-25
        25k makan nasi goreng @2026-09-25 19:30

    If no date/time is provided, the current Jakarta time is used.
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

    Local:
        Uses credentials.json

    Production:
        Uses GOOGLE_CREDENTIALS_JSON environment variable.
    """

    spreadsheet_id = os.environ["SPREADSHEET_ID"]

    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")

    if credentials_json:
        credentials = Credentials.from_service_account_info(
            json.loads(credentials_json),
            scopes=GOOGLE_SCOPES,
        )
    else:
        credentials = Credentials.from_service_account_file(
            "credentials.json",
            scopes=GOOGLE_SCOPES,
        )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet("Sheet1")

    return worksheet


def build_sheet_row(raw_text, expense, update_id):
    """
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
    J Telegram_Update_ID
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
        update_id,
    ]


def is_update_processed(worksheet, update_id):
    """
    Check whether this Telegram update has already been processed.

    Telegram_Update_ID is stored in column J.
    """

    update_ids = worksheet.col_values(10)

    return str(update_id) in update_ids


def append_expense(raw_text, expense, update_id):
    """
    Append one parsed expense to Google Sheets.
    """

    worksheet = get_google_sheet()

    row = build_sheet_row(
        raw_text,
        expense,
        update_id,
    )

    worksheet.append_row(
        row,
        value_input_option="USER_ENTERED",
    )


# ============================================================
# Statistics
# ============================================================

def get_stats_date_range(start_date_str=None, end_date_str=None):
    """
    Determine the requested stats date range.

    /stats
        Last 30 days, including today.

    /stats YYYY-MM-DD
        That single date.

    /stats YYYY-MM-DD YYYY-MM-DD
        Inclusive date range.
    """

    today = datetime.now(JAKARTA_TZ).date()

    if not start_date_str and not end_date_str:
        end_date = today
        start_date = today - timedelta(days=29)

        return start_date, end_date, None

    try:
        if start_date_str and not end_date_str:
            start_date = datetime.strptime(
                start_date_str,
                "%Y-%m-%d",
            ).date()

            end_date = start_date

        elif start_date_str and end_date_str:
            start_date = datetime.strptime(
                start_date_str,
                "%Y-%m-%d",
            ).date()

            end_date = datetime.strptime(
                end_date_str,
                "%Y-%m-%d",
            ).date()

        else:
            return None, None, (
                "⚠️ Invalid stats format.\n\n"
                "Use:\n"
                "/stats\n"
                "/stats YYYY-MM-DD\n"
                "/stats YYYY-MM-DD YYYY-MM-DD"
            )

    except ValueError:
        return None, None, (
            "⚠️ Invalid date. Use YYYY-MM-DD.\n"
            "Example: /stats 2026-09-01 2026-09-28"
        )

    if start_date > end_date:
        return None, None, (
            "⚠️ Start date cannot be after end date."
        )

    return start_date, end_date, None


def calculate_stats(worksheet, start_date, end_date):
    """
    Calculate expense statistics from Sheet1.

    Uses the Timestamp column as the expense datetime.
    """

    rows = worksheet.get_all_values()

    if len(rows) <= 1:
        return {
            "total": 0,
            "transactions": 0,
            "categories": {
                category: {
                    "amount": 0,
                    "transactions": 0,
                }
                for category in sorted(ALLOWED_CATEGORIES)
            },
        }

    stats = {
        "total": 0,
        "transactions": 0,
        "categories": {
            category: {
                "amount": 0,
                "transactions": 0,
            }
            for category in sorted(ALLOWED_CATEGORIES)
        },
    }

    for row in rows[1:]:
        if len(row) < 9:
            continue

        timestamp = row[0]
        category = row[8].strip().lower()

        if not timestamp or category not in ALLOWED_CATEGORIES:
            continue

        try:
            expense_datetime = datetime.strptime(
                timestamp,
                "%Y-%m-%d %H:%M:%S",
            )

            expense_date = expense_datetime.date()

        except ValueError:
            continue

        if not (start_date <= expense_date <= end_date):
            continue

        try:
            amount = int(float(row[7]))
        except (ValueError, TypeError):
            continue

        stats["total"] += amount
        stats["transactions"] += 1

        stats["categories"][category]["amount"] += amount
        stats["categories"][category]["transactions"] += 1

    return stats


def format_rupiah(amount):
    """
    Format an integer as Indonesian Rupiah.
    """

    return f"Rp{amount:,}"


def format_stats_message(start_date, end_date, stats):
    """
    Create the Telegram response for /stats.
    """

    if start_date == end_date:
        date_range = start_date.strftime("%Y-%m-%d")
    else:
        date_range = (
            f"{start_date.strftime('%Y-%m-%d')} → "
            f"{end_date.strftime('%Y-%m-%d')}"
        )

    total = stats["total"]
    transactions = stats["transactions"]

    lines = [
        "📊 Expense Stats",
        date_range,
        "",
        f"Total: {format_rupiah(total)}",
        f"Transactions: {transactions}",
    ]

    if transactions > 0:
        average = total / transactions

        lines.append(
            f"Average: {format_rupiah(round(average))}"
        )

    lines.append("")

    for category in sorted(ALLOWED_CATEGORIES):
        category_stats = stats["categories"][category]

        amount = category_stats["amount"]
        category_transactions = category_stats["transactions"]

        if total > 0:
            percentage = amount / total * 100
        else:
            percentage = 0

        lines.append(
            f"{category}: "
            f"{format_rupiah(amount)} · "
            f"{percentage:.1f}% · "
            f"{category_transactions} transactions"
        )

    return "\n".join(lines)


def handle_stats_command(worksheet, raw_text):
    """
    Parse and execute /stats.
    """

    match = STATS_PATTERN.match(raw_text.strip())

    if not match:
        return (
            "⚠️ Invalid stats format.\n\n"
            "Use:\n"
            "/stats\n"
            "/stats YYYY-MM-DD\n"
            "/stats YYYY-MM-DD YYYY-MM-DD"
        )

    start_date_str, end_date_str = match.groups()

    start_date, end_date, error = get_stats_date_range(
        start_date_str,
        end_date_str,
    )

    if error:
        return error

    stats = calculate_stats(
        worksheet,
        start_date,
        end_date,
    )

    return format_stats_message(
        start_date,
        end_date,
        stats,
    )


# ============================================================
# Telegram
# ============================================================

def send_telegram_message(chat_id, text):
    """
    Send a message to a Telegram chat.
    """

    response = requests.post(
        f"{TELEGRAM_API_URL}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
        },
        timeout=10,
    )

    response.raise_for_status()


# ============================================================
# Flask
# ============================================================

app = Flask(__name__)


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    """
    Receive an incoming Telegram message.
    """

    update = request.get_json(silent=True)

    if not update:
        return {"ok": True}, 200

    update_id = update.get("update_id")

    if update_id is None:
        return {"ok": True}, 200

    message = update.get("message")

    if not message:
        return {"ok": True}, 200

    chat = message.get("chat")
    raw_text = message.get("text", "").strip()

    if not chat:
        return {"ok": True}, 200

    chat_id = chat["id"]

    # --------------------------------------------------------
    # Help command
    # --------------------------------------------------------

    if raw_text.lower() == "/help":
        send_telegram_message(
            chat_id,
            "💰 Expense Tracker\n\n"
            "Commands:\n"
            "/help - Show this help\n"
            "/stats - Stats for the last 30 days\n"
            "/stats YYYY-MM-DD - Stats for one day\n"
            "/stats YYYY-MM-DD YYYY-MM-DD - Stats for a date range\n\n"
            "Expense format:\n"
            "<amount> <category> <description>\n\n"
            "Example:\n"
            "25k makan nasi goreng\n\n"
            "Categories:\n"
            "• makan\n"
            "• transportasi\n"
            "• tagihan\n"
            "• keluarga\n"
            "• donasi\n"
            "• personal\n"
            "• lainnya\n\n"
            "Units:\n"
            "• k\n"
            "• rb\n"
            "• ribu\n\n"
            "Optional date/time:\n"
            "@YYYY-MM-DD\n"
            "@YYYY-MM-DD HH:MM\n\n"
            "Example:\n"
            "32k makan Kopi Spanish Latte "
            "@2026-09-25 13:00"
        )

        return {"ok": True}, 200

    # --------------------------------------------------------
    # Get worksheet
    # --------------------------------------------------------

    try:
        worksheet = get_google_sheet()

    except Exception:
        app.logger.exception(
            "Failed to connect to Google Sheets"
        )

        send_telegram_message(
            chat_id,
            "⚠️ Something went wrong while connecting "
            "to Google Sheets. Please try again.",
        )

        return {"ok": True}, 200

    # --------------------------------------------------------
    # Stats command
    # --------------------------------------------------------

    if raw_text.lower().startswith("/stats"):
        try:
            response = handle_stats_command(
                worksheet,
                raw_text,
            )

            send_telegram_message(
                chat_id,
                response,
            )

        except Exception:
            app.logger.exception(
                "Failed to calculate expense statistics"
            )

            send_telegram_message(
                chat_id,
                "⚠️ Something went wrong while calculating "
                "your expense stats.",
            )

        return {"ok": True}, 200

    # --------------------------------------------------------
    # Check for duplicate Telegram update
    # --------------------------------------------------------

    try:
        if is_update_processed(
            worksheet,
            update_id,
        ):
            app.logger.info(
                "Ignoring duplicate Telegram update: %s",
                update_id,
            )

            return {"ok": True}, 200

    except Exception:
        app.logger.exception(
            "Failed to check Telegram update ID"
        )

        send_telegram_message(
            chat_id,
            "⚠️ Something went wrong while checking "
            "your expense. Please try again.",
        )

        return {"ok": True}, 200

    # --------------------------------------------------------
    # Validate message
    # --------------------------------------------------------

    if not raw_text:
        send_telegram_message(
            chat_id,
            "⚠️ Please send an expense message.\n"
            "Example: 25k makan nasi goreng",
        )

        return {"ok": True}, 200

    expense, error = parse_expense(raw_text)

    if error:
        send_telegram_message(
            chat_id,
            error,
        )

        return {"ok": True}, 200

    # --------------------------------------------------------
    # Save expense
    # --------------------------------------------------------

    try:
        row = build_sheet_row(
            raw_text,
            expense,
            update_id,
        )

        worksheet.append_row(
            row,
            value_input_option="USER_ENTERED",
        )

    except Exception:
        app.logger.exception(
            "Failed to append expense to Google Sheets"
        )

        send_telegram_message(
            chat_id,
            "⚠️ Something went wrong while saving "
            "your expense. Please try again.",
        )

        return {"ok": True}, 200

    # --------------------------------------------------------
    # Send confirmation
    # --------------------------------------------------------

    try:
        send_telegram_message(
            chat_id,
            f"✅ Added: Rp{expense['amount']:,}\n"
            f"Category: {expense['category']}\n"
            f"Item: {expense['item']}",
        )

    except Exception:
        # The expense has already been saved.
        # Return 200 so Telegram does not retry the update
        # and create a duplicate expense.
        app.logger.exception(
            "Failed to send Telegram reply"
        )

    return {"ok": True}, 200


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
