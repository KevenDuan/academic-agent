"""静态资源统一入口。

所有图标、按钮图片、logo 等资源都放在本目录下（或子目录中），
统一通过 resource_path() 解析绝对路径，避免相对路径依赖工作目录的问题。
"""

from __future__ import annotations

from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parent


def resource_path(*parts: str) -> str:
    """返回 resources 目录下的资源绝对路径字符串。

    供 QIcon / QPixmap 等 Qt 接口使用，例如：
        resource_path("logo.png")
        resource_path("icons", "open.svg")
    """
    return str(RESOURCE_ROOT.joinpath(*parts))
