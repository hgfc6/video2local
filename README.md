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

## 手工冒烟验证

1. 启动 `python -m video2local.main`
2. 点击“启动 Chrome”
3. 在专用 Chrome 中手动登录抖音
4. 打开收藏页，验证页面能被识别
5. 打开作者作品页，验证页面能被识别
6. 启动一次同步，确认同一视频第二次同步会被跳过
