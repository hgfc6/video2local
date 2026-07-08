import re
from dataclasses import dataclass
from pathlib import Path

from video2local.domain import VideoMetadata


INVALID_CHARS = re.compile(r'[<>:"/\\|?*]+')
WHITESPACE = re.compile(r"\s+")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass
class ArchiveManager:
    download_root: Path

    def safe_name(self, raw: str) -> str:
        cleaned = INVALID_CHARS.sub(" ", raw).strip().rstrip(".")
        collapsed = WHITESPACE.sub(" ", cleaned).strip()
        candidate = collapsed or "untitled"
        if candidate.upper() in WINDOWS_RESERVED_NAMES:
            return f"{candidate}_"
        return candidate

    def normalize_extension(self, raw: str) -> str:
        normalized = self.safe_name(raw.strip().lstrip(".")).replace(" ", ".").lower()
        return normalized or "bin"

    def build_target_path(self, metadata: VideoMetadata, file_ext: str) -> Path:
        platform = self.safe_name(metadata.platform)
        author = self.safe_name(metadata.author_name)
        video_id = self.safe_name(metadata.video_id)
        title = self.safe_name(metadata.title or video_id)
        extension = self.normalize_extension(file_ext)
        filename = f"{title} [{video_id}].{extension}"
        return self.download_root / platform / author / filename
