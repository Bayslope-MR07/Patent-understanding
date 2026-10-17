# main.py
import os
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from extractor import (
    extract_text_from_pdf_bytes,
    extract_text_from_docx_bytes,
    extract_text_from_txt_bytes,
)
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1500"))

if not OPENAI_API_KEY:
    raise RuntimeError("Please set OPENAI_API_KEY in environment")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(title="Patent Understanding Module")
templates = Jinja2Templates(directory="templates")


# Home page
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


def simple_detect_file_type(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".docx") or name.endswith(".doc"):
        return "docx"
    if name.endswith(".txt"):
        return "txt"
    return "unknown"


async def read_upload_file_bytes(upload_file: UploadFile) -> bytes:
    content = await upload_file.read()
    return content


def build_prompt_for_openai(extracted_text: str, original_filename_or_url: str = None, is_url=False) -> str:
    source_label = f"Source: {original_filename_or_url}\n\n" if original_filename_or_url else ""

    url_instruction = ""
    if is_url:
        url_instruction = (
            "The user provided a URL instead of raw text. "
            "You cannot visit external links, but you must infer/explain what this URL might represent. "
            "If it's a patent link, summarize it as a patent. "
            "If it's another document link, summarize it as a general document. "
            "Give a helpful explanation as if the content were accessible.\n\n"
        )

    prompt = f"""
You are a Document Understanding Assistant.

{source_label}
{url_instruction}

Read the following input (it may be a patent document, another type of document, or just a URL).  
Your job is to explain it in very simple terms for someone who is not a technical or legal expert.

Steps:
1. Detect the type of input:
   - If it looks like a patent or patent application → explain it as a patent (summary, example, key claims, difficult terms).
   - If it looks like another kind of document or a URL → still summarize what it is likely about (main idea, example/analogy, difficult terms explained).

2. Always produce output in this structure:
   - 📄 Summary: [short plain-language summary]  
   - 💡 Example/Analogy: [one simple real-world example]  
   - 📘 Difficult Terms Explained: [list of hard terms with one-line definitions]  
   - 🔎 Key Points/Claims: [if patent → list claims, otherwise → list main bullet points]  

3. Keep the entire response concise (<= 500 words). Use bullet lists where useful.

Here is the input below:

---INPUT START---
{extracted_text[:12000]}
---INPUT END---
"""
    return prompt


@app.post("/analyze")
async def analyze(file: UploadFile = File(None), url: str = Form(None)):
    """
    Accept either an uploaded file (pdf/docx/txt) or a URL form field named `url`.
    Returns JSON with the LLM output.
    """
    if not file and not url:
        return JSONResponse({"error": "Provide either a file upload or a url field."}, status_code=400)

    extracted_text = ""
    source_label = ""

    if file:
        source_label = f"uploaded file: {file.filename}"
        file_bytes = await read_upload_file_bytes(file)
        ftype = simple_detect_file_type(file.filename or "")
        if ftype == "pdf":
            extracted_text = extract_text_from_pdf_bytes(file_bytes)
        elif ftype == "docx":
            extracted_text = extract_text_from_docx_bytes(file_bytes)
        elif ftype == "txt":
            extracted_text = extract_text_from_txt_bytes(file_bytes)
        else:
            # fallback attempts
            text_try = extract_text_from_pdf_bytes(file_bytes)
            if len(text_try) > 50:
                extracted_text = text_try
            else:
                extracted_text = extract_text_from_txt_bytes(file_bytes)

    elif url:
        source_label = f"url: {url}"
        # Instead of scraping, just pass raw URL as input
        extracted_text = f"The user provided this link: {url}"

    # ✅ Remove strict length check
    if not extracted_text:
        return JSONResponse({"error": "Could not process useful input."}, status_code=400)

    prompt = build_prompt_for_openai(extracted_text, source_label, is_url=bool(url))

    # Call OpenAI Responses API
    try:
        response = client.responses.create(
            model=MODEL,
            input=prompt,
            max_output_tokens=MAX_TOKENS
        )

        output_text = ""
        if hasattr(response, "output_text") and response.output_text:
            output_text = response.output_text
        else:
            if hasattr(response, "output") and isinstance(response.output, list):
                for item in response.output:
                    if isinstance(item, dict) and "content" in item:
                        content = item.get("content")
                        if isinstance(content, str):
                            output_text += content
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict):
                                    output_text += c.get("text", "")
                                elif isinstance(c, str):
                                    output_text += c
            if not output_text:
                output_text = str(response)

        return JSONResponse({"result": output_text})
    except Exception as e:
        return JSONResponse({"error": "OpenAI API error", "details": str(e)}, status_code=500)
