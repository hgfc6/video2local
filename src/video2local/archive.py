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
    flatten_into_root: bool = False

    def normalize_title_text(self, raw: str) -> str:
        normalized = raw.replace("#", "，").lstrip("，").strip()
        return normalized

    def safe_name(self, raw: str) -> str:
        cleaned = INVALID_CHARS.sub(" ", self.normalize_title_text(raw)).strip().rstrip(".")
        collapsed = WHITESPACE.sub(" ", cleaned).strip()
        candidate = collapsed or "untitled"
        if candidate.upper() in WINDOWS_RESERVED_NAMES:
            return f"{candidate}_"
        return candidate

    def build_filename_stem(
        self,
        *,
        video_id: str,
        title: str | None,
        suffix: str | None = None,
    ) -> str:
        safe_video_id = self.safe_name(video_id)
        safe_title = self.safe_name(title or safe_video_id)
        parts = [safe_title, safe_video_id]
        if suffix:
            parts.append(self.safe_name(suffix))
        return "-".join(parts)

    def normalize_extension(self, raw: str) -> str:
        normalized = self.safe_name(raw.strip().lstrip(".")).replace(" ", ".").lower()
        return normalized or "bin"

    def build_author_directory_name(self, metadata: VideoMetadata) -> str:
        """Use a stable Douyin handle alongside the display name when available."""
        author = self.safe_name(metadata.author_name)
        if metadata.platform == "douyin" and metadata.author_handle:
            return f"{author}+{self.safe_name(metadata.author_handle)}"
        return author

    def build_target_path(self, metadata: VideoMetadata, file_ext: str) -> Path:
        extension = self.normalize_extension(file_ext)
        filename = f"{self.build_filename_stem(video_id=metadata.video_id, title=metadata.title)}.{extension}"
        if self.flatten_into_root:
            return self.download_root / filename
        platform = self.safe_name(metadata.platform)
        author = self.build_author_directory_name(metadata)
        return self.download_root / platform / author / filename
