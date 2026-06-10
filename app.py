"""
AI Manhwa Translator - Backend (Python Flask)
✅ FIXED: CORS, error handling, timeout, file size, OCR improvements
Deploy: Render.com (bepul)
"""

import os
import io
import base64
import json
import requests
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

app = Flask(__name__)
CORS(app, resources={
    r"/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "max_age": 3600
    }
})

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
OCR_SPACE_API_KEY = os.environ.get("OCR_SPACE_API_KEY", "K81851527588957")
MAX_PAGES = 20
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
OCR_TIMEOUT = 60  # 60 seconds


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def pdf_to_images(pdf_bytes: bytes, dpi: int = 150) -> list:
    """PDF → PNG images (base64) using PyMuPDF"""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        
        for i, page in enumerate(doc):
            if i >= MAX_PAGES:
                break
            
            try:
                mat = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                img_bytes = pix.tobytes("png")
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                
                pages.append({
                    "index": i,
                    "base64": b64,
                    "width": pix.width,
                    "height": pix.height,
                })
            except Exception as e:
                print(f"Page {i} konvertatsiya xatosi: {e}")
                continue
        
        doc.close()
        return pages
    except Exception as e:
        raise Exception(f"PDF konvertatsiya xatosi: {str(e)}")


def ocr_image(base64_img: str) -> dict:
    """
    Server ichidagi Tesseract orqali inglizcha matnlarni mutlaqo bepul va tez o'qish
    """
    try:
        import pytesseract
        
        # Base64 rasmni PIL formatiga o'tkazish
        img_bytes = base64.b64decode(base64_img)
        img = Image.open(io.BytesIO(img_bytes))
        
        # Tesseract orqali matn va koordinatalarni olish
        data = pytesseract.image_to_data(img, lang="eng", output_type=pytesseract.Output.DICT)
        
        full_text = " ".join(data["text"]).strip()
        lines = []
        
        # Har bir so'z koordinatasini hisoblash
        for i in range(len(data["text"])):
            word_text = data["text"][i].strip()
            if not word_text or len(word_text) < 2:
                continue
                
            lines.append({
                "text": word_text,
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i])
            })
            
        return {"text": full_text, "lines": lines}
        
    except Exception as e:
        return {"text": "", "lines": [], "error": f"Tesseract OCR xatosi: {str(e)}"}


def draw_translated_image(base64_img: str, translations: list) -> str:
    """
    Photoshop kabi Inpainting (sezilmas o'chirish) algoritmi bilan matnni almashtirish
    """
    try:
        import cv2
        import numpy as np
        
        # 1. Base64 dan rasmni yuklab OpenCV formatiga (NumPy) o'tkazamiz
        img_bytes = base64.b64decode(base64_img)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # 2. Matnlar turgan joy uchun qora rangda bo'sh maska (niqob) yaratamiz
        mask = np.zeros(img_cv.shape[:2], dtype=np.uint8)
        
        # 3. Maska yuziga matnlar turgan joylarni oq rangda chizib chiqamiz
        for item in translations:
            x = int(item.get("x", 0))
            y = int(item.get("y", 0))
            w = int(item.get("w", 100))
            h = int(item.get("h", 30))
            if not str(item.get("translated", "")).strip():
                continue
                
            # Matn atrofini biroz kengroq olib maskaga oq quti chizamiz
            padding = 2
            cv2.rectangle(mask, (x - padding, y - padding), (x + w + padding, y + h + padding), 255, -1)
            
        # 4. ENGMUHIM JOYI: OpenCV Navier-Stokes inpainting algoritmi yordamida 
        # rasm yuzidagi barcha oq qutilarni (matnlarni) sezilmas qilib o'chirib, fonni tiklaymiz!
        inpainted_img = cv2.inpaint(img_cv, mask, inpaintRadius=3, flags=cv2.INPAINT_NS)
        
        # 5. Tozalangan rasmni matn yozish uchun PIL formatiga qaytaramiz
        img_pil = Image.fromarray(cv2.cvtColor(inpainted_img, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img_pil)
        
        # Shriftni sozlash
        font_size = 14
        try:
            font = ImageFont.truetype("LiberationSans-Regular.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()

        # 6. Endi tozalangan rasm yuziga yangi o'zbekcha matnlarni chizamiz
        for item in translations:
            x = int(item.get("x", 0))
            y = int(item.get("y", 0))
            w = int(item.get("w", 100))
            uz_text = str(item.get("translated", ""))
            if not uz_text.strip():
                continue
                
            # Matn rasm ustida har qanday fonda (och yoki to'q) ideal o'qilishi uchun
            # unga qora rangda soya (outline/stroke) berib, ichini oq rangda yozamiz
            wrapped = wrap_text(uz_text, font, w)
            text_y = y
            for line in wrapped:
                draw.text(
                    (x, text_y), 
                    line, 
                    fill="white", 
                    font=font,
                    stroke_width=2,
                    stroke_fill="#1a1a1a" # Qora soya
                )
                text_y += font_size + 2

        # PNG → base64 formatiga qaytarish
        buf = io.BytesIO()
        img_pil.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
        
    except Exception as e:
        raise Exception(f"Typesetting xatosi: {str(e)}")

        # PNG → base64
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    
    except Exception as e:
        raise Exception(f"Typesetting xatosi: {str(e)}")



def wrap_text(text: str, font, max_width: int) -> list:
    """Matnni berilgan kenglikka moslab qatorlarga bo'lish"""
    if not text or not text.strip():
        return []
    
    words = text.split()
    lines, current = [], ""
    
    for word in words:
        test = (current + " " + word).strip()
        try:
            bbox = font.getbbox(test)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(test) * 7
        
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    
    if current:
        lines.append(current)
    
    return lines if lines else [text[:30]] if text else []


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────


@app.route("/")
def home():
    return render_template("index.html")


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        return "", 204


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AI Manhwa Translator",
        "version": "2.0"
    }), 200


