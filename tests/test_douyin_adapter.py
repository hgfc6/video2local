from video2local.adapters.douyin import DouyinAdapter
from video2local.domain import SourceType


def test_detect_source_returns_favorites_for_like_collection_url() -> None:
    adapter = DouyinAdapter()

    source = adapter.detect_source("https://www.douyin.com/user/self?showTab=favorite_collection")

    assert source is not None
    assert source.source_type == SourceType.FAVORITES


def test_detect_source_returns_author_videos_for_user_post_url() -> None:
    adapter = DouyinAdapter()

    source = adapter.detect_source("https://www.douyin.com/user/MS4wLjABAAAA?showTab=post")

    assert source is not None
    assert source.source_type == SourceType.AUTHOR_VIDEOS


def test_parse_candidate_normalizes_missing_title_to_video_id() -> None:
    adapter = DouyinAdapter()
    metadata = adapter.parse_candidate(
        raw_item={
            "video_id": "735001",
            "title": "",
            "author_name": "张三",
            "page_url": "https://www.douyin.com/video/735001",
        },
        source_type=SourceType.AUTHOR_VIDEOS,
    )

    assert metadata.video_id == "735001"
    assert metadata.title == "735001"
    assert metadata.author_name == "张三"
