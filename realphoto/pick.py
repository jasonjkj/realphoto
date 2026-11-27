#!/usr/bin/env python3
"""pick.py — 素材库直发：从本地相簿随机取图。

直接随机取，不生成、不验货。
素材库: <REALPHOTO_ALBUM_DIR>/{photo,video}/（缺省 $REALPHOTO_HOME/album/）。
"""
import os
import random

from . import paths

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


def pick(d, exts, n=1):
    """随机取 n 个（不重复）；素材不足则全给。返回文件路径列表。"""
    if not os.path.isdir(d):
        return []
    cands = sorted(f for f in os.listdir(d)
                   if os.path.isfile(os.path.join(d, f))
                   and os.path.splitext(f)[1].lower() in exts)
    if not cands:
        return []
    return [os.path.join(d, f) for f in random.sample(cands, min(n, len(cands)))]


def send_asset(video: bool = False, n: int = 1,
               album: str | None = None) -> list[str]:
    """素材库直发核心：返回选中文件列表（空 = 无素材）。打印由 BFF 层做。

    album 缺省 = paths.album_dir()（realphoto 相簿根，photo/ video/ 子目录）。
    """
    base = album or paths.album_dir()
    d = os.path.join(base, "video" if video else "photo")
    exts = VIDEO_EXTS if video else IMAGE_EXTS
    n = max(1, min(9, n))
    return pick(d, exts, n)


def parse_n(argv) -> int:
    """-n N / --count N / --count=N；缺失或非法 → 1。上限 9（防刷屏）。"""
    n = 1
    argv = list(argv or [])
    for i, a in enumerate(argv):
        raw = None
        if a in ("-n", "--count") and i + 1 < len(argv):
            raw = argv[i + 1]
        elif a.startswith("--count="):
            raw = a.split("=", 1)[1]
        if raw is not None:
            try:
                n = int(raw)
            except ValueError:
                continue
    return max(1, min(9, n))
