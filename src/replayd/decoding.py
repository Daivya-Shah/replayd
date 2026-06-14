import gzip
import zlib
from collections.abc import Mapping


def _content_encoding(headers: Mapping[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == "content-encoding":
            return value.split(",")[0].strip().lower()
    return None


def decode_body(raw: bytes, headers: Mapping[str, str]) -> bytes:
    encoding = _content_encoding(headers)
    if encoding in (None, "", "identity"):
        return raw

    try:
        if encoding == "gzip":
            return gzip.decompress(raw)
        if encoding == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except Exception:
        return raw

    return raw
