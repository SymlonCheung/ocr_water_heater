"""OCR Processing logic (Pure Logic)."""
import logging
import cv2
import numpy as np
import PIL.Image
import ddddocr

from .const import (
    RESIZE_FACTOR, SIDE_CROP_PIXELS, UNSHARP_AMOUNT,
    VALID_MIN, VALID_MAX, MODE_A_SMART_SLIM, MODE_A_SLIM_THRESHOLD, MODE_A_FORCE_ERODE,
    SPLIT_OVERLAP_PX, SOLVER_THRESHOLDS, CHAR_REPLACE_MAP,
    DEFAULT_ROI, DEFAULT_SKEW
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
        return clean, raw_text

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

    def _keep_largest_contour(self, binary_img, is_right_split=False):
        if cv2.countNonZero(binary_img) > (binary_img.size * 0.5):
            work_img = cv2.bitwise_not(binary_img)
        else:
            work_img = binary_img.copy()
        contours, _ = cv2.findContours(work_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours: return binary_img
        
        candidates = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if cv2.contourArea(cnt) < 30: continue
            if is_right_split and x <= 2: continue
            candidates.append(cnt)
        
        if not candidates: candidates = contours
        max_cnt = max(candidates, key=cv2.contourArea)
        mask = np.zeros_like(work_img)
        cv2.drawContours(mask, [max_cnt], -1, 255, thickness=cv2.FILLED)
        return cv2.bitwise_not(mask)

    def _center_digit_on_canvas(self, binary_img, is_right_split=False):
        cleaned_img = self._keep_largest_contour(binary_img, is_right_split)
        work_img = cv2.bitwise_not(cleaned_img)
        coords = cv2.findNonZero(work_img)
        if coords is None: return cleaned_img
        x, y, w, h = cv2.boundingRect(coords)
        
        if w < 2 or h < 5: return cleaned_img 

        digit_crop = work_img[y:y+h, x:x+w]
        target_height = 50
        canvas_size = (80, 80)
        scale = target_height / float(h)
        new_w = int(w * scale) if int(w * scale) > 0 else 1
        
        if new_w > 70: new_w = 70
        
        resized_digit = cv2.resize(digit_crop, (new_w, target_height), interpolation=cv2.INTER_AREA if new_w > 70 else cv2.INTER_CUBIC)
        
        canvas = np.zeros(canvas_size, dtype=np.uint8)
        start_x = max(0, (canvas_size[0] - new_w) // 2)
        start_y = max(0, (canvas_size[1] - target_height) // 2)
        
        paste_w = min(new_w, canvas_size[0] - start_x)
        paste_h = min(target_height, canvas_size[1] - start_y)
        
        canvas[start_y:start_y+paste_h, start_x:start_x+paste_w] = resized_digit[:paste_h, :paste_w]
        return cv2.bitwise_not(canvas)

    def _preprocess_base(self, image, debug_store):
        x, y, w, h = self._roi
        h_img, w_img = image.shape[:2]
        
        if x+w > w_img or y+h > h_img:
            if x >= w_img or y >= h_img: return None
            roi = image[max(0, y):min(h_img, y+h), max(0, x):min(w_img, x+w)]
        else:
            roi = image[y:y+h, x:x+w]
            
        if roi.size == 0: return None
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        if self._skew != 0:
            rows, cols = gray.shape
            theta = np.deg2rad(self._skew)
            M = np.float32([[1, np.tan(theta), 0], [0, 1, 0]])
            new_width = int(cols + rows * np.abs(np.tan(theta)))
            gray = cv2.warpAffine(gray, M, (new_width, rows), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

        new_dim = (int(gray.shape[1] * RESIZE_FACTOR), int(gray.shape[0] * RESIZE_FACTOR))
        gray = cv2.resize(gray, new_dim, interpolation=cv2.INTER_CUBIC)
        if SIDE_CROP_PIXELS > 0 and gray.shape[1] > 2 * SIDE_CROP_PIXELS:
            gray = gray[:, SIDE_CROP_PIXELS : -SIDE_CROP_PIXELS]

        gray = self._unsharp_mask(gray, amount=UNSHARP_AMOUNT)
        # 保存中间图到字典
        debug_store["00_Base.jpg"] = gray
        return gray

    def _run_mode_a(self, gray_base, debug_store):
        gamma = 1.5
        invGamma = 1.0 / gamma
        table = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
        gray_proc = cv2.LUT(gray_base, table)

        _, binary = cv2.threshold(gray_proc, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if cv2.countNonZero(binary) < (binary.size * 0.5):
            binary = cv2.bitwise_not(binary)

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
            cnts, _ = cv2.findContours(cv2.bitwise_not(eroded), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cnts:
                max_area = max([cv2.contourArea(c) for c in cnts])
                cnts_orig, _ = cv2.findContours(cv2.bitwise_not(binary), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                max_area_orig = max([cv2.contourArea(c) for c in cnts_orig]) if cnts_orig else 0
                if max_area_orig > 0 and max_area >= max_area_orig * 0.3:
                    binary = eroded
                    debug_store["01_ModeA_Slimmed.jpg"] = binary

        binary = cv2.copyMakeBorder(binary, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        debug_store["01_ModeA_Final.jpg"] = binary

        raw = self._dddd_ocr_core(binary)
        clean, _ = self._clean_ocr_text(raw)
        return clean

    def _run_mode_b(self, gray_base, debug_store):
        def find_split(g):
            _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            if cv2.countNonZero(b) < (b.size * 0.5): b = cv2.bitwise_not(b)
            vproj = np.sum(b == 0, axis=0)
            kernel = 3
            vproj_smooth = np.convolve(vproj, np.ones(kernel)/kernel, mode='same')
            mid_region = vproj_smooth[int(len(vproj)*0.2):int(len(vproj)*0.8)+1]
            return int(np.argmin(mid_region) + int(len(vproj)*0.2)) if np.min(mid_region) < 0.3 * np.max(vproj_smooth) else None

        h, w = gray_base.shape
        mid = find_split(gray_base)
        if mid is None:
            mid = w // 2

        left_part = gray_base[:, :max(1, mid + SPLIT_OVERLAP_PX)]
        right_part = gray_base[:, max(0, mid - SPLIT_OVERLAP_PX):]

        def solve(img_p, tag, is_r):
            gamma = 1.5; invG = 1.0/gamma
            tbl = np.array([((i/255.0)**invG)*255 for i in range(256)]).astype("uint8")
            i_s = cv2.LUT(img_p, tbl)
            _, b_s = cv2.threshold(i_s, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
            if cv2.countNonZero(b_s)<b_s.size*0.5: b_s=cv2.bitwise_not(b_s)
            b_s = cv2.erode(b_s, np.ones((2,2),np.uint8), iterations=1)
            can_s = self._center_digit_on_canvas(b_s, is_r)
            debug_store[f"{tag}_1_Slim.jpg"] = can_s
            if (r:= self._dddd_ocr_core(can_s)): return self._clean_ocr_text(r)[0]
            
            for i, th in enumerate(SOLVER_THRESHOLDS):
                _, b_f = cv2.threshold(img_p, th, 255, cv2.THRESH_BINARY)
                if cv2.countNonZero(b_f)>b_f.size*0.7: b_f=cv2.bitwise_not(b_f)
                can_f = self._center_digit_on_canvas(b_f, is_r)
                debug_store[f"{tag}_2_Thresh_{th}.jpg"] = can_f
                if (r:= self._dddd_ocr_core(can_f)): return self._clean_ocr_text(r)[0]
            return ""

        val_l = solve(left_part, "Left", False)
        val_r = solve(right_part, "Right", True)
        return val_l + val_r if (val_l and val_r) else ""

    def process_image(self, img_bytes):
        """
        主函数。
        Returns:
            tuple: (final_result_int | None, debug_images_dict)
        """
        debug_imgs = {} # 用来存图片的字典
        
        if not img_bytes: return None, debug_imgs
        try:
            image_array = np.asarray(bytearray(img_bytes), dtype=np.uint8)
            img_origin = cv2.imdecode(image_array, -1)
        except Exception:
            return None, debug_imgs

        if img_origin is None: return None, debug_imgs

        # 1. 预处理
        gray_base = self._preprocess_base(img_origin, debug_imgs)
        if gray_base is None: return None, debug_imgs

        # 2. Mode A
        res_a = self._run_mode_a(gray_base, debug_imgs)
        if len(res_a) == 2:
            try:
                val = int(res_a)
                if VALID_MIN <= val <= VALID_MAX:
                    return val, debug_imgs
            except: pass

        # 3. Mode B
        res_b = self._run_mode_b(gray_base, debug_imgs)
        if len(res_b) == 2:
            try:
                val = int(res_b)
                if VALID_MIN <= val <= VALID_MAX:
                    return val, debug_imgs
            except: pass
            
        return None, debug_imgs