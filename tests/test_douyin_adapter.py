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


def test_collect_candidate_urls_returns_unique_absolute_video_and_note_urls() -> None:
    adapter = DouyinAdapter()
    html = """
    <a href="/video/735001">one</a>
    <a href="https://www.douyin.com/video/735002">two</a>
    <a href="/note/735003">image post</a>
    <a href="/video/735001">duplicate</a>
    """

    urls = adapter.collect_candidate_urls(html)

    assert urls == [
        "https://www.douyin.com/video/735001",
        "https://www.douyin.com/video/735002",
        "https://www.douyin.com/note/735003",
    ]


def test_extract_share_url_pulls_short_link_from_raw_douyin_share_text() -> None:
    adapter = DouyinAdapter()
    share_text = "9.76 复制打开抖音，看看【香菜严选的作品】  https://v.douyin.com/5MF6Y_tP8nk/ 08/05 X@Z.Mj :5pm wse:/"

    url = adapter.extract_share_url(share_text)

    assert url == "https://v.douyin.com/5MF6Y_tP8nk/"


def test_parse_share_variants_returns_sorted_versions_with_metadata() -> None:
    adapter = DouyinAdapter()
    payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
            "desc": "分享视频",
            "author": {"nickname": "香菜严选"},
            "duration": 8467,
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "540_3_1",
                        "bit_rate": 916480,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 969980,
                            "width": 540,
                            "height": 960,
                            "url_list": ["https://cdn.example.com/540.mp4"],
                        },
                    },
                    {
                        "gear_name": "720_1_1",
                        "bit_rate": 1971327,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 2086404,
                            "width": 720,
                            "height": 1280,
                            "url_list": ["https://cdn.example.com/720.mp4"],
                        },
                    },
                ]
            },
        }
    }

    variants = adapter.parse_share_variants(payload)

    assert [variant.variant_id for variant in variants] == ["720_1_1", "540_3_1"]
    assert variants[0].quality_label == "720p"
    assert variants[0].codec_label == "H.265"
    assert variants[0].bit_rate == 1971327
    assert variants[0].file_size == 2086404
    assert variants[0].download_url == "https://cdn.example.com/720.mp4"


def test_parse_share_variants_synthesizes_public_download_profiles_from_download_addr() -> None:
    adapter = DouyinAdapter()
    payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
            "desc": "分享视频",
            "author": {"nickname": "香菜严选"},
            "video": {
                "download_addr": {
                    "url_list": [
                        "https://api-play-hl.amemv.com/aweme/v1/play/?video_id=v2800fgi0000d8nlbjfog65qbk07m570&line=0&ratio=540p&watermark=1&media_type=4&vr_type=0&improve_bitrate=0&biz_sign=test&logo_name=aweme_search_suffix&source=PackSourceEnum_AWEME_DETAIL"
                    ]
                }
            },
        }
    }

    variants = adapter.parse_share_variants(payload)

    assert [variant.quality_label for variant in variants] == ["1080p", "720p", "540p"]
    assert variants[0].download_url.endswith("ratio=1080p&watermark=0&media_type=4&vr_type=0&improve_bitrate=0&biz_sign=test&logo_name=aweme_search_suffix&source=PackSourceEnum_AWEME_DETAIL")


def test_parse_share_variants_prefers_native_high_resolution_variants_over_public_profiles() -> None:
    adapter = DouyinAdapter()
    payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
            "desc": "分享视频",
            "author": {"nickname": "香菜严选"},
            "video": {
                "download_addr": {
                    "url_list": [
                        "https://api-play-hl.amemv.com/aweme/v1/play/?video_id=v2800fgi0000d8nlbjfog65qbk07m570&line=0&ratio=540p&watermark=1&media_type=4&vr_type=0&improve_bitrate=0&biz_sign=test&logo_name=aweme_search_suffix&source=PackSourceEnum_AWEME_DETAIL"
                    ]
                },
                "bit_rate": [
                    {
                        "gear_name": "adapt_lowest_4_1",
                        "bit_rate": 5134767,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 5409478,
                            "width": 2160,
                            "height": 3840,
                            "url_list": ["https://cdn.example.com/2160.mp4"],
                        },
                    },
                    {
                        "gear_name": "normal_1080_0",
                        "bit_rate": 3609244,
                        "is_h265": 0,
                        "play_addr": {
                            "data_size": 3819934,
                            "width": 1080,
                            "height": 1920,
                            "url_list": ["https://cdn.example.com/1080.mp4"],
                        },
                    },
                ],
            },
        }
    }

    variants = adapter.parse_share_variants(payload)

    assert variants[0].quality_label == "2160p"
    assert variants[0].download_url == "https://cdn.example.com/2160.mp4"
    assert "public_1080p" not in [variant.variant_id for variant in variants]


def test_parse_share_variants_reads_kukutool_video_fullinfo_labels_and_sizes() -> None:
    adapter = DouyinAdapter()
    payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
            "desc": "分享视频",
            "author": {"nickname": "香菜严选"},
            "video": {
                "video_fullinfo": [
                    {
                        "type": "540p",
                        "size": 2430281,
                        "url": "https://cdn.example.com/540.mp4",
                    },
                    {
                        "type": "超高清",
                        "size": 67819321,
                        "url": "https://cdn.example.com/ultra.mp4",
                    },
                ]
            },
        }
    }

    variants = adapter.parse_share_variants(payload)

    assert [variant.quality_label for variant in variants] == ["超高清", "540p"]
    assert variants[0].download_url == "https://cdn.example.com/ultra.mp4"
    assert variants[0].file_size == 67819321
    assert variants[0].is_recommended is True
