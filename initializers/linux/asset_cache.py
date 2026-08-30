"""Local cache lookup for Linux setup seed assets."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = REPO_ROOT / "assets" / "linux_setup_cache"

HF_PATH_TO_CACHE = {
    "libreoffice_calc/4188d3a4-077d-46b7-9c86-23e1a036f6c1/Freeze_row_column2_gold.xlsx": (
        "libreoffice_calc/4188d3a4/Freeze_row_column2_gold.xlsx"
    ),
    "libreoffice_impress/bf4e9888-f10f-47af-8dba-76413038b73c/4.3-Template_4.29.2016_Gold.pptx": (
        "libreoffice_impress/bf4e9888/4.3-Template_4.29.2016_Gold.pptx"
    ),
    "libreoffice_writer/4bcb1253-a636-4df4-8cb0-a35c04dfef31/View_Person_Organizational_Summary.docx": (
        "libreoffice_writer/4bcb1253/View_Person_Organizational_Summary.docx"
    ),
    "thunderbird/dd84e895-72fd-4023-a336-97689ded257c/thunderbird-profile.tar.gz": (
        "thunderbird/dd84e895/thunderbird-profile.tar.gz"
    ),
    "thunderbird/d38192b0-17dc-4e1d-99c3-786d0117de77/show-thunderbird-attachments.py": (
        "thunderbird/d38192b0/show-thunderbird-attachments.py"
    ),
    "thunderbird/d38192b0-17dc-4e1d-99c3-786d0117de77/cssselect-1.3.0-py3-none-any.whl": (
        "thunderbird/d38192b0/cssselect-1.3.0-py3-none-any.whl"
    ),
}


def local_cache_for_url(url: str) -> Path | None:
    """Return a local cached file for a known Hugging Face setup URL."""
    parsed = urlparse(url)
    if parsed.netloc != "huggingface.co":
        return None
    marker = "/resolve/main/"
    if marker not in parsed.path:
        return None
    repo_path = unquote(parsed.path.split(marker, 1)[1].lstrip("/"))
    local_rel = HF_PATH_TO_CACHE.get(repo_path)
    if not local_rel:
        return None
    candidate = CACHE_ROOT / local_rel
    return candidate if candidate.is_file() else None
