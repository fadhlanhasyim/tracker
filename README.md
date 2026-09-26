# Telegram Expense Tracker

A simple personal expense tracker for Indonesia using a Telegram bot.

Send an expense message through Telegram, and the bot parses it with a deterministic Regex-based parser and saves it to Google Sheets.

No AI is required.

## Features

* Telegram Bot API integration
* Deterministic expense parsing with Regex
* IDR amount parsing
* Supports `k`, `rb`, and `ribu` units
* Strict expense categories
* Optional historical date and time
* Google Sheets storage
* Persistent Telegram webhook duplicate protection
* Jakarta timezone (`Asia/Jakarta`)
* Flask webhook backend
* Deployable on PythonAnywhere

## Tech Stack

* Python 3.13+
* Flask
* Gunicorn
* Telegram Bot API
* Google Sheets API
* `gspread`
* `google-auth`
* `python-dotenv`
* `requests`

## Expense Format

The basic format is:

```text
<amount> <category> <description>
```

### Examples

```text
25k makan nasi goreng
```

```text
50rb transportasi bensin motor
```

```text
150000 personal kaos
```

### Supported Amount Units

The following units are supported:

* `k`
* `rb`
* `ribu`

They are case-insensitive and represent `×1,000`.

Examples:

```text
25k  → Rp25,000
25rb → Rp25,000
25ribu → Rp25,000
```

## Categories

Only these categories are accepted:

| Category       | Purpose                                    |
| -------------- | ------------------------------------------ |
| `makan`        | Food, drinks, groceries, coffee            |
| `transportasi` | Fuel, toll, parking, Gojek/Grab            |
| `tagihan`      | Utilities, electricity, WiFi, phone credit |
| `keluarga`     | Allowances, family needs, house needs      |
| `donasi`       | Charity, zakat, infaq, social giving       |
| `personal`     | Hobbies, skincare, clothes, gadgets        |
| `lainnya`      | Anything else                              |

Category matching is case-insensitive.

## Historical Date and Time

Expenses can optionally specify a date:

```text
25k makan nasi goreng @2026-09-25
```

Or an exact date and time:

```text
25k makan nasi goreng @2026-09-25 19:30
```

If no date or time is provided, the current Jakarta time is used.

Natural-language dates are intentionally not supported.

## Google Sheets Structure

The bot stores expenses in `Sheet1`.

| Column | Name               | Description                |
| ------ | ------------------ | -------------------------- |
| A      | Timestamp          | `YYYY-MM-DD HH:MM:SS`      |
| B      | Day                | Day of month               |
| C      | Month              | `Jan`, `Feb`, `Mar`, etc.  |
| D      | Year               | Four-digit year            |
| E      | Day_of_Week        | `Monday`, `Tuesday`, etc.  |
| F      | Raw_Text           | Original Telegram message  |
| G      | Item               | Parsed description         |
| H      | Amount_IDR         | Amount in IDR              |
| I      | Category           | Normalized category        |
| J      | Telegram_Update_ID | Telegram update identifier |

### Telegram Update ID

Column J is used for webhook idempotency.

Telegram may retry a webhook update if it does not receive a successful response.

The bot stores the Telegram `update_id` with each expense and checks it before inserting a new row.

This prevents the same Telegram message from creating multiple expenses.

## Project Structure

```text
telegram-expense-tracker/
├── main.py
├── Procfile
├── requirements.txt
├── runtime.txt
├── README.md
└── .gitignore
```

Sensitive local files:

```text
.env
credentials.json
```

must not be committed to Git.

## Environment Variables

The application requires:

```text
TELEGRAM_BOT_TOKEN
SPREADSHEET_ID
GOOGLE_CREDENTIALS_JSON
```

Example `.env`:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
SPREADSHEET_ID=your_google_spreadsheet_id
GOOGLE_CREDENTIALS_JSON={"type":"service_account",...}
```

Never commit `.env` or `credentials.json`.

## Google Cloud Setup

The Google service account requires access to:

* Google Sheets API
* Google Drive API

The target Google Spreadsheet must be shared with the service account email.

The application uses these OAuth scopes:

```text
https://www.googleapis.com/auth/spreadsheets
https://www.googleapis.com/auth/drive
```

## Local Development

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the Flask application:

```bash
python main.py
```

The application runs on:

```text
http://localhost:5000
```

Health check:

```bash
curl http://localhost:5000/health
```

Expected response:

```json
{
  "status": "ok"
}
```

## Telegram Webhook

The production Telegram webhook points to:

```text
https://YOUR_DOMAIN/telegram-webhook
```

Set the webhook using:

```bash
curl -X POST \
  "https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook" \
  -d "url=https://YOUR_DOMAIN/telegram-webhook"
```

Check the webhook:

```bash
curl \
  "https://api.telegram.org/botYOUR_BOT_TOKEN/getWebhookInfo"
```

## Production Deployment

The application can be deployed as a Python web application.

The WSGI application imports:

```python
from main import app as application
```

The project uses:

```text
web: gunicorn main:app
```

as its process command.

The production environment must provide:

```text
TELEGRAM_BOT_TOKEN
SPREADSHEET_ID
GOOGLE_CREDENTIALS_JSON
```

## Response Examples

Successful expense:

```text
✅ Added: Rp25,000
Category: makan
Item: Nasi goreng
```

Invalid format:

```text
⚠️ Invalid format. Use: <amount> <category> <description>
Example: 25k makan nasi goreng
```

Invalid category:

```text
❌ Category 'bensin' is invalid.
Allowed categories:
• donasi
• keluarga
• lainnya
• makan
• personal
• tagihan
• transportasi
```

## Design Principles

### Deterministic parsing

The application intentionally does not use an AI model.

A valid expense must follow the defined syntax.

This makes expense recording predictable and reduces unexpected categorization.

### Strict categories

Only predefined categories are accepted.

This keeps the Google Sheet consistent and easier to analyze later.

### Persistent idempotency

Telegram webhook retries must not create duplicate expenses.

The Telegram `update_id` is stored in Google Sheets and checked before inserting an expense.

### Explicit timezone

All generated timestamps use:

```text
Asia/Jakarta
```

instead of relying on the hosting server's timezone.

## License

Personal project.
