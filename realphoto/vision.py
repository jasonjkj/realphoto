#!/usr/bin/env python3
"""vision.py — 验货适配层：只传「图 + 问题」，不碰 API / key。

验货入口有两种给法，二选一：
  1. 注入 `see_image(path, prompt) -> str` callable（推荐，进程内直接调用）
  2. 设 `REALPHOTO_VISION_CMD` 指向外部脚本，按
     `<python> <脚本> <图片路径> --prompt <提示>` 调用，从输出里抠 JSON

两者都没有时，验货按 **fail-closed** 处理（判不通过，不放过可疑图）。
"""
import os
import subprocess
import sys

from . import paths


def default_see_image(path: str, prompt: str, timeout: int = 90) -> str:
    """subprocess 调外部验货入口，返回 stdout + stderr 合并文本（调用方从中抠 JSON）。

    未配置入口 / 入口不存在 / rc!=0 → 抛异常（fail-closed）。
    """
    cmd = paths.vision_cmd()
    if not cmd:
        raise RuntimeError(
            "未配置验货入口：设 REALPHOTO_VISION_CMD 指向一个视觉脚本，"
            "或在调用时注入 see_image callable"
        )
    if not os.path.exists(cmd):
        raise RuntimeError("验货入口不存在: %s" % cmd)
    r = subprocess.run([sys.executable, cmd, path, "--prompt", prompt],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("验货入口失败 rc=%d: %s"
                           % (r.returncode, (r.stderr or "")[:200]))
    return (r.stdout or "") + (r.stderr or "")
