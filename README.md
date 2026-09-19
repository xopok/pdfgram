# pdfgram

A Telegram bot that automatically downloads PDFs or arXiv papers, crops out excessive page margins using `pdfCropMargins`, renames them with descriptive titles, and either delivers them right back in chat or emails them to your Amazon Kindle (`@kindle.com`).

---

## Features

- **Link & arXiv Intelligence:**
  - Paste any arXiv link (`https://arxiv.org/abs/...`, `https://arxiv.org/pdf/...`, or `arxiv:XXXX.XXXXX`).
  - Automatically fetches the official paper title from the arXiv API.
  - Renames the file: e.g. `2309.19101v1 - Monitoring and Discovering Reward Hacking with Internal Representations during LLM Evaluations.pdf`.
  - Also works with direct PDF links or PDFs uploaded straight into the chat!
- **Margin Cropping (`pdfCropMargins`):**
  - Removes wide margins to make papers readable on e-ink Kindle screens, tablets, or small monitors.
  - Configurable retention margin percentage (default: `10%` to keep breathing room).
  - Uniform page cropping enabled by default to prevent page-to-page shifting.
- **Flexible Delivery:**
  - **Option a:** Send the cropped PDF directly back into Telegram chat.
  - **Option b:** Email the renamed PDF directly to your Send-to-Kindle address.
  - **Interactive buttons:** Choose on-the-fly (`Send to Chat`, `Send to Kindle`, `Send Both`).
- **User Settings & Whitelist:**
  - Update your Kindle address directly in Telegram via `/setkindle you@kindle.com`.
  - Optional `ALLOWED_USER_IDS` whitelist to protect your bot and server resources.
- **Containerized & Ready for Debian:**
  - Full Docker & `docker-compose.yaml` setup bundling `poppler-utils` and `ghostscript`.

---

## Quick Start with Docker Compose

### 1. Configure Environment

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` and configure your Telegram bot token:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567
ALLOWED_USER_IDS=12345678  # Optional: your Telegram ID
```

> **How to get a bot token:** Talk to [@BotFather](https://t.me/BotFather) on Telegram and run `/newbot`.
> **How to find your user ID:** Send a message to [@userinfobot](https://t.me/userinfobot) on Telegram.

### 2. (Optional) Configure Send-to-Kindle

If you want to send cropped PDFs directly to your Kindle:

1. **Find your Kindle email address:**
   In your Amazon account, go to **Manage Your Content and Devices** &rarr; **Preferences** &rarr; **Personal Document Settings** &rarr; **Send-to-Kindle E-Mail Settings** (e.g. `username@kindle.com`).
2. **Approve the sender email:**
   In that same Amazon section, scroll down to **Approved Personal Document E-mail List** and add the email address you'll be sending from (e.g. your Gmail address).
3. **Set SMTP details in `.env`:**

```env
KINDLE_EMAIL=username@kindle.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_gmail_app_password  # Use an App Password if using 2FA
SMTP_USE_TLS=true
DEFAULT_ACTION=ask                     # Options: ask, chat, kindle, both
```

> **Note:** If Kindle is not configured, the bot automatically sends all cropped PDFs back to the Telegram chat (Option a).

### 3. Build & Run

Start the bot with Docker Compose:

```bash
docker compose up -d --build
```

To view logs:

```bash
docker compose logs -f
```

To stop:

```bash
docker compose down
```

---

## Running Locally (without Docker)

If you prefer running directly in Python on your Debian server:

### 1. Install System Dependencies

`pdfCropMargins` requires `poppler-utils` (for `pdftoppm`) and `ghostscript`:

```bash
sudo apt update
sudo apt install -y poppler-utils ghostscript python3-venv
```

### 2. Create Virtual Environment & Install Dependencies

```bash
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

### 3. Run the Bot

```bash
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN
./.venv/bin/python bot.py
```

---

## Bot Commands

| Command | Description |
| :--- | :--- |
| *(Send URL or PDF)* | Automatically downloads, crops margins, and prompts/delivers according to `DEFAULT_ACTION`. |
| `/crop <url>` | Forces cropping and returns the PDF directly to Telegram chat. |
| `/kindle <url>` | Forces cropping and delivers directly to Kindle. |
| `/setkindle <email>` | Sets or updates your personal Kindle email address. |
| `/mykindle` | Checks your current Kindle address and SMTP connection status. |
| `/status` | Displays margin cropping settings and server status. |
| `/help` | Shows usage instructions. |

---

## Running Unit Tests

Run the test suite using the virtual environment:

```bash
./.venv/bin/python -m unittest test_pdfgram.py
```
