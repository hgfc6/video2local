from dataclasses import dataclass
from pathlib import Path
import subprocess

from video2local.domain import VideoMetadata


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    download_dir: Path
    filename_stem: str
    cookies_from_browser: str | None


class YtDlpService:
    def __init__(self, binary_name: str = "yt-dlp") -> None:
        self.binary_name = binary_name

    def build_request(
        self,
        metadata: VideoMetadata,
        download_dir: Path,
        cookies_from_browser: str | None,
    ) -> DownloadRequest:
        title = metadata.title or metadata.video_id
        return DownloadRequest(
            url=metadata.download_url,
            download_dir=download_dir,
            filename_stem=f"{title} [{metadata.video_id}]",
            cookies_from_browser=cookies_from_browser,
        )

    def build_command(self, request: DownloadRequest) -> list[str]:
        escaped_stem = request.filename_stem.replace("%", "%%")
        output_template = str(request.download_dir / f"{escaped_stem}.%(ext)s")
        command = [
            self.binary_name,
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
        if request.cookies_from_browser:
            command.extend(["--cookies-from-browser", request.cookies_from_browser])
        command.append(request.url)
        return command

    def infer_extension(self, output_path: str) -> str:
        return Path(output_path).suffix.lstrip(".")

    def download(self, metadata: VideoMetadata, target_dir: Path) -> tuple[str, str]:
        request = self.build_request(
            metadata=metadata,
            download_dir=target_dir,
            cookies_from_browser="chrome",
        )
        command = self.build_command(request)
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        output_path = completed.stdout.strip().splitlines()[-1]
        return self.infer_extension(output_path), output_path
