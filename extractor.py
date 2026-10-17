# extractor.py
import io
import requests
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from docx import Document

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    text = []
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text.append(page_text)
    except Exception:
        pass
    return "\n".join(text).strip()

def extract_text_from_docx_bytes(docx_bytes: bytes) -> str:
    text = []
    try:
        with io.BytesIO(docx_bytes) as f:
            doc = Document(f)
            for p in doc.paragraphs:
                text.append(p.text)
    except Exception:
        pass
    return "\n".join(text).strip()

def extract_text_from_txt_bytes(txt_bytes: bytes) -> str:
    try:
        return txt_bytes.decode('utf-8', errors='ignore')
    except Exception:
        return ""

def fetch_text_from_url(url: str) -> str:
    """Fetches a web page and returns main textual content (basic)."""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "patent-understand-bot/1.0"})
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # Remove scripts/styles
        for s in soup(["script", "style", "noscript"]):
            s.decompose()

        # Option: try to get article/main
        main = soup.find("main") or soup.find("article")
        if main:
            text = main.get_text(separator="\n").strip()
            if len(text) > 200:
                return text

        # Fall back to body text
        body = soup.body
        if body:
            return body.get_text(separator="\n").strip()
        return soup.get_text(separator="\n").strip()
    except Exception:
        return ""
