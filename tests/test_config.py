from pathlib import Path

from video2local.config import AppPaths, AppSettings


def test_app_paths_from_root_uses_workspace_relative_directories(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path)

    assert paths.root == tmp_path
    assert paths.data_dir == tmp_path / ".video2local"
    assert paths.chrome_profile_dir == tmp_path / ".video2local" / "chrome-profile"
    assert paths.downloads_dir == tmp_path / "downloads"
    assert paths.database_path == tmp_path / ".video2local" / "video2local.db"


def test_default_settings_enable_douyin_favorites_and_author_pages(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)

    assert settings.platform_name == "douyin"
    assert settings.supported_source_types == ("favorites", "author_videos")
    assert settings.paths == AppPaths.from_root(tmp_path)
