from video2local.adapters.bilibili import BilibiliAdapter
from video2local.domain import SourceType


def test_extract_share_url_reads_b23_short_link_from_share_text() -> None:
    adapter = BilibiliAdapter()

    url = adapter.extract_share_url("【测试视频】 https://b23.tv/AbCdEfG 复制打开哔哩哔哩")

    assert url == "https://b23.tv/AbCdEfG"


def test_detect_source_recognizes_up_video_page_and_favorites_page() -> None:
    adapter = BilibiliAdapter()

    author_source = adapter.detect_source("https://space.bilibili.com/123456/video")
    favorites_source = adapter.detect_source("https://space.bilibili.com/123456/favlist?fid=987654")

    assert author_source is not None
    assert author_source.source_type == SourceType.AUTHOR_VIDEOS
    assert favorites_source is not None
    assert favorites_source.source_type == SourceType.FAVORITES


def test_collect_candidate_urls_deduplicates_standard_video_links() -> None:
    adapter = BilibiliAdapter()

    urls = adapter.collect_candidate_urls(
        '<a href="https://www.bilibili.com/video/BV1xx411c7mD?spm_id=1">one</a>'
        '<a href="https://www.bilibili.com/video/BV1xx411c7mD">duplicate</a>'
        '<a href="https://www.bilibili.com/video/BV1ab411c7mE">two</a>'
    )

    assert urls == [
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://www.bilibili.com/video/BV1ab411c7mE",
    ]


def test_collect_candidate_urls_accepts_relative_and_protocol_relative_links() -> None:
    adapter = BilibiliAdapter()

    urls = adapter.collect_candidate_urls(
        '<a href="/video/BV1xx411c7mD">one</a>'
        '<a href="//www.bilibili.com/video/BV1ab411c7mE">two</a>'
    )

    assert urls == [
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://www.bilibili.com/video/BV1ab411c7mE",
    ]


def test_collect_candidate_urls_accepts_json_escaped_video_links() -> None:
    adapter = BilibiliAdapter()

    urls = adapter.collect_candidate_urls('{"jump_url":"https:\\/\\/www.bilibili.com\\/video\\/BV1xx411c7mD"}')

    assert urls == ["https://www.bilibili.com/video/BV1xx411c7mD"]


def test_parse_video_info_builds_highest_video_and_best_audio_variants() -> None:
    adapter = BilibiliAdapter()
    payload = {
        "id": "BV1xx411c7mD",
        "title": "测试视频",
        "uploader": "测试UP",
        "duration": 61.2,
        "webpage_url": "https://www.bilibili.com/video/BV1xx411c7mD",
        "formats": [
            {"format_id": "80", "height": 1080, "width": 1920, "vcodec": "avc1.640032", "acodec": "none", "tbr": 3600, "filesize": 30_000_000},
            {"format_id": "64", "height": 720, "width": 1280, "vcodec": "hev1.1.6.L120", "acodec": "none", "tbr": 1800, "filesize": 15_000_000},
            {"format_id": "30280", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 192, "filesize": 800_000},
            {"format_id": "30216", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 64, "filesize": 2_000_000},
        ],
    }

    metadata, variants = adapter.parse_video_info(
        payload,
        source_type=SourceType.SHARE_LINK,
        source_url="https://b23.tv/AbCdEfG",
    )

    assert metadata.video_id == "BV1xx411c7mD"
    assert metadata.author_name == "测试UP"
    assert metadata.duration_seconds == 61
    assert [item.quality_label for item in variants] == ["1080p", "720p"]
    assert variants[0].codec_label == "H.264"
    assert variants[0].format_selector == "80+30280"
    assert variants[0].file_size == 30_800_000
    assert variants[0].is_recommended is True


def test_parse_video_info_uses_part_number_in_stable_id() -> None:
    adapter = BilibiliAdapter()
    payload = {
        "id": "BV1xx411c7mD",
        "playlist_index": 2,
        "title": "第二集",
        "uploader": "测试UP",
        "formats": [{"format_id": "80", "height": 1080, "vcodec": "avc1", "acodec": "mp4a", "tbr": 1000}],
    }

    metadata, variants = adapter.parse_video_info(payload, source_type=SourceType.SHARE_LINK, source_url="https://example.com")

    assert metadata.video_id == "BV1xx411c7mD-p2"
    assert variants[0].format_selector == "80"
