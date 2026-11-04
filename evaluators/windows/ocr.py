"""Read final-screen text, using Windows OCR when Tesseract is unavailable."""

import io
from pathlib import Path
import subprocess
import sys
import tempfile


def read_screenshot_text(data: bytes) -> str:
    from PIL import Image, ImageEnhance, ImageOps

    image = Image.open(io.BytesIO(data)).convert('RGB')
    prepared = ImageEnhance.Contrast(ImageOps.grayscale(image)).enhance(1.8)
    try:
        import pytesseract
        return pytesseract.image_to_string(prepared, config='--psm 6')
    except Exception:
        if sys.platform != 'win32':
            raise
    with tempfile.TemporaryDirectory(prefix='osomni-final-ocr-') as directory:
        image_path = Path(directory) / 'screen.png'
        prepared.save(image_path)
        script = Path(__file__).with_name('checks') / 'windows_ocr.ps1'
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
             '-File', str(script), '-ImagePath', str(image_path)],
            capture_output=True, encoding='utf8', errors='replace', timeout=25,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError('Windows OCR could not read the final screenshot')
        return result.stdout.strip()
