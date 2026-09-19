"""
Utilities for detecting arXiv links, extracting metadata, and fetching paper titles.
"""

import re
import xml.etree.ElementTree as ET
import logging
from typing import Optional, Tuple
import httpx

logger = logging.getLogger(__name__)

# Regular expressions for matching arXiv identifiers and URLs
# Matches both new format (e.g. 2309.19101, 2309.19101v1) and old format (e.g. cs/0612025, math.GT/0309136)
ARXIV_URL_REGEX = re.compile(
    r'https?://(?:www\.)?arxiv\.org/(?:abs|pdf|html)/([a-zA-Z\-]+(?:\.[a-zA-Z]{2})?/[0-9]{7}(?:v[0-9]+)?|[0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)(?:\.pdf)?',
    re.IGNORECASE,
)

ARXIV_ID_DIRECT_REGEX = re.compile(
    r'(?:arxiv:\s*)?([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?|[a-zA-Z\-]+(?:\.[a-zA-Z]{2})?/[0-9]{7}(?:v[0-9]+)?)',
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": "pdfgram-telegram-bot/1.0 (https://github.com/vlysenkov/pdfgram; mailto:contact@example.com)"
}


def extract_arxiv_id(text: str) -> Optional[str]:
    """
    Extracts an arXiv ID from a text string (URL or bare ID).
    Returns the matched ID or None.
    """
    text = text.strip()
    # First check for full arxiv.org URL
    url_match = ARXIV_URL_REGEX.search(text)
    if url_match:
        return url_match.group(1)
    
    # Check for direct arXiv ID (e.g., "arxiv:2309.19101" or "2309.19101v1")
    # Only if text looks like an arxiv reference
    if "arxiv" in text.lower() or re.fullmatch(r'[0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?', text):
        id_match = ARXIV_ID_DIRECT_REGEX.search(text)
        if id_match:
            return id_match.group(1)
            
    return None


def get_arxiv_pdf_url(arxiv_id: str) -> str:
    """Returns the direct PDF download URL for a given arXiv ID."""
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def sanitize_filename(name: str, max_length: int = 180) -> str:
    """
    Sanitize string to be safe for filenames across Linux, macOS, and Windows.
    Replaces problematic characters and collapses multiple spaces.
    """
    # Replace illegal filename characters with dashes or underscores
    name = re.sub(r'[\r\n\t]+', ' ', name)
    name = re.sub(r'[\\/*?:"<>|]', '-', name)
    name = re.sub(r'\s+', ' ', name).strip(' .-_')
    
    if len(name) > max_length:
        name = name[:max_length].rstrip(' .-_')
    return name


async def fetch_arxiv_metadata(arxiv_id: str, timeout: float = 10.0) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetches the paper title and summary from arXiv Atom API.
    Fallback to scraping the abstract page if API fails.
    Returns: (title, summary)
    """
    # Remove version suffix for query if present, or query with full id
    clean_id = re.sub(r'v\d+$', '', arxiv_id)
    api_url = f"https://export.arxiv.org/api/query?id_list={clean_id}"

    async with httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
        # Try 1: ArXiv Atom API
        try:
            resp = await client.get(api_url)
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
                entry = root.find("atom:entry", atom_ns)
                if entry is not None:
                    title_elem = entry.find("atom:title", atom_ns)
                    summary_elem = entry.find("atom:summary", atom_ns)
                    title = " ".join(title_elem.text.split()) if title_elem is not None and title_elem.text else None
                    summary = " ".join(summary_elem.text.split()) if summary_elem is not None and summary_elem.text else None
                    if title:
                        return title, summary
        except Exception as e:
            logger.warning(f"ArXiv API fetch failed for {arxiv_id}: {e}")

        # Try 2: Abstract HTML page fallback
        try:
            abs_url = f"https://arxiv.org/abs/{arxiv_id}"
            resp = await client.get(abs_url)
            if resp.status_code == 200:
                html = resp.text
                # Match <h1 class="title mathjax"><span class="descriptor">Title:</span>...</h1>
                title_match = re.search(
                    r'<h1[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>(?:<span[^>]*>.*?</span>)?(.*?)</h1>',
                    html,
                    re.IGNORECASE | re.DOTALL,
                )
                if title_match:
                    raw_title = title_match.group(1)
                    # Strip any nested HTML tags
                    clean_title = re.sub(r'<[^<]+?>', '', raw_title)
                    clean_title = " ".join(clean_title.split())
                    return clean_title, None
        except Exception as e:
            logger.warning(f"ArXiv HTML scrape fallback failed for {arxiv_id}: {e}")

    return None, None


def make_arxiv_filename(arxiv_id: str, title: Optional[str]) -> str:
    """
    Formats the filename for an arXiv paper:
    e.g. '2609.19101v1 - Monitoring and Discovering Reward Hacking with Internal Representations during LLM Evaluations.pdf'
    """
    if title:
        safe_title = sanitize_filename(title, max_length=150)
        return f"{arxiv_id} - {safe_title}.pdf"
    return f"{arxiv_id}.pdf"
