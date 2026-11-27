#!/usr/bin/env python3
"""bff.py — 真人素材域 BFF 统一入口（MEDIA: 产出协议）。

对外契约（调用方只跟本层打交道，不碰内部实现）：
  grab_model(kw=None)        抓模特：现场抓一张合格模特图 → MEDIA:<路径>
  send_asset(video, n)       素材直发：本地相簿随机取（不重复）→ 每行 MEDIA:<路径>
  pool_status()              缓存查询：grab/pool 目录状态 JSON

console：`realphoto-bff <子命令>`（供调用方以子进程方式接入）：
  realphoto-bff grab-model [--kw "<英文关键词>"]
  realphoto-bff send-asset [--video] [-n N]
  realphoto-bff pool-status
  realphoto-bff inspect <图片路径>     # 只验货单张，不抓
  realphoto-bff fill N                 # 抓 N 张入池备用（旧池化模式）
  realphoto-bff consume                # 从池取一张直发（旧池化模式）

返回码: 0=成功  1=失败/无素材
"""
import argparse
import json
import os
import sys

from . import __version__, card as card_mod, config as config_mod, grab, paths, pick


def grab_model(n: int | None = None, profile: str | None = None,
               kw: str | None = None, *, see_image="__default__") -> int:
    """抓模特主链路（可配置/流式）：

    - n: 本次张数（缺省读 config.grab.n，默认 5）
    - profile: 画像名（config.json 的 profiles key，或 intent_words 口语词；缺省回退 card 默认）
    - kw: 兼容旧用法——临时覆盖搜索关键词（给定则走单张旧路径）
    - stream=true（config）：每抓到一张立即打一行 MEDIA + PROGRESS（便于逐条推送与报进度）
    - 无合格 → NO_GOOD
    """
    card = card_mod.load_card()
    cfg = config_mod.load_config()
    grab_cfg = cfg.get("grab") or {}
    count = n or int(grab_cfg.get("n") or 5)
    stream = bool(grab_cfg.get("stream", True))
    prof = config_mod.resolve_profile(profile, cfg)
    if kw is not None:
        hit = grab.grab_one(card, kw=kw, see_image=see_image)
        if hit:
            print("MEDIA:%s" % hit[0])
            print("来源: %s" % hit[1])
            return 0
        print("NO_GOOD 没有抓到合格模特图", file=sys.stderr)
        return 1
    hits = grab.grab_many(card, n=count, profile_cfg=prof, see_image=see_image)
    if stream:
        i = 0
        for path, src in hits:
            i += 1
            print("MEDIA:%s" % path)
            print("PROGRESS: 已出 %d/%d" % (i, count))
        if i == 0:
            print("NO_GOOD 没有抓到合格模特图", file=sys.stderr)
            return 1
        return 0
    all_hits = list(hits)
    if not all_hits:
        print("NO_GOOD 没有抓到合格模特图", file=sys.stderr)
        return 1
    for path, _src in all_hits:
        print("MEDIA:%s" % path)
    return 0


def send_asset(video: bool = False, n: int = 1) -> int:
    """素材库直发：每张一行 MEDIA:<路径>；无素材 → NO_IMAGE。"""
    files = pick.send_asset(video=video, n=n)
    if not files:
        print("NO_IMAGE")
        return 1
    for f in files:
        print("MEDIA:%s" % f)
    print("来源: realphoto 真人相簿(%s) x%d" % ("video" if video else "photo", len(files)))
    return 0


def pool_status() -> int:
    """缓存查询：grab/pool/album 目录与数量（JSON 一行）。"""
    gd, pd = paths.grab_dir(), paths.pool_dir()
    ad = paths.album_dir()

    def _count(d, exts):
        if not os.path.isdir(d):
            return 0
        return len([f for f in os.listdir(d) if f.lower().endswith(exts)])

    print(json.dumps({
        "home": paths.home(),
        "grab_dir": gd, "grab_count": _count(gd, (".jpg", ".jpeg", ".png", ".webp")),
        "pool_dir": pd, "pool_count": _count(pd, (".jpg", ".jpeg", ".png", ".webp")),
        "album_dir": ad, "album_photo_count": _count(os.path.join(ad, "photo"),
                                                     (".jpg", ".jpeg", ".png", ".webp")),
        "album_video_count": _count(os.path.join(ad, "video"), (".mp4", ".mov", ".webm")),
        "vision_cmd": paths.vision_cmd(),
        "vision_cmd_exists": bool(paths.vision_cmd()) and os.path.exists(paths.vision_cmd()),
        "card_path": card_mod.card_path(),
        "version": __version__,
    }, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="realphoto-bff",
                                 description="真人素材 BFF（素材直发 / 抓模特 / 池状态）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("grab-model", help="抓模特（流式）：--n 张数 --profile 人群/口语")
    p.add_argument("--kw", default=None, help="临时覆盖卡内 search_keywords（走单张旧路径）")
    p.add_argument("--n", type=int, default=None, help="本次张数（缺省读 config.grab.n=5）")
    p.add_argument("--profile", default=None, help="画像名：config.json 里 profiles 的 key（或 intent_words 里的口语词）；未配置则忽略")
    p = sub.add_parser("send-asset", help="素材库直发")
    p.add_argument("--video", action="store_true")
    p.add_argument("-n", "--count", type=int, default=1)
    sub.add_parser("pool-status", help="缓存查询")
    p = sub.add_parser("inspect", help="只验货单张，不抓")
    p.add_argument("image")
    p = sub.add_parser("fill", help="抓 N 张合格图入池（旧池化模式）")
    p.add_argument("n", type=int)
    sub.add_parser("consume", help="从池取一张直发（旧池化模式）")
    a = ap.parse_args(argv)

    if a.cmd == "grab-model":
        return grab_model(n=a.n, profile=a.profile, kw=a.kw)
    if a.cmd == "send-asset":
        return send_asset(video=a.video, n=a.count)
    if a.cmd == "pool-status":
        return pool_status()
    if a.cmd == "inspect":
        if not os.path.exists(a.image):
            print("文件不存在: %s" % a.image, file=sys.stderr)
            return 1
        card = card_mod.load_card()
        from . import vision as vision_adapter
        try:
            print(vision_adapter.default_see_image(a.image, card["verify_prompt"]))
            return 0
        except Exception as e:
            print("ERROR 验货失败: %s" % e, file=sys.stderr)
            return 1
    if a.cmd == "fill":
        card = card_mod.load_card()
        got = grab.fill(a.n, card, card["verify_prompt"])
        print("补池完成: 入 %d 张, 池内共 %d 张" % (got, grab.pool_size()))
        return 0 if got else 1
    if a.cmd == "consume":
        card = card_mod.load_card()
        dst = grab.consume(card, card["verify_prompt"])
        if dst:
            print("MEDIA:%s" % dst)
            print("剩余池内: %d 张" % grab.pool_size())
            return 0
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
