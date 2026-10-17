import uuid
import os
import time
import logging
import tempfile
import requests
import html
import re
from urllib.parse import urlparse
from flask import Flask, render_template, request, session
from flask_session import Session
from dotenv import load_dotenv
from openai import OpenAI
from bs4 import BeautifulSoup

# === NEW: OCR Dependencies ===
try:
    from pdf2image import convert_from_path
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("OCR not available. Run: pip install pytesseract pdf2image pillow")

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Flask app setup
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
Session(app)

# ---- Load instructions from external file ----
def load_instructions(file_path="instructions.txt"):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error loading instructions file: {str(e)}")
        return "You are a helpful AI assistant."

active_sessions = {}
assistant_id = None

def get_assistant_id():
    global assistant_id
    if not assistant_id:
        instructions_text = load_instructions("instructions.txt")
        assistant = client.beta.assistants.create(
            name="Patent Explainer",
            instructions=instructions_text,
            model=OPENAI_MODEL,
            tools=[{"type": "file_search"}]
        )
        assistant_id = assistant.id
        logger.info(f"Assistant created with ID: {assistant_id}")
    return assistant_id

try:
    if OPENAI_API_KEY:
        assistant_id = get_assistant_id()
except Exception as e:
    logger.warning(f"Could not initialize assistant at startup: {e}")

# === NEW: Smart PDF Text Extractor with OCR fallback ===
def extract_text_from_pdf_smart(pdf_path):
    # Pehle normal text extract karne ki koshish
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        if text.strip() and len(text.strip()) > 300:
            return text.strip()
    except Exception as e:
        logger.warning(f"PyPDF2 failed: {e}")

    # Agar normal text nahi mila → OCR mode ON
    if OCR_AVAILABLE:
        try:
            logger.info("Normal text extraction failed → using OCR...")
            images = convert_from_path(pdf_path, dpi=300)
            full_text = []
            for i, img in enumerate(images):
                text = pytesseract.image_to_string(img, lang='eng')
                if text.strip():
                    full_text.append(f"\n--- Page {i+1} ---\n{text.strip()}")
            ocr_result = "\n".join(full_text)
            if len(ocr_result) > 500:
                return f"[Extracted via OCR]\n{ocr_result}"
        except Exception as e:
            logger.error(f"OCR failed: {str(e)}")

    return None

# === Existing normalize & fetch functions (unchanged) ===
def normalize_patent_link(link):
    try:
        link = link.strip()
        if "patents.google.com" in link:
            parsed = urlparse(link)
            path_parts = parsed.path.split("/")
            patent_id = next((p for p in path_parts if re.match(r"[A-Z]{2}\d+[A-Z]?\d*", p, re.IGNORECASE)), None)
            if patent_id:
                return f"https://patents.google.com/patent/{patent_id}/en"
            return link.split("?")[0]

        clean_link = re.sub(r"^https?://", "", link, flags=re.IGNORECASE)
        clean_link = clean_link.split("?")[0].split("#")[0].strip("/")

        match = re.match(r"([A-Za-z]{2}[\d]+[A-Za-z]?\d*)", clean_link, re.IGNORECASE)
        if match:
            patent_id = match.group(1).upper()
            return f"https://patents.google.com/patent/{patent_id}/en"

        if link.lower().endswith(".pdf"):
            match = re.search(r"([A-Z]{2}\d{7,}[A-Z]?\d*)", link, re.IGNORECASE)
            if match:
                patent_id = match.group(1).upper()
                return f"https://patents.google.com/patent/{patent_id}/en"

        return None
    except Exception as e:
        logger.error(f"Normalize link error: {str(e)}")
        return None

