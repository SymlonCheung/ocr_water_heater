"""OCR Processing logic (Simplified)."""
import logging
import cv2
import numpy as np
import PIL.Image
import ddddocr
from .const import (
    RESIZE_FACTOR, SIDE_CROP_PIXELS, UNSHARP_AMOUNT, VALID_MIN, VALID_MAX,
    MODE_A_SMART_SLIM, MODE_A_SLIM_THRESHOLD, MODE_A_FORCE_ERODE,
    CHAR_REPLACE_MAP, DEFAULT_ROI, DEFAULT_SKEW
)

_LOGGER = logging.getLogger(__name__)

if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

class OCRProcessor:
    """Class to handle OCR logic only."""

    def __init__(self):
        self._ocr_engine = None
        self._roi = DEFAULT_ROI
        self._skew = DEFAULT_SKEW
        self._init_engine()

    def configure(self, roi, skew):
        """Update parameters."""
        self._roi = roi
        self._skew = skew

    def _init_engine(self):
        try:
            try:
                self._ocr_engine = ddddocr.DdddOcr(show_ad=False)
            except TypeError:
                self._ocr_engine = ddddocr.DdddOcr()
            self._ocr_engine.set_ranges("0123456789")
        except Exception as e:
            _LOGGER.error("Failed to initialize ddddocr: %s", e)

    def _unsharp_mask(self, image, amount=1.5):
        blurred = cv2.GaussianBlur(image, (5, 5), 1.0)
        sharpened = float(amount + 1) * image - float(amount) * blurred
        sharpened = np.maximum(sharpened, 0)
        sharpened = np.minimum(sharpened, 255)
        return sharpened.astype(np.uint8)

    def _clean_ocr_text(self, raw_text):
        raw_text = raw_text.strip()
        clean = ""
        for char in raw_text:
            if char in CHAR_REPLACE_MAP:
                clean += CHAR_REPLACE_MAP[char]
            elif char.isdigit():
                clean += char
        return clean

    def _dddd_ocr_core(self, image):
        try:
            _, buf = cv2.imencode(".jpg", image)
            bytes_img = buf.tobytes()
            res = self._ocr_engine.classification(bytes_img, probability=True)
            txt = ""
            for prob in res['probability']:
                txt += res['charsets'][prob.index(max(prob))]
            return txt
        except Exception:
            return ""

    def _preprocess_base(self, image, debug_store):
        x, y, w, h = self._roi
        h_img, w_img = image.shape[:2]
        
        # ROI Crop
        roi = image[max(0, y):min(h_img, y+h), max(0, x):min(w_img, x+w)]
        if roi.size == 0:
            return None
        
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        # Skew Correction
        if self._skew != 0:
            rows, cols = gray.shape
            theta = np.deg2rad(self._skew)
            M = np.float32([[1, np.tan(theta), 0], [0, 1, 0]])
            new_width = int(cols + rows * np.abs(np.tan(theta)))
            gray = cv2.warpAffine(gray, M, (new_width, rows), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

        # Resize
        new_dim = (int(gray.shape[1] * RESIZE_FACTOR), int(gray.shape[0] * RESIZE_FACTOR))
        gray = cv2.resize(gray, new_dim, interpolation=cv2.INTER_CUBIC)

        # Side Crop
        if SIDE_CROP_PIXELS > 0 and gray.shape[1] > 2 * SIDE_CROP_PIXELS:
            gray = gray[:, SIDE_CROP_PIXELS : -SIDE_CROP_PIXELS]

        # Sharpen
        gray = self._unsharp_mask(gray, amount=UNSHARP_AMOUNT)
        debug_store["00_Base.jpg"] = gray
        return gray

    def process_image(self, img_bytes):
        """
        Main function. Processes image using single-pass OCR.
        """
        debug_imgs = {}
        if not img_bytes:
            return None, debug_imgs

        try:
            image_array = np.asarray(bytearray(img_bytes), dtype=np.uint8)
            img_origin = cv2.imdecode(image_array, -1)
        except Exception:
            return None, debug_imgs

        if img_origin is None:
            return None, debug_imgs

        # 1. 预处理
        gray_base = self._preprocess_base(img_origin, debug_imgs)
        if gray_base is None:
            return None, debug_imgs

        # 2. 图像增强 (Gamma & Otsu Binary)
        gamma = 1.5
        invGamma = 1.0 / gamma
        table = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
        gray_proc = cv2.LUT(gray_base, table)
        
        _, binary = cv2.threshold(gray_proc, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # 确保背景为白色 (ddddocr 识别习惯)
        if cv2.countNonZero(binary) < (binary.size * 0.5):
            binary = cv2.bitwise_not(binary)

        # 3. 细化处理 (Slimming logic)
        black_ratio = (binary.size - cv2.countNonZero(binary)) / binary.size
        iterations = 0
        if MODE_A_FORCE_ERODE:
            iterations = 1
        elif MODE_A_SMART_SLIM and black_ratio > MODE_A_SLIM_THRESHOLD:
            excess = (black_ratio - MODE_A_SLIM_THRESHOLD) / (0.5 - MODE_A_SLIM_THRESHOLD)
            iterations = int(np.clip(round(excess * 2), 1, 2))

        if iterations > 0:
            kernel = np.ones((2, 2), np.uint8)
            eroded = cv2.erode(binary, kernel, iterations=iterations)
            # 简单的连通域面积检查，防止腐蚀过度
            cnts, _ = cv2.findContours(cv2.bitwise_not(eroded), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cnts:
                binary = eroded

        # 4. 留白填充 (Padding 提高识别率)
        binary = cv2.copyMakeBorder(binary, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        debug_imgs["01_Final_Binary.jpg"] = binary

        # 5. 执行 OCR
        raw = self._dddd_ocr_core(binary)
        clean_res = self._clean_ocr_text(raw)

        # 6. 验证结果
        if clean_res:
            try:
                val = int(clean_res)
                if VALID_MIN <= val <= VALID_MAX:
                    return val, debug_imgs
            except ValueError:
                pass

        return None, debug_imgs
