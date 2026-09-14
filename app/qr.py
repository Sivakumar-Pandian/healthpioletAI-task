import io
import qrcode
from qrcode.image.pil import PilImage


def generate_qr_bytes(data: str, box_size: int = 8, border: int = 2) -> bytes:
    """Generates PNG bytes for the given data string."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img: PilImage = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
