import hashlib


def content_hash(text: str) -> str:
    """Stable hash used to detect whether a job's description has actually
    changed, so background AI reprocessing (embedding, requirement
    extraction) can be skipped for edits that don't touch it."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
