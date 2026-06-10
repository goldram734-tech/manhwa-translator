# Python-ning rasmiy yengil versiyasini olamiz
FROM python:3.10-slim

# Tesseract va uning koreys tili paketini o'rnatamiz
# Shuningdek, OpenCV uchun kerakli tizim kutubxonalarini ham qo'shamiz
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-kor \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Server ichida ishchi papka yaratamiz
WORKDIR /app

# Kutubxonalar ro'yxatini ko'chirib, ularni o'rnatamiz
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Loyihaning barcha kodlarini serverga ko'chiramiz
COPY . .

# Loyihani ishga tushirish buyrug'i (main.py o'rniga asosiy faylingiz nomini yozing)
CMD ["python", "main.py"]
