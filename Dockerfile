# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first to leverage caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Expose port (Render sets $PORT dynamically)
ENV PORT=8000
EXPOSE 8000

# Run gunicorn with Render-compatible port and 120s timeout for OpenAI analysis
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8000} app:app --workers 1 --timeout 120"]
