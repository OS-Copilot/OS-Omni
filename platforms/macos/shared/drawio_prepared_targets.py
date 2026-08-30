from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PreparedDrawIOTarget = Tuple[str, str, float, float]

DRAWIO_PREPARED_TARGETS: Dict[str, List[PreparedDrawIOTarget]] = {
    "release_board_refresh.drawio": [
        ("Card 1", "card_1", 0.182, 0.307),
        ("Card 2", "card_2", 0.280, 0.307),
        ("Card 3", "card_3", 0.378, 0.307),
        ("Card 4", "card_4", 0.182, 0.418),
        ("Card 5", "card_5", 0.280, 0.418),
        ("Card 6", "card_6", 0.378, 0.418),
    ],
    "launch_matrix_sync.drawio": [
        ("Slot 1", "card_1", 0.175, 0.307),
        ("Slot 2", "card_2", 0.255, 0.307),
        ("Slot 3", "card_3", 0.336, 0.307),
        ("Slot 4", "card_4", 0.417, 0.307),
        ("Slot 5", "card_5", 0.497, 0.307),
        ("Slot 6", "card_6", 0.175, 0.412),
        ("Slot 7", "card_7", 0.255, 0.412),
        ("Slot 8", "card_8", 0.336, 0.412),
        ("Slot 9", "card_9", 0.417, 0.412),
        ("Slot 10", "card_10", 0.497, 0.412),
        ("Slot 11", "card_11", 0.175, 0.517),
        ("Slot 12", "card_12", 0.255, 0.517),
        ("Slot 13", "card_13", 0.336, 0.517),
        ("Slot 14", "card_14", 0.417, 0.517),
        ("Slot 15", "card_15", 0.497, 0.517),
        ("Slot 16", "card_16", 0.175, 0.622),
        ("Slot 17", "card_17", 0.255, 0.622),
        ("Slot 18", "card_18", 0.336, 0.622),
        ("Slot 19", "card_19", 0.417, 0.622),
        ("Slot 20", "card_20", 0.497, 0.622),
    ],
    "ops_plan_relabel.drawio": [
        ("Item 1", "card_1", 0.175, 0.307),
        ("Item 2", "card_2", 0.255, 0.307),
        ("Item 3", "card_3", 0.336, 0.307),
        ("Item 4", "card_4", 0.417, 0.307),
        ("Item 5", "card_5", 0.497, 0.307),
        ("Item 6", "card_6", 0.175, 0.412),
        ("Item 7", "card_7", 0.255, 0.412),
        ("Item 8", "card_8", 0.336, 0.412),
        ("Item 9", "card_9", 0.417, 0.412),
        ("Item 10", "card_10", 0.497, 0.412),
        ("Item 11", "card_11", 0.175, 0.517),
        ("Item 12", "card_12", 0.255, 0.517),
        ("Item 13", "card_13", 0.336, 0.517),
        ("Item 14", "card_14", 0.417, 0.517),
        ("Item 15", "card_15", 0.497, 0.517),
        ("Item 16", "card_16", 0.175, 0.622),
        ("Item 17", "card_17", 0.255, 0.622),
        ("Item 18", "card_18", 0.336, 0.622),
        ("Item 19", "card_19", 0.417, 0.622),
        ("Item 20", "card_20", 0.497, 0.622),
    ],
}


def extract_drawio_filename_from_window_title(title: str) -> Optional[str]:
    raw_title = str(title or "").strip()
    if not raw_title:
        return None
    match = re.search(r"([^/\\]+\.drawio)\b", raw_title)
    if not match:
        return None
    return match.group(1)


def resolve_prepared_drawio_target_id(
    filename: str,
    x_norm: float,
    y_norm: float,
) -> Optional[str]:
    entries = DRAWIO_PREPARED_TARGETS.get(str(filename or "").strip())
    if not entries:
        return None

    best: Optional[Tuple[str, float]] = None
    for _label, cell_id, px, py in entries:
        distance = ((px - x_norm) ** 2) + ((py - y_norm) ** 2)
        if best is None or distance < best[1]:
            best = (cell_id, distance)

    if best is None:
        return None
    return best[0]


def resolve_prepared_drawio_document_path(
    available_paths: List[Path],
    window_titles: List[str],
) -> Optional[Path]:
    available_by_name = {
        path.name: path
        for path in available_paths
        if path.is_file() and path.name in DRAWIO_PREPARED_TARGETS
    }
    if not available_by_name:
        return None

    for title in window_titles:
        filename = extract_drawio_filename_from_window_title(title)
        if filename and filename in available_by_name:
            return available_by_name[filename]

    if len(available_by_name) == 1:
        return next(iter(available_by_name.values()))

    return max(available_by_name.values(), key=lambda path: path.stat().st_mtime)
