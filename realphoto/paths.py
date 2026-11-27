"""paths.py — 运行态路径解析（env 可覆盖，缺省落在用户数据目录）。

env：
  REALPHOTO_HOME        运行态缓存根（模型抓取 / 池 / 索引都在其下；缺省 ~/.realphoto）
  REALPHOTO_ALBUM_DIR   本地素材库（photo/ video/ 子目录；缺省 $REALPHOTO_HOME/album）
  REALPHOTO_VISION_CMD  外部验货入口脚本（可选；不设则验货 fail-closed）

本包不绑定任何外部目录结构：所有缺省都在用户自己的数据目录下，
换机器、换目录、拷到别的路径都能跑。
"""
import os

_DEFAULT_HOME = os.path.join(os.path.expanduser("~"), ".realphoto")


def home() -> str:
    """运行态缓存根（model-grab / model-pool / last.json 都在其下）。"""
    return os.environ.get("REALPHOTO_HOME") or _DEFAULT_HOME


def grab_dir() -> str:
    return os.path.join(home(), "model-grab")


def pool_dir() -> str:
    return os.path.join(home(), "model-pool")


def album_dir() -> str:
    """本地素材库根：photo/ video/ 子目录在其下。"""
    return os.environ.get("REALPHOTO_ALBUM_DIR") or os.path.join(home(), "album")


def vision_cmd() -> str | None:
    """外部验货入口脚本路径；未配置返回 None（验货按 fail-closed 处理）。

    这个包不绑带任何具体的视觉能力实现：要么由使用方提供脚本（`REALPHOTO_VISION_CMD`），
    要么在调用时注入 `see_image` callable。两者都没有时，验货一律判不通过。
    """
    return os.environ.get("REALPHOTO_VISION_CMD") or None
