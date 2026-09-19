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
import urllib.request
import httpx
import pypdf

from config import Config
from arxiv_utils import extract_arxiv_id, sanitize_filename

logger = logging.getLogger("pdfgram")

DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
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
            if len(title) > 2 and not title.lower().startswith("untitled"):
                return sanitize_filename(title, max_length=150)
    except Exception as e:
        logger.debug(f"Could not read PDF metadata from {pdf_path}: {e}")
    return None


def download_with_urllib_sync(
    url: str,
    destination_path: str,
    max_size_mb: int,
    timeout: float,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Fallback downloader using Python standard library urllib."""
    max_bytes = max_size_mb * 1024 * 1024
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Accept": "*/*",
        "Referer": "https://arxiv.org/" if "arxiv.org" in url else url,
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False, f"urllib HTTP {resp.status}", None

            cd = resp.headers.get("Content-Disposition", "")
            suggested_filename = None
            if "filename=" in cd:
                parts = cd.split("filename=")
                if len(parts) > 1:
                    fname = parts[1].strip('"\'; ')
                    if fname:
                        suggested_filename = sanitize_filename(fname)

            downloaded = 0
            with open(destination_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        return False, f"File exceeded limit of {max_size_mb} MB", None
                    f.write(chunk)

        with open(destination_path, "rb") as f:
            if f.read(5) != b"%PDF-":
                return False, "Downloaded file missing %PDF header", None

        if not suggested_filename:
            suggested_filename = extract_filename_from_url(url)

        return True, None, suggested_filename

    except Exception as e:
        return False, f"urllib error: {str(e)}", None


async def download_file(
    url: str,
    destination_path: str,
    max_size_mb: int = 50,
    timeout: float = 60.0,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Downloads a PDF file from a URL to destination_path.
    Tries canonical URLs, custom headers, and urllib fallback for arXiv resilience.
    Returns: (success, error_message, suggested_filename)
    """
    max_bytes = max_size_mb * 1024 * 1024
    suggested_filename = None

    # Construct candidate URLs
    urls_to_try = []
    if "arxiv.org" in url:
        arxiv_id = extract_arxiv_id(url)
        if arxiv_id:
            # Canonical arXiv link (without .pdf), then with .pdf, then export mirror
            urls_to_try.extend([
                f"https://arxiv.org/pdf/{arxiv_id}",
                f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                f"https://export.arxiv.org/pdf/{arxiv_id}",
                f"https://export.arxiv.org/pdf/{arxiv_id}.pdf",
            ])
    if url not in urls_to_try:
        urls_to_try.append(url)

    last_error = None
    for attempt_url in urls_to_try:
        # Prepare headers tailored for this URL
        headers = dict(DOWNLOAD_HEADERS)
        if "arxiv.org" in attempt_url:
            arxiv_id = extract_arxiv_id(attempt_url)
            headers["Referer"] = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "https://arxiv.org/"

        # Method 1: httpx streaming
        try:
            logger.info(f"Downloading from {attempt_url} via httpx...")
            async with httpx.AsyncClient(
                headers=headers,
                follow_redirects=True,
                timeout=httpx.Timeout(timeout, connect=15.0),
            ) as client:
                async with client.stream("GET", attempt_url) as response:
                    if response.status_code == 200:
                        content_disp = response.headers.get("content-disposition", "")
                        if "filename=" in content_disp:
                            parts = content_disp.split("filename=")
                            if len(parts) > 1:
                                fname = parts[1].strip('"\'; ')
                                if fname:
                                    suggested_filename = sanitize_filename(fname)

                        content_len = response.headers.get("content-length")
                        if content_len and int(content_len) > max_bytes:
                            return False, f"File size ({int(content_len) // (1024*1024)} MB) exceeds limit ({max_size_mb} MB)", None

                        downloaded = 0
                        with open(destination_path, "wb") as f:
                            async for chunk in response.aiter_bytes(chunk_size=65536):
                                downloaded += len(chunk)
                                if downloaded > max_bytes:
                                    return False, f"File exceeded limit of {max_size_mb} MB while downloading", None
                                f.write(chunk)

                        with open(destination_path, "rb") as f:
                            if f.read(5) == b"%PDF-":
                                if not suggested_filename:
                                    suggested_filename = extract_filename_from_url(attempt_url)
                                logger.info(f"Successfully downloaded {attempt_url} ({downloaded} bytes via httpx)")
                                return True, None, suggested_filename
                            else:
                                last_error = "Downloaded content is not a valid PDF"
                                logger.warning(f"{attempt_url}: {last_error}")
                    else:
                        last_error = f"Server returned HTTP {response.status_code} ({response.reason_phrase})"
                        logger.warning(f"httpx download from {attempt_url} failed: {last_error}")

        except Exception as e:
            last_error = f"httpx error: {str(e)}"
            logger.warning(f"httpx error for {attempt_url}: {last_error}")

        # Method 2: Fallback to urllib
        logger.info(f"Trying urllib fallback for {attempt_url}...")
        u_ok, u_err, u_fname = await asyncio.to_thread(
            download_with_urllib_sync,
            attempt_url,
            destination_path,
            max_size_mb,
            timeout,
        )
        if u_ok:
            logger.info(f"Successfully downloaded {attempt_url} via urllib")
            return True, None, u_fname or suggested_fname or extract_filename_from_url(attempt_url)
        else:
            last_error = u_err
            logger.warning(f"urllib fallback for {attempt_url} failed: {u_err}")

    logger.error(f"All download attempts failed for {url}: {last_error}")
    return False, last_error or "Download failed", None


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
