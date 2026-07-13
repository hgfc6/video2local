# Video2Local

Video2Local 是一个 Python 桌面工具，用于将网页视频归档到本地。它使用独立 Chrome 保存登录态，按顺序解析和下载视频，避免高并发触发平台或第三方服务限流。

## 当前能力

- 平台工作台：顶部切换 `抖音` 或 `Bilibili`；切换时清空结果，拒绝执行不属于当前平台的页面和链接。
- 抖音：收藏页、作者作品页批量同步；单链接可选择 `native` 和 `Kukutool` 解析。
- Bilibili：收藏夹、`space.bilibili.com/<UP主>/video` 投稿页批量同步；标准视频链接、`b23.tv` 短链和分享文案单链接解析。
- 批量任务：支持前 N 个、同步前预览、首条样本和停止请求；按“解析一个、下载一个”串行执行。
- 下载归档：选择输出目录；可按 `平台/作者` 分目录或平铺输出；文件名为 `标题-视频ID[-清晰度].扩展名`。
- 清晰度：单链接表展示清晰度、来源、编码、码率和大小；Bilibili 优先下载最佳视频流与音频流并合并为 MP4。

## 使用流程

### 1. 选择平台工作台

- 抖音工作台显示 `native` 和 `Kukutool` 解析来源选择。
- Bilibili 工作台固定使用原生解析及专用 Chrome 登录 cookies，不会调用 Kukutool。

### 2. 单链接解析

1. 选择对应平台工作台。
2. 粘贴当前平台的分享文案、短链或标准视频链接。
3. 点击“解析分享链接”，在结果表中勾选版本。
4. 点击“下载所选版本”。

抖音启用 Kukutool 时，先点击“启动 Chrome”，并在专用 Chrome 打开 `https://dy.kukutool.com`。若出现广告、验证或弹窗，需要手动处理，程序会等待网页恢复。

Bilibili 如需账号权限范围内的 1440P、4K 等版本，先在专用 Chrome 登录 Bilibili 后再解析；未登录时按匿名权限解析。

### 3. 批量同步

1. 选择平台工作台并点击“启动 Chrome”。
2. 在专用 Chrome 登录对应平台。
3. 打开支持的内容页：
   - 抖音：收藏页或作者作品页。
   - Bilibili：收藏夹或 UP 主投稿页。
4. 可设置“前 N 个视频”，再点击“检查当前页面”。
5. 点击“同步前预览”核对作者、标题、可用版本和默认下载版本。
6. 点击“开始同步”。

## 输出规则

默认输出：

```text
downloads/<platform>/<author>/<title>-<video-id>[-<quality>].mp4
```

启用平铺输出后：

```text
<选择的目录>/<title>-<video-id>[-<quality>].mp4
```

- `#` 替换为中文逗号 `，`，开头多余逗号会去除。
- 非法 Windows 文件名字符会自动清理。
- 首条样本下载到 `<输出目录>/_smoke_test/`。

## 依赖与启动

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .[dev]
python -m playwright install chromium
.\.venv\Scripts\python.exe -m video2local.main
```

Bilibili 的分离音视频合并需要安装 `ffmpeg`。程序会检查当前进程、当前用户和系统级 PATH，并将找到的 ffmpeg 目录显式传给 `yt-dlp`。

运行测试：

```powershell
python -m pytest -v
```

## 边界

- 不接管日常 Chrome，也不自动登录、绕过验证码、广告、会员、地区或版权限制。
- Bilibili 当前不支持番剧、合集和多 P 选择。
- 可下载版本以当前账号和平台实际返回的格式为准，不保证等同于理论原画。