def fetch_google_patent_content(link):
    try:
        normalized_link = normalize_patent_link(link)
        if not normalized_link:
            return None

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        }
        r = requests.get(normalized_link, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        content_parts = []
        meta = soup.find("meta", {"name": "description"})
        if meta and meta.get("content"):
            content_parts.append(meta["content"].strip())

        abstract = soup.find("section", {"itemprop": "abstract"})
        if abstract:
            abstract_text = abstract.get_text(separator="\n", strip=True)
            if len(abstract_text) > 30:
                content_parts.append("Abstract:\n" + abstract_text)

        description = soup.find("div", {"itemprop": "description"}) or soup.find("section", {"itemprop": "description"})
        if description:
            desc_text = description.get_text(separator="\n", strip=True)
            if len(desc_text) > 50:
                content_parts.append("Description:\n" + desc_text)

        claims = soup.find("section", {"itemprop": "claims"})
        if claims:
            claims_text = claims.get_text(separator="\n", strip=True)[:4000]
            if len(claims_text) > 30:
                content_parts.append("Key Claims:\n" + claims_text)

        title_tag = soup.find("h1")
        if title_tag:
            title = title_tag.get_text(strip=True)
            if title:
                content_parts.insert(0, f"Patent Title: {title}")

        inventors = soup.find_all("dd", {"itemprop": "inventor"})
        if inventors:
            names = [inv.get_text(strip=True) for inv in inventors]
            content_parts.insert(1, f"Inventors: {', '.join(names)}")

        assignee = soup.find("dd", {"itemprop": "assigneeCurrent"}) or soup.find("dd", {"itemprop": "assigneeOriginal"})
        if assignee:
            content_parts.insert(2, f"Assignee: {assignee.get_text(strip=True)}")

        final_text = "\n\n".join([part for part in content_parts if part.strip()])
        if len(final_text.strip()) < 30:
            return None

        return html.unescape(final_text.strip())

    except Exception as e:
        logger.warning(f"Error fetching Google Patent content: {str(e)}")
        return None

# === Updated upload_and_explain (now supports OCR) ===
def upload_and_explain(file_path=None, content=None):
    try:
        if file_path:
            # Agar PDF hai → smart extraction
            if file_path.lower().endswith(".pdf"):
                extracted_text = extract_text_from_pdf_smart(file_path)
                if extracted_text:
                    content = extracted_text
                else:
                    return "Error: Could not extract any text from the PDF. It might be a heavily scanned or protected file."

            # Agar content nahi mila aur PDF hai → fall back to normal upload
            if not content:
                with open(file_path, "rb") as f:
                    uploaded_file = client.files.create(file=f, purpose="assistants")
            else:
                # Content ko temp file mein daal ke upload
                with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
                    tmp.write(content.encode("utf-8"))
                    tmp_path = tmp.name
                with open(tmp_path, "rb") as f:
                    uploaded_file = client.files.create(file=f, purpose="assistants")
                os.remove(tmp_path)

        elif content:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
                tmp.write(content.encode("utf-8"))
                tmp.flush()
            with open(tmp.name, "rb") as f:
                uploaded_file = client.files.create(file=f, purpose="assistants")
            os.remove(tmp.name)
        else:
            raise ValueError("No file or content provided.")

        thread = client.beta.threads.create(
            messages=[{
                "role": "user",
                "content": "Please explain the uploaded document in detail.",
                "attachments": [{"file_id": uploaded_file.id, "tools": [{"type": "file_search"}]}]
            }]
        )
        run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=get_assistant_id())
        while True:
            status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            if status.status in ["completed", "failed", "cancelled"]:
                break
            time.sleep(2)

        messages = client.beta.threads.messages.list(thread_id=thread.id)
        explanation = "No explanation generated."
        for msg in messages.data:
            if msg.role == "assistant":
                explanation = msg.content[0].text.value
                break

        session["thread_id"] = thread.id
        session["file_id"] = uploaded_file.id
        return explanation

    except Exception as e:
        logger.error(f"Error in upload_and_explain: {str(e)}")
        return f"Error: {str(e)}"

