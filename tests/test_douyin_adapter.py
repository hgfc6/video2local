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


def test_detect_source_returns_author_videos_for_plain_user_url() -> None:
    adapter = DouyinAdapter()

    source = adapter.detect_source("https://www.douyin.com/user/self")

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


def test_parse_aweme_detail_uses_highest_bitrate_media_url() -> None:
    adapter = DouyinAdapter()
    payload = {
        "aweme_detail": {
            "aweme_id": "7062344670323526953",
            "desc": "#情绪 #成长",
            "duration": 6826,
            "author": {
                "nickname": "h6ii",
            },
            "video": {
                "bit_rate": [
                    {
                        "bit_rate": 900000,
                        "play_addr": {
                            "url_list": ["https://cdn.example.com/low.mp4"],
                        },
                    },
                    {
                        "bit_rate": 1347641,
                        "play_addr": {
                            "url_list": ["https://cdn.example.com/high.mp4"],
                        },
                    },
                ],
                "play_addr": {
                    "url_list": ["https://cdn.example.com/fallback.mp4"],
                },
            },
        }
    }

    metadata = adapter.parse_aweme_detail(
        payload,
        source_type=SourceType.AUTHOR_VIDEOS,
        page_url="https://www.douyin.com/video/7062344670323526953",
    )

    assert metadata.video_id == "7062344670323526953"
    assert metadata.title == "#情绪 #成长"
    assert metadata.author_name == "h6ii"
    assert metadata.duration_seconds == 6
    assert metadata.download_url == "https://cdn.example.com/high.mp4"


def test_collect_candidate_urls_returns_unique_absolute_video_urls() -> None:
    adapter = DouyinAdapter()
    html = """
    <a href="/video/735001">one</a>
    <a href="https://www.douyin.com/video/735002">two</a>
    <a href="/video/735001">duplicate</a>
    """

    urls = adapter.collect_candidate_urls(html)

    assert urls == [
        "https://www.douyin.com/video/735001",
        "https://www.douyin.com/video/735002",
    ]
