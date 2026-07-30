FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . /app/

# Create data directory for SQLite
RUN mkdir -p /app/data

# Set PYTHONPATH for module imports
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Set Flask app module path
ENV FLASK_APP=app.app

# Expose port
EXPOSE 5000

# Run the application
WORKDIR /app
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5000"]
