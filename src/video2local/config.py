from dataclasses import dataclass
from pathlib import Path

DEFAULT_PLATFORM_NAME = "douyin"
DEFAULT_SOURCE_TYPES = ("favorites", "author_videos")


@dataclass(frozen=True)
class AppPaths:
    root: Path
    data_dir: Path
    chrome_profile_dir: Path
    downloads_dir: Path
    database_path: Path

    @classmethod
    def from_root(cls, root: Path) -> "AppPaths":
        data_dir = root / ".video2local"
        return cls(
            root=root,
            data_dir=data_dir,
            chrome_profile_dir=data_dir / "chrome-profile",
            downloads_dir=root / "downloads",
            database_path=data_dir / "video2local.db",
        )


@dataclass(frozen=True)
class AppSettings:
    platform_name: str
    supported_source_types: tuple[str, ...]
    paths: AppPaths

    @classmethod
    def for_root(
        cls,
        root: Path,
        *,
        platform_name: str,
        supported_source_types: tuple[str, ...],
    ) -> "AppSettings":
        return cls(
            platform_name=platform_name,
            supported_source_types=supported_source_types,
            paths=AppPaths.from_root(root),
        )

    @classmethod
    def default_for_root(cls, root: Path) -> "AppSettings":
        return cls.for_root(
            root,
            platform_name=DEFAULT_PLATFORM_NAME,
            supported_source_types=DEFAULT_SOURCE_TYPES,
        )
