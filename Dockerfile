FROM python:3.11-slim

# Install system dependencies required by pdfCropMargins (poppler-utils for pdftoppm, ghostscript)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    ghostscript \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create non-root user and data directory
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app

# Copy application files
COPY --chown=appuser:appuser . .

USER appuser

# Ensure python output is sent directly to terminal without buffering
ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
