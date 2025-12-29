# Use Python 3.10 slim image (lightweight and stable)
FROM python:3.10-slim

# Set working directory inside the container
WORKDIR /app

# --- 1. SYSTEM DEPENDENCIES ---
# Install FFmpeg (required for audio processing) and build tools
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# --- 2. PYTHON DEPENDENCIES ---
# Copy requirements first to leverage Docker caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Install Gunicorn (Production Server)
RUN pip install gunicorn

# --- 3. COPY APPLICATION CODE ---
# Copy the entire project into the container
COPY . .

# --- 4. CONFIGURATION ---
# Expose the port Flask runs on
EXPOSE 5000

# Set environment variables to ensure Python output is logged immediately
ENV PYTHONUNBUFFERED=1

# --- 5. START COMMAND ---
# Run the Flask app using Gunicorn
# Timeout is increased to 120s to handle AI processing delays
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--timeout", "120"]