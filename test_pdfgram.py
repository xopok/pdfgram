"""
Unit tests for pdfgram components.
"""

import os
import unittest
import tempfile
import pypdf

from arxiv_utils import (
    extract_arxiv_id,
    get_arxiv_pdf_url,
    sanitize_filename,
    make_arxiv_filename,
)
from cropper import extract_filename_from_url, read_pdf_title, crop_pdf
from config import Config


class TestArxivUtils(unittest.TestCase):
    def test_extract_arxiv_id_various_urls(self):
        cases = [
            ("https://arxiv.org/abs/2309.19101", "2309.19101"),
            ("https://arxiv.org/abs/2309.19101v1", "2309.19101v1"),
            ("https://arxiv.org/pdf/2309.19101.pdf", "2309.19101"),
            ("https://arxiv.org/pdf/2309.19101v2.pdf", "2309.19101v2"),
            ("https://arxiv.org/html/2309.19101v1", "2309.19101v1"),
            ("arxiv:2309.19101", "2309.19101"),
            ("2309.19101v1", "2309.19101v1"),
            ("https://arxiv.org/abs/cs/0612025", "cs/0612025"),
            ("https://example.com/other.pdf", None),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(extract_arxiv_id(url), expected)

    def test_get_arxiv_pdf_url(self):
        self.assertEqual(get_arxiv_pdf_url("2309.19101v1"), "https://arxiv.org/pdf/2309.19101v1")

    def test_sanitize_filename(self):
        dirty = "Monitoring and Discovering Reward Hacking with / \\ : * ? < > | Newlines\n\r"
        clean = sanitize_filename(dirty)
        for char in '/\\:*?<>"|\n\r':
            self.assertNotIn(char, clean)
        self.assertIn("Monitoring and Discovering Reward Hacking", clean)

    def test_make_arxiv_filename(self):
        fname = make_arxiv_filename(
            "2609.19101v1",
            "Monitoring and Discovering Reward Hacking with Internal Representations during LLM Evaluations",
        )
        self.assertTrue(fname.startswith("2609.19101v1 - Monitoring"))
        self.assertTrue(fname.endswith(".pdf"))


class TestCropper(unittest.TestCase):
    def test_extract_filename_from_url(self):
        url = "https://example.com/papers/deep_learning_survey.pdf"
        self.assertEqual(extract_filename_from_url(url), "deep_learning_survey.pdf")

        url_no_ext = "https://example.com/download/report"
        self.assertEqual(extract_filename_from_url(url_no_ext), "report.pdf")

    def test_read_pdf_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "titled.pdf")
            writer = pypdf.PdfWriter()
            writer.add_blank_page(width=300, height=400)
            writer.add_metadata({"/Title": "Super Advanced AI Research"})
            with open(pdf_path, "wb") as f:
                writer.write(f)

            extracted_title = read_pdf_title(pdf_path)
            self.assertEqual(extracted_title, "Super Advanced AI Research")

    def test_crop_pdf(self):
        import asyncio

        with tempfile.TemporaryDirectory() as tmpdir:
            input_pdf = os.path.join(tmpdir, "input.pdf")
            output_pdf = os.path.join(tmpdir, "output.pdf")

            writer = pypdf.PdfWriter()
            writer.add_blank_page(width=500, height=700)
            with open(input_pdf, "wb") as f:
                writer.write(f)

            config = Config(
                telegram_bot_token="fake_token",
                allowed_user_ids=[],
                crop_percent=10,
                crop_uniform=True,
            )

            async def run():
                return await crop_pdf(input_pdf, output_pdf, config)

            ok, msg = asyncio.run(run())
            self.assertTrue(ok, f"Crop failed: {msg}")
            self.assertTrue(os.path.exists(output_pdf))
            self.assertGreater(os.path.getsize(output_pdf), 0)


if __name__ == "__main__":
    unittest.main()
