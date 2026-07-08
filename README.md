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
