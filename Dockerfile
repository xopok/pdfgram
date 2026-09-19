FROM python:3.11-slim

# Install system dependencies required by pdfCropMargins and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    ghostscript \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Clone repository from GitHub
ARG REPO_URL=https://github.com/xopok/pdfgram.git
ARG BRANCH=main
RUN git clone --depth 1 --branch ${BRANCH} ${REPO_URL} .

# Install python dependencies from the cloned repo
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create non-root user and data directory
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app

USER appuser

# Ensure python output is sent directly to terminal without buffering
ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
