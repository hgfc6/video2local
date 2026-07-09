from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen

from video2local.domain import SourceType, VideoMetadata


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    download_dir: Path
    filename_stem: str
    cookies_from_browser: str | None
    cookies_file: Path | None = None


class YtDlpService:
    def __init__(self, binary_name: str | list[str] | None = None) -> None:
        self.binary_name = binary_name

    def command_prefix(self) -> list[str]:
        if self.binary_name is None:
            return [sys.executable, "-m", "yt_dlp"]
        if isinstance(self.binary_name, str):
            return [self.binary_name]
        return list(self.binary_name)

    def build_request(
        self,
        metadata: VideoMetadata,
        download_dir: Path,
        cookies_from_browser: str | None,
        cookies_file: Path | None = None,
        filename_stem: str | None = None,
    ) -> DownloadRequest:
        return DownloadRequest(
            url=metadata.download_url,
            download_dir=download_dir,
            filename_stem=filename_stem or f"{metadata.title or metadata.video_id} [{metadata.video_id}]",
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
        )

    def build_command(self, request: DownloadRequest) -> list[str]:
        escaped_stem = request.filename_stem.replace("%", "%%")
        output_template = str(request.download_dir / f"{escaped_stem}.%(ext)s")
        command = [
            *self.command_prefix(),
            "--ignore-config",
            "-f",
            "bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "--print",
            "after_move:filepath",
            "-o",
            output_template,
        ]
        if request.cookies_file is not None:
            command.extend(["--cookies", str(request.cookies_file)])
        elif request.cookies_from_browser:
            command.extend(["--cookies-from-browser", request.cookies_from_browser])
        command.append(request.url)
        return command

    def infer_extension(self, output_path: str) -> str:
        return Path(output_path).suffix.lstrip(".")

    def probe_metadata(
        self,
        *,
        url: str,
        platform: str,
        source_type: SourceType,
        cookies_from_browser: str | None,
        cookies_file: Path | None = None,
    ) -> VideoMetadata:
        command = [
            *self.command_prefix(),
            "--ignore-config",
            "--skip-download",
            "--dump-single-json",
        ]
        if cookies_file is not None:
            command.extend(["--cookies", str(cookies_file)])
        elif cookies_from_browser:
            command.extend(["--cookies-from-browser", cookies_from_browser])
        command.append(url)
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        payload = json.loads(completed.stdout)
        video_id = str(payload["id"])
        title = payload.get("title") or video_id
        author_name = payload.get("uploader") or payload.get("channel") or payload.get("creator") or "unknown"
        page_url = payload.get("webpage_url") or url
        return VideoMetadata(
            platform=platform,
            source_type=source_type,
            video_id=video_id,
            title=title,
            author_name=author_name,
            page_url=page_url,
            download_url=page_url,
        )

    def should_download_direct(self, metadata: VideoMetadata) -> bool:
        download_url = metadata.download_url
        return any(
            marker in download_url
            for marker in (
                "mime_type=video_mp4",
                ".zjcdn.com/",
                "douyinvod.com",
                "/aweme/v1/play/?video_id=",
            )
        )

    def download(
        self,
        metadata: VideoMetadata,
        target_dir: Path,
        cookies_file: Path | None = None,
        filename_stem: str | None = None,
    ) -> tuple[str, str]:
        if self.should_download_direct(metadata):
            return self._download_direct_media(metadata, target_dir, filename_stem=filename_stem)
        request = self.build_request(
            metadata=metadata,
            download_dir=target_dir,
            cookies_from_browser="chrome",
            cookies_file=cookies_file,
            filename_stem=filename_stem,
        )
        command = self.build_command(request)
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        output_path = completed.stdout.strip().splitlines()[-1]
        return self.infer_extension(output_path), output_path

    def _download_direct_media(
        self,
        metadata: VideoMetadata,
        target_dir: Path,
        *,
        filename_stem: str | None = None,
    ) -> tuple[str, str]:
        request = self.build_request(
            metadata=metadata,
            download_dir=target_dir,
            cookies_from_browser=None,
            filename_stem=filename_stem,
        )
        output_path = request.download_dir / f"{request.filename_stem}.mp4"
        http_request = Request(
            metadata.download_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/138.0.0.0 Safari/537.36"
                ),
                "Referer": metadata.page_url,
            },
        )
        with urlopen(http_request) as response:
            with output_path.open("wb") as output_file:
                while True:
                    chunk = response.read(1024 * 64)
                    if not chunk:
                        break
                    output_file.write(chunk)
        return "mp4", str(output_path)
