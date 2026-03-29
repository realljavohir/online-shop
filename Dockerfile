FROM python:3.9-slim

WORKDIR /app

# requirements.txt ni nusxalash va o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Barcha fayllarni nusxalash
COPY . .

# Botni ishga tushirish
CMD ["python", "run.py"]
