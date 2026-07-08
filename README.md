# Video2Local

Python 桌面工具，负责把抖音等平台的内容源页面同步到本地目录。

## 开发环境

1. `python -m venv .venv`
2. `.venv\Scripts\activate`
3. `python -m pip install -e .[dev]`
4. `python -m playwright install chromium`

## 运行测试

`python -m pytest -v`

## 启动应用

`python -m video2local.main`

## 当前界面能力

- `启动 Chrome`：打开专用 Chrome 配置目录
- `检查当前页面`：识别当前是否为受支持的收藏页或作者作品页
- `下载首个样本`：先下载当前页面首个可见视频到 `downloads/_smoke_test/`，用于验证登录态、页面识别和下载链路
- `开始同步`：后台开始抓取并下载视频
- `停止同步`：在当前视频处理完成后安全停止
- `打开下载目录`：直接打开本地归档目录
- `查看最近摘要`：显示最近一次同步任务统计

## 手工冒烟验证

1. 启动 `python -m video2local.main`
2. 点击“启动 Chrome”
3. 在专用 Chrome 中手动登录抖音
4. 打开收藏页，或打开作者作品页
5. 点击“检查当前页面”，确认界面显示已识别来源
6. 点击“下载首个样本”，确认 `downloads/_smoke_test/` 中出现一个样本文件
7. 点击“开始同步”，观察界面中的当前进度和最后处理项
8. 需要中止时点击“停止同步”，确认任务在安全边界停止
9. 同步完成后点击“查看最近摘要”，确认统计与实际一致
10. 再次启动一次同步，确认同一视频第二次同步会被跳过
