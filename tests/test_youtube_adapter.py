from video2local.adapters.youtube import YouTubeAdapter


def test_extract_share_url_reads_youtube_short_link_from_share_text() -> None:
    adapter = YouTubeAdapter()

    url = adapter.extract_share_url("分享视频 https://youtu.be/abcDEF12345?t=12 快来看看")

    assert url == "https://youtu.be/abcDEF12345?t=12"


def test_parse_video_info_builds_best_video_and_audio_selector() -> None:
    adapter = YouTubeAdapter()
    payload = {
        "id": "abcDEF12345",
        "title": "YouTube 测试视频",
        "uploader": "测试频道",
        "duration": 61.2,
        "webpage_url": "https://www.youtube.com/watch?v=abcDEF12345",
        "formats": [
            {"format_id": "248", "height": 1080, "width": 1920, "fps": 60, "vcodec": "vp9", "acodec": "none", "tbr": 4500, "filesize": 30_000_000},
            {"format_id": "136", "height": 720, "width": 1280, "fps": 30, "vcodec": "avc1", "acodec": "none", "tbr": 1800, "filesize": 15_000_000},
            {"format_id": "251", "vcodec": "none", "acodec": "opus", "abr": 160, "filesize": 1_000_000},
        ],
    }

    metadata, variants = adapter.parse_video_info(payload, source_url="https://youtu.be/abcDEF12345")

    assert metadata.platform == "youtube"
    assert metadata.author_name == "测试频道"
    assert metadata.duration_seconds == 61
    assert [item.quality_label for item in variants] == ["1080p60", "720p30"]
    assert variants[0].codec_label == "VP9"
    assert variants[0].format_selector == "248+251"
    assert variants[0].is_recommended is True
