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
# Install CPU-only torch first, from PyTorch's own CPU wheelhouse — this project never
# uses a GPU, but FlagEmbedding's default resolution otherwise pulls in the full NVIDIA
# CUDA toolkit (several GB of unused downloads). Installing it here first means the
# `pip install -r requirements.txt` below sees torch already satisfied and skips it.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt
# Install development/test dependencies
RUN pip install --no-cache-dir pytest pytest-asyncio httpx psycopg2-binary ruff

# Copy the application source code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
