FROM python:3.11-slim

# Working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port for the app
EXPOSE 8000

# Add Google auth if not already present
ENV USE_GKE_GCLOUD_AUTH_PLUGIN=True

# Startup
CMD ["python", "main.py"]