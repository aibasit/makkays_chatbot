FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for compiling packages and database drivers
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Install development/test dependencies
RUN pip install --no-cache-dir pytest pytest-asyncio httpx psycopg2-binary ruff

# Copy the application source code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
