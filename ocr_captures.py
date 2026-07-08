"""OCR every screenshot in captures/ using the built-in Windows OCR engine.

Uses winrt (Windows.Media.Ocr) so it needs no Tesseract binary and no Pillow
(both unavailable in this Python). Writes the extracted text to captures/ocr.txt
so the build/tune screens can be read as text instead of vision-reading each PNG.

Usage:
  python ocr_captures.py            # OCR captures/*.png
  python ocr_captures.py "cat5*"    # OCR a subset
"""
import asyncio
import sys
import pathlib

from winrt.windows.media.ocr import OcrEngine
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder, SoftwareBitmap, BitmapPixelFormat
from winrt.windows.storage import StorageFile, FileAccessMode

CAPTURES = pathlib.Path("captures")


def _engine():
    eng = OcrEngine.try_create_from_user_profile_languages()
    if eng is None:
        eng = OcrEngine.try_create_from_language(Language("en-US"))
    if eng is None:
        raise RuntimeError("No Windows OCR language pack installed.")
    return eng


async def ocr_file(engine, path: pathlib.Path) -> str:
    file = await StorageFile.get_file_from_path_async(str(path.resolve()))
    stream = await file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    if bitmap.bitmap_pixel_format != BitmapPixelFormat.BGRA8:
        bitmap = SoftwareBitmap.convert(bitmap, BitmapPixelFormat.BGRA8)
    result = await engine.recognize_async(bitmap)
    return result.text or ""


async def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*.png"
    files = sorted(CAPTURES.glob(pattern))
    if not files:
        print(f"no images match {pattern!r} in {CAPTURES}/")
        return
    engine = _engine()
    blocks = []
    for p in files:
        try:
            text = await ocr_file(engine, p)
        except Exception as e:
            text = f"[OCR error: {e!r}]"
        blocks.append(f"=== {p.name} ===\n{text}")
        print(f"{p.name}: {text[:150]}")
    (CAPTURES / "ocr.txt").write_text("\n\n".join(blocks), encoding="utf-8")
    print(f"\nwrote {CAPTURES / 'ocr.txt'} ({len(files)} images)")


if __name__ == "__main__":
    asyncio.run(main())
