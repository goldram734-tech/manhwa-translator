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
    Google Lens API orqali rasmdan inglizcha matnlarni o'qish (Tezkor va bepul)
    Returns: { "text": str, "lines": [...] }
    """
    try:
        from chrome_lens_py import ChromeLens as GoogleLens
        
        # Base64 rasmni baytlarga o'girish
        img_bytes = base64.b64decode(base64_img)
        
        # Google Lens orqali sknerlash (Ingliz tili rejimi)
        lens = GoogleLens()
        data = lens.match(img_bytes, lang="en")
        
        full_text = data.get("text", "").strip()
        lines = []
        
        # Google Lens natijalarini loyihamiz formatiga moslash
        for block in data.get("blocks", []):
            line_text = block.get("text", "").strip()
            if not line_text:
                continue
                
            # Koordinatalarni olish (Google Lens o'lchamlari)
            box = block.get("box", {})
            left = box.get("left", 0)
            top = box.get("top", 0)
            width = box.get("width", 100)
            height = box.get("height", 30)
            
            lines.append({
                "text": line_text,
                "x": int(left),
                "y": int(top),
                "w": int(width),
                "h": int(height)
            })
            
        return {"text": full_text, "lines": lines}
        
    except Exception as e:
        return {"text": "", "lines": [], "error": f"Google Lens OCR xatosi: {str(e)}"}


def draw_translated_image(base64_img: str, translations: list) -> str:
    """
    Har bir OCR box ustiga:
    1. Oq to'rtburchak (original matnni berkitish)
    2. O'zbek matni yozish
    Returns: base64 PNG
    """
    try:
        img_bytes = base64.b64decode(base64_img)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Font — Unicode (O'zbek) uchun
        font_size = 14
        try:
            font = ImageFont.truetype("LiberationSans-Regular.ttf", font_size)
            font_bold = ImageFont.truetype("LiberationSans-Bold.ttf", font_size)
        except IOError:
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", font_size)
                font_bold = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
            except IOError:
                font = ImageFont.load_default()
                font_bold = ImageFont.load_default()

        for item in translations:
            try:
                x = int(item.get("x", 0))
                y = int(item.get("y", 0))
                w = int(item.get("w", 100))
                h = int(item.get("h", 30))
                uz_text = str(item.get("translated", ""))
                
                if not uz_text or not uz_text.strip():
                    continue

                # 1. Oq box (inpainting o'rniga)
                padding = 3
                draw.rectangle(
                    [x - padding, y - padding, x + w + padding, y + h + padding],
                    fill="white",
                    outline="#cccccc",
                    width=1,
                )

                # 2. Matn yozish (word wrap)
                wrapped = wrap_text(uz_text, font, w + padding * 2)
                text_y = y
                
                for line in wrapped:
                    if text_y + font_size > y + h + padding * 2 + 5:
                        break
                    try:
                        draw.text((x, text_y), line, fill="#1a1a1a", font=font)
                    except Exception:
                        pass
                    text_y += font_size + 2
            
            except Exception as e:
                print(f"Translation item xatosi: {e}")
                continue

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
