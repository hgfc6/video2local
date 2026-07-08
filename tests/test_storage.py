import sqlite3
from pathlib import Path

import pytest

from video2local.domain import SourceType, VideoMetadata
from video2local.storage import VideoRepository


def test_repository_initialize_enforces_runtime_constraints(tmp_path: Path) -> None:
    database_path = tmp_path / "video2local.db"
    repo = VideoRepository(database_path)

    repo.initialize()

    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            insert into videos (
                platform,
                video_id,
                source_type,
                author_name,
                title,
                page_url,
                download_url,
                local_path,
                file_ext,
                download_status
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "douyin",
                "unique-1",
                "favorites",
                "张三",
                "晚霞散步",
                "https://www.douyin.com/video/unique-1",
                "https://cdn.example.com/unique-1",
                "downloads/douyin/张三/晚霞散步 [unique-1].mp4",
                "mp4",
                "downloaded",
            ),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                insert into videos (
                    platform,
                    video_id,
                    source_type,
                    author_name,
                    title,
                    page_url,
                    download_url,
                    local_path,
                    file_ext,
                    download_status
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "douyin",
                    "unique-1",
                    "favorites",
                    "张三",
                    "重复",
                    "https://www.douyin.com/video/unique-1-duplicate",
                    "https://cdn.example.com/unique-1-duplicate",
                    "downloads/douyin/张三/重复 [unique-1].mp4",
                    "mp4",
                    "downloaded",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                insert into videos (
                    platform,
                    video_id,
                    source_type,
                    author_name,
                    title,
                    page_url,
                    download_url,
                    local_path,
                    file_ext,
                    download_status
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "douyin",
                    "bad-source",
                    "bad_source",
                    "张三",
                    "无效来源",
                    "https://www.douyin.com/video/bad-source",
                    "https://cdn.example.com/bad-source",
                    "downloads/douyin/张三/无效来源 [bad-source].mp4",
                    "mp4",
                    "downloaded",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                insert into videos (
                    platform,
                    video_id,
                    source_type,
                    author_name,
                    title,
                    page_url,
                    download_url,
                    local_path,
                    file_ext,
                    download_status
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "douyin",
                    "bad-status",
                    "favorites",
                    "张三",
                    "无效状态",
                    "https://www.douyin.com/video/bad-status",
                    "https://cdn.example.com/bad-status",
                    "downloads/douyin/张三/无效状态 [bad-status].mp4",
                    "mp4",
                    "invalid",
                ),
            )


def test_repository_persists_downloaded_video_and_returns_it(tmp_path: Path) -> None:
    repo = VideoRepository(tmp_path / "video2local.db")
    repo.initialize()
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="735001",
        title="晚霞散步",
        author_name="张三",
        page_url="https://www.douyin.com/video/735001",
        download_url="https://cdn.example.com/735001",
    )

    repo.upsert_downloaded_video(
        metadata=metadata,
        local_path="downloads/douyin/张三/晚霞散步 [735001].mp4",
        file_ext="mp4",
    )

    row = repo.get_video("douyin", "735001")

    assert row is not None
    assert row["platform"] == "douyin"
    assert row["video_id"] == "735001"
    assert row["source_type"] == "favorites"
    assert row["author_name"] == "张三"
    assert row["title"] == "晚霞散步"
    assert row["page_url"] == "https://www.douyin.com/video/735001"
    assert row["download_url"] == "https://cdn.example.com/735001"
    assert row["local_path"] == "downloads/douyin/张三/晚霞散步 [735001].mp4"
    assert row["file_ext"] == "mp4"
    assert row["download_status"] == "downloaded"


def test_repository_detects_existing_video_by_platform_and_video_id(tmp_path: Path) -> None:
    repo = VideoRepository(tmp_path / "video2local.db")
    repo.initialize()
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.AUTHOR_VIDEOS,
        video_id="735999",
        title="山路日常",
        author_name="李四",
        page_url="https://www.douyin.com/video/735999",
        download_url="https://cdn.example.com/735999",
    )

    repo.upsert_downloaded_video(
        metadata=metadata,
        local_path="downloads/douyin/李四/山路日常 [735999].mp4",
        file_ext="mp4",
    )

    assert repo.has_downloaded_video("douyin", "735999") is True
    assert repo.has_downloaded_video("douyin", "missing") is False


def test_repository_upsert_updates_existing_video_in_place(tmp_path: Path) -> None:
    repo = VideoRepository(tmp_path / "video2local.db")
    repo.initialize()
    database_path = tmp_path / "video2local.db"
    original = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="736888",
        title="第一次标题",
        author_name="王五",
        page_url="https://www.douyin.com/video/736888",
        download_url="https://cdn.example.com/736888-v1",
    )
    updated = VideoMetadata(
        platform="douyin",
        source_type=SourceType.AUTHOR_VIDEOS,
        video_id="736888",
        title="第二次标题",
        author_name="王五新",
        page_url="https://www.douyin.com/video/736888?from=author",
        download_url="https://cdn.example.com/736888-v2",
    )

    repo.upsert_downloaded_video(
        metadata=original,
        local_path="downloads/douyin/王五/第一次标题 [736888].mp4",
        file_ext="mp4",
    )

    with sqlite3.connect(database_path) as conn:
        conn.execute(
            "update videos set updated_at = ? where platform = ? and video_id = ?",
            ("2000-01-01 00:00:00", "douyin", "736888"),
        )

    repo.upsert_downloaded_video(
        metadata=updated,
        local_path="downloads/douyin/王五新/第二次标题 [736888].mkv",
        file_ext="mkv",
    )

    row = repo.get_video("douyin", "736888")

    assert row is not None
    assert row["source_type"] == "author_videos"
    assert row["author_name"] == "王五新"
    assert row["title"] == "第二次标题"
    assert row["page_url"] == "https://www.douyin.com/video/736888?from=author"
    assert row["download_url"] == "https://cdn.example.com/736888-v2"
    assert row["local_path"] == "downloads/douyin/王五新/第二次标题 [736888].mkv"
    assert row["file_ext"] == "mkv"
    assert row["download_status"] == "downloaded"
    assert row["updated_at"] != "2000-01-01 00:00:00"

    with sqlite3.connect(database_path) as conn:
        count = conn.execute("select count(*) from videos where platform = ? and video_id = ?", ("douyin", "736888")).fetchone()

    assert count is not None
    assert count[0] == 1