@app.route("/convert-pdf", methods=["POST"])
def convert_pdf():
    """
    POST /convert-pdf
    Body: multipart/form-data { file: PDF }
    Returns: { pages: [ { index, base64, width, height } ] }
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "PDF fayl yuborilmadi"}), 400

        pdf_file = request.files["file"]
        
        if not pdf_file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "Faqat PDF format qabul qilinadi"}), 400

        pdf_bytes = pdf_file.read()
        
        if len(pdf_bytes) > MAX_FILE_SIZE:
            return jsonify({
                "error": f"PDF hajmi {MAX_FILE_SIZE // 1024 // 1024}MB dan oshmasligi kerak"
            }), 400

        if len(pdf_bytes) == 0:
            return jsonify({"error": "PDF fayl bo'sh"}), 400

        pages = pdf_to_images(pdf_bytes)
        
        if not pages:
            return jsonify({"error": "PDF-dan sahifa ajratib bo'lmadi"}), 500

        return jsonify({
            "pages": pages,
            "total": len(pages),
            "status": "success"
        }), 200

    except Exception as e:
        return jsonify({"error": f"PDF konvertatsiya xatosi: {str(e)}"}), 500


@app.route("/ocr", methods=["POST"])
def ocr():
    """
    POST /ocr
    Body: JSON { base64: "..." }
    Returns: { text: str, lines: [...] }
    """
    try:
        data = request.get_json()
        
        if not data or "base64" not in data:
            return jsonify({"error": "base64 rasm yuborilmadi"}), 400

        result = ocr_image(data["base64"])
        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": f"OCR xatosi: {str(e)}"}), 500


@app.route("/typeset", methods=["POST"])
def typeset():
    """
    POST /typeset
    Body: JSON { base64: "...", translations: [ {x,y,w,h,translated} ] }
    Returns: { base64: "..." }
    """
    try:
        data = request.get_json()
        
        if not data or "base64" not in data:
            return jsonify({"error": "Rasm yuborilmadi"}), 400

        translations = data.get("translations", [])
        result_b64 = draw_translated_image(data["base64"], translations)
        
        return jsonify({
            "base64": result_b64,
            "status": "success"
        }), 200

    except Exception as e:
        return jsonify({"error": f"Typesetting xatosi: {str(e)}"}), 500


# ─────────────────────────────────────────────
# ERROR HANDLERS
# ─────────────────────────────────────────────

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint topilmadi"}), 404


@app.errorhandler(500)
def server_error(error):
    return jsonify({"error": "Server xatosi"}), 500


# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
