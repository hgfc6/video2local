from pathlib import Path

from video2local.archive import ArchiveManager
from video2local.domain import SourceType, VideoMetadata


def test_safe_filename_replaces_windows_invalid_characters(tmp_path: Path) -> None:
    manager = ArchiveManager(download_root=tmp_path)

    assert manager.safe_name('A<>:"/\\|?*B .') == "A B"


def test_safe_name_rewrites_windows_reserved_names(tmp_path: Path) -> None:
    manager = ArchiveManager(download_root=tmp_path)

    assert manager.safe_name("CON") == "CON_"
    assert manager.safe_name("aux") == "aux_"
    assert manager.safe_name("Lpt9") == "Lpt9_"


def test_build_target_path_sanitizes_path_components(tmp_path: Path) -> None:
    manager = ArchiveManager(download_root=tmp_path)
    metadata = VideoMetadata(
        platform="dou/yin",
        source_type=SourceType.FAVORITES,
        video_id="735001",
        title='晚霞<>:"#散步',
        author_name="张/三",
        page_url="https://www.douyin.com/video/735001",
        download_url="https://www.douyin.com/video/735001",
    )

    expected = tmp_path / "dou yin" / "张 三" / "晚霞 ，散步-735001.mp4"

    assert manager.build_target_path(metadata, "mp4") == expected


def test_build_target_path_uses_sanitized_video_id_when_title_missing(tmp_path: Path) -> None:
    manager = ArchiveManager(download_root=tmp_path)
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.AUTHOR_VIDEOS,
        video_id='vid<>:"/\\|?*01',
        title=None,
        author_name="AUX",
        page_url="https://www.douyin.com/video/vid01",
        download_url="https://www.douyin.com/video/vid01",
    )

    expected = tmp_path / "douyin" / "AUX_" / "vid 01-vid 01.mp4"

    assert manager.build_target_path(metadata, ".MP4") == expected


def test_build_target_path_normalizes_multi_part_extension(tmp_path: Path) -> None:
    manager = ArchiveManager(download_root=tmp_path)
    metadata = VideoMetadata(
        platform="youtube",
        source_type=SourceType.AUTHOR_VIDEOS,
        video_id="abc123",
        title="demo",
        author_name="creator",
        page_url="https://www.youtube.com/watch?v=abc123",
        download_url="https://www.youtube.com/watch?v=abc123",
    )

    expected = tmp_path / "youtube" / "creator" / "demo-abc123.tar.gz"

    assert manager.build_target_path(metadata, "tar.gz") == expected


def test_build_target_path_can_flatten_into_selected_root(tmp_path: Path) -> None:
    manager = ArchiveManager(download_root=tmp_path, flatten_into_root=True)
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="abc123",
        title="演示标题",
        author_name="作者A",
        page_url="https://www.douyin.com/video/abc123",
        download_url="https://www.douyin.com/video/abc123",
    )

    expected = tmp_path / "演示标题-abc123.mp4"

    assert manager.build_target_path(metadata, "mp4") == expected
