"""
PDF downloading, metadata inspection, and margin cropping using pdfCropMargins.
"""

import os
import sys
import shlex
import asyncio
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse, unquote
import httpx
import pypdf

from config import Config
from arxiv_utils import sanitize_filename

logger = logging.getLogger(__name__)

DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36 pdfgram-bot/1.0"
    ),
    "Accept": "application/pdf,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
}


def extract_filename_from_url(url: str, default: str = "document.pdf") -> str:
    """Extract a plausible filename from a URL path."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    base = os.path.basename(path)
    if base and "." in base:
        return sanitize_filename(base)
    elif base:
        return f"{sanitize_filename(base)}.pdf"
    return default


def read_pdf_title(pdf_path: str) -> Optional[str]:
    """Extract title metadata from PDF using pypdf if available."""
    try:
        reader = pypdf.PdfReader(pdf_path)
        meta = reader.metadata
        if meta and meta.title:
            title = meta.title.strip()
            # Some titles are filled with 'untitled' or empty placeholders
            if len(title) > 2 and not title.lower().startswith("untitled"):
                return sanitize_filename(title, max_length=150)
    except Exception as e:
        logger.debug(f"Could not read PDF metadata from {pdf_path}: {e}")
    return None


async def download_file(
    url: str,
    destination_path: str,
    max_size_mb: int = 50,
    timeout: float = 60.0,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Downloads a PDF file from a URL to destination_path.
    Returns: (success, error_message, suggested_filename)
    """
    max_bytes = max_size_mb * 1024 * 1024
    suggested_filename = None

    try:
        async with httpx.AsyncClient(
            headers=DOWNLOAD_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(timeout, connect=15.0),
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    return False, f"Server returned HTTP {response.status_code} ({response.reason_phrase})", None

                # Extract filename from Content-Disposition if present
                content_disp = response.headers.get("content-disposition", "")
                if "filename=" in content_disp:
                    parts = content_disp.split("filename=")
                    if len(parts) > 1:
                        fname = parts[1].strip('"\'; ')
                        if fname:
                            suggested_filename = sanitize_filename(fname)

                content_len = response.headers.get("content-length")
                if content_len and int(content_len) > max_bytes:
                    return False, f"File size ({int(content_len) // (1024*1024)} MB) exceeds maximum limit ({max_size_mb} MB)", None

                downloaded = 0
                with open(destination_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            return False, f"File exceeded maximum limit of {max_size_mb} MB while downloading", None
                        f.write(chunk)

        # Validate that the downloaded file is indeed a PDF (check magic bytes %PDF-)
        with open(destination_path, "rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                return False, "Downloaded file does not appear to be a valid PDF (missing %PDF header)", None

        if not suggested_filename:
            suggested_filename = extract_filename_from_url(url)

        return True, None, suggested_filename

    except httpx.TimeoutException:
        return False, f"Download timed out after {timeout} seconds", None
    except Exception as e:
        logger.exception(f"Failed to download {url}")
        return False, f"Download error: {str(e)}", None


async def crop_pdf(
    input_path: str,
    output_path: str,
    config: Config,
    timeout: float = 180.0,
) -> Tuple[bool, str]:
    """
    Crops PDF margins using pdfCropMargins CLI invoked via python -m pdfCropMargins.
    Runs in an isolated subprocess for stability and memory safety.
    Returns: (success, message)
    """
    cmd = [
        sys.executable,
        "-m",
        "pdfCropMargins",
        "-p",
        str(config.crop_percent),
    ]

    if config.crop_uniform:
        cmd.append("-u")

    if config.crop_same_page_size:
        cmd.append("-s")

    if config.crop_extra_args:
        try:
            extra_tokens = shlex.split(config.crop_extra_args)
            cmd.extend(extra_tokens)
        except Exception as e:
            logger.warning(f"Failed to parse CROP_EXTRA_ARGS: {e}")

    cmd.extend(["-o", output_path, input_path])

    logger.info(f"Running crop command: {' '.join(cmd)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            error_msg = stderr_str or stdout_str or f"Exited with code {proc.returncode}"
            logger.error(f"Crop failed ({proc.returncode}): {error_msg}")
            return False, f"pdfCropMargins failed: {error_msg[:300]}"

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return False, "pdfCropMargins completed but output file was not generated or is empty"

        return True, "Cropping completed successfully"

    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return False, f"Margin cropping timed out after {timeout} seconds"
    except Exception as e:
        logger.exception("Error executing pdfCropMargins subprocess")
        return False, f"Subprocess error: {str(e)}"
