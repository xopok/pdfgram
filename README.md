# pdfgram

A Telegram bot that automatically downloads PDFs or arXiv papers, crops margins using `pdfCropMargins`, renames them with descriptive titles, and returns the cropped document directly to your Telegram chat.

---

## Features

- **arXiv & PDF Intelligence:**
  - Send any arXiv link (`https://arxiv.org/abs/...`, `https://arxiv.org/pdf/...`, or `arxiv:XXXX.XXXXX`).
  - Fetches the official paper title from the arXiv API and renames the file:
    `2609.19101v1 - Monitoring and Discovering Reward Hacking with Internal Representations during LLM Evaluations.pdf`
  - Also works with direct PDF links or PDFs uploaded directly to the chat!
- **Margin Cropping (`pdfCropMargins`):**
  - Removes wide margins to make papers readable on e-ink Kindle screens, tablets, and phones.
  - Configurable retention margin percentage (default: `10%`).
  - Uniform page cropping enabled by default to prevent page-to-page shifting.
- **Direct & Fast Delivery:**
  - Instantly sends the cropped, renamed PDF right back to you in chat.
- **Access Control:**
  - Restrict bot usage with `ALLOWED_USER_IDS` whitelist so only you can use it.

---

## Deployment (Debian Server)

### 1. Push latest changes to GitHub
From your development machine, push the latest code:
```bash
git push origin main
```

### 2. Setup on your server
Clone the repo and configure your environment:
```bash
git clone https://github.com/xopok/pdfgram.git
cd pdfgram
cp .env.example .env
nano .env
```

In `.env`, set your bot token and whitelist your Telegram ID:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567
ALLOWED_USER_IDS=12345678   # Your numeric Telegram ID (from @userinfobot)
```

### 3. Build & Run
The Docker image will automatically clone and build the code from GitHub:
```bash
docker compose up -d --build
```

- **View logs:** `docker compose logs -f`
- **Stop:** `docker compose down`

### Updating
Whenever you push changes to GitHub, rebuild the container on your server:
```bash
docker compose build --no-cache
docker compose up -d
```

---

## Running Locally (without Docker)

### 1. Install System Dependencies
```bash
sudo apt update
sudo apt install -y poppler-utils ghostscript python3-venv
```

### 2. Create Virtual Environment & Install Requirements
```bash
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

### 3. Run the Bot
```bash
cp .env.example .env
# Edit .env with TELEGRAM_BOT_TOKEN and ALLOWED_USER_IDS
./.venv/bin/python bot.py
```

---

## Bot Commands

| Command | Description |
| :--- | :--- |
| *(Send URL or PDF)* | Automatically downloads, crops margins, renames, and sends back the PDF. |
| `/status` | Displays margin cropping settings and whitelist status. |
| `/help` | Shows usage instructions. |

---

## Running Unit Tests

```bash
./.venv/bin/python -m unittest test_pdfgram.py
```