# === Rest of your code unchanged ===
def answer_question(thread_id, file_id, question):
    try:
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=question,
            attachments=[{"file_id": file_id, "tools": [{"type": "file_search"}]}]
        )
        run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=get_assistant_id())
        while True:
            status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            if status.status in ["completed", "failed"]:
                break
            time.sleep(1)
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        for msg in messages.data:
            if msg.role == "assistant":
                return msg.content[0].text.value
        return "No answer found."
    except Exception as e:
        logger.error(f"Q&A error: {str(e)}")
        return f"Error: {str(e)}"

@app.route("/", methods=["GET", "POST"])
def index():
    result = session.get("result", "")
    answer = ""

    if request.method == "GET":
        if "file_id" in session:
            try:
                client.files.delete(session["file_id"])
            except:
                pass
        session.clear()

    if request.method == "POST":
        file = request.files.get("file")
        link = request.form.get("link", "").strip()
        question = request.form.get("question", "").strip()

        try:
            if file and file.filename:
                ext = os.path.splitext(file.filename)[1].lower()
                allowed_ext = {".pdf", ".docx", ".txt", ".md", ".csv", ".pptx", ".xlsx", ".json"}
                if ext not in allowed_ext:
                    result = f"Error: Unsupported file type ({ext})."
                else:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                        file.save(tmp.name)
                        result = upload_and_explain(file_path=tmp.name)
                    os.remove(tmp.name)
                session["result"] = result

            elif link:
                content = fetch_google_patent_content(link)
                if not content:
                    result = "Error: Could not fetch content from Google Patents."
                else:
                    result = upload_and_explain(content=content)
                session["result"] = result

            if question and "thread_id" in session and "file_id" in session:
                answer = answer_question(session["thread_id"], session["file_id"], question)
            elif question:
                answer = "Please upload a document or link first."

        except Exception as e:
            logger.error(f"Request error: {str(e)}")
            result = f"Error: {str(e)}"

    return render_template("index.html", result=result, answer=answer)


from flask_cors import CORS  # CORS handle karne ke liye

CORS(app)  # ye allow karega cross-origin requests


@app.route("/api/start-analysis", methods=["POST"])
def start_analysis():
    try:
        file = request.files.get("file")
        link = request.form.get("link", "").strip()
        result = ""

        if file:
            ext = os.path.splitext(file.filename)[1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                file.save(tmp.name)
                result = upload_and_explain(file_path=tmp.name)
            os.remove(tmp.name)

        elif link:
            content = fetch_google_patent_content(link)
            if content:
                result = upload_and_explain(content=content)
            else:
                result = "Could not fetch content from Google Patents."

        session_id = str(uuid.uuid4())
        active_sessions[session_id] = {
            "thread_id": session.get("thread_id"),
            "file_id": session.get("file_id")
        }
        return {"result": result, "sessionId": session_id}, 200

    except Exception as e:
        return {"result": f"Error: {str(e)}"}, 500

@app.route("/api/ask-question/<session_id>", methods=["POST"])
@app.route("/api/ask-question", methods=["POST"])
def ask_question_api(session_id=None):
    try:
        sid = session_id or request.form.get("session_id") or request.form.get("sessionId")
        question = request.form.get("question", "").strip()
        if not question and request.is_json:
            data = request.get_json(silent=True) or {}
            question = data.get("question", "").strip()
            sid = sid or data.get("session_id") or data.get("sessionId")

        if not question:
            return {"error": "Question is required"}, 400

        sess_info = active_sessions.get(sid) or {}
        thread_id = sess_info.get("thread_id") or session.get("thread_id")
        file_id = sess_info.get("file_id") or session.get("file_id")

        if not thread_id or not file_id:
            return {"error": "No active session found. Please analyze a patent document first."}, 400

        answer = answer_question(thread_id, file_id, question)
        return {"answer": answer}, 200
    except Exception as e:
        logger.error(f"QA API error: {str(e)}")
        return {"error": str(e)}, 500

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
