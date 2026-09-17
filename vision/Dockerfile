FROM python:3.12-slim

# opencv-python (no headless, la pide webcam_test.py para GUI local) necesita
# libGL en tiempo de import aunque acá adentro nunca se use ventana/cámara.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python"]
CMD ["train.py", "--help"]
