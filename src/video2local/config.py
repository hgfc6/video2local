from dataclasses import dataclass
from pathlib import Path

DEFAULT_PLATFORM_NAME = "douyin"
DEFAULT_SOURCE_TYPES = ("favorites", "author_videos")
DEFAULT_KUKUTOOL_BASE_URL = "https://dy.kukutool.com"


@dataclass(frozen=True)
class AppPaths:
    root: Path
    data_dir: Path
    chrome_profile_dir: Path
    downloads_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> "AppPaths":
        data_dir = root / ".video2local"
        return cls(
            root=root,
            data_dir=data_dir,
            chrome_profile_dir=data_dir / "chrome-profile",
            downloads_dir=root / "downloads",
        )


@dataclass(frozen=True)
class ShareResolverSettings:
    enable_kukutool_fallback: bool = False
    kukutool_base_url: str = DEFAULT_KUKUTOOL_BASE_URL
    enabled_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(dict.fromkeys(item for item in self.enabled_sources if item))
        if not normalized:
            normalized = ("native",)
        if self.enable_kukutool_fallback and not self.enabled_sources:
            normalized = ("native", "kukutool")
        object.__setattr__(self, "enabled_sources", normalized)


@dataclass(frozen=True)
class AppSettings:
    platform_name: str
    supported_source_types: tuple[str, ...]
    paths: AppPaths
    share_resolvers: ShareResolverSettings

    @classmethod
    def for_root(
        cls,
        root: Path,
        *,
        platform_name: str,
        supported_source_types: tuple[str, ...],
        share_resolvers: ShareResolverSettings | None = None,
    ) -> "AppSettings":
        return cls(
            platform_name=platform_name,
            supported_source_types=supported_source_types,
            paths=AppPaths.from_root(root),
            share_resolvers=share_resolvers or ShareResolverSettings(),
        )

    @classmethod
    def default_for_root(cls, root: Path) -> "AppSettings":
        return cls.for_root(
            root,
            platform_name=DEFAULT_PLATFORM_NAME,
            supported_source_types=DEFAULT_SOURCE_TYPES,
        )
