# Patent Understanding Assistant (Advanced)

## Overview
This project fetches patent/application text via USPTO APIs (official), processes text with an NLP pipeline, and outputs:
- Plain-language patent summary
- A simple real-world analogy
- Definitions for difficult/legal terms present in the document

## Setup
1. Create virtualenv and activate
```bash
python -m venv venv
source venv/bin/activate   # on Windows use venv\Scripts\activate
pip install -r requirements.txt
```

2. Add your USPTO API key to environment variable:
```bash
export USPTO_API_KEY="your_key_here"
```

3. (Optional) Download spaCy model
```bash
python -m spacy download en_core_web_sm
```

## Run CLI demo
```bash
python src/main.py --patent-numbers 16782745 16782746 --outdir output
```

## Run Streamlit demo
```bash
streamlit run streamlit_app.py
```
