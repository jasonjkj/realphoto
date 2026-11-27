#!/usr/bin/env python3
"""providers.py — 模特图搜索 provider（可按 chain 编排）。

endpoint / 开关 / 关键词从 model-card.json 读；key 由调用方注入
（env_key 名在 card providers 段，值由 bff 层从配置目录 .env / 环境解析——本模块不碰 .env）。

chain：config.json 的 `chain`（优先级顺序）+ `providers`（{name: {enabled, entry, options}}）。
entry 三种形态（sources.resolve_entry）：builtin:<内置> | <module>:<func> | <路径.py>:<func>。
单源加载失败/异常 → stderr 一行 + 跳过（fail-isolated），链不中断。
"""
import json
import sys
import urllib.parse
import urllib.request

from . import sources

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def pexels_images(card: dict, query: str, api_key: str, per_page: int = 10) -> list[str]:
    """Pexels 搜图 → large2x 直链列表。provider 未启用 / 无 key → []。"""
    prov = card["providers"].get("pexels")
    if not prov or not prov.get("enabled"):
        return []
    if not api_key:
        return []
    q = urllib.parse.quote(query)
    url = "%s?query=%s&per_page=%d&orientation=portrait" % (prov["endpoint"], q, per_page)
    req = urllib.request.Request(url, headers={"Authorization": api_key, "User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read())
    return [p["src"]["large2x"] for p in d.get("photos", [])
            if p.get("src", {}).get("large2x")]


def pixabay_images(card: dict, query: str, api_key: str, per_page: int = 10) -> list[str]:
    """Pixabay 搜图 → largeImageURL/webformatURL 列表。provider 未启用 / 无 key → []。"""
    prov = card["providers"].get("pixabay")
    if not prov or not prov.get("enabled"):
        return []
    if not api_key:
        return []
    q = urllib.parse.quote(query)
    url = ("%s?key=%s&q=%s&per_page=%d&orientation=vertical&image_type=photo"
           "&safesearch=true&category=fashion" % (prov["endpoint"], api_key, q, per_page))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read())
    urls = []
    for h in d.get("hits", []):
        u = h.get("largeImageURL") or h.get("webformatURL")
        if u:
            urls.append(u)
    return urls


def chain_candidates(cfg: dict, card: dict, query: str,
                     keys: dict | None = None, album_dir: str | None = None):
    """按 chain 顺序遍历可用 provider → (urls_or_items, src_name) 生成器（fail-isolated）。

    cfg:    config.json（chain + providers 段）；缺 chain → 默认 [pexels, pixabay, bing]。
    card:   model-card（providers 开关/endpoint 读它）。
    query:  实际搜索串。
    keys:   {源名: API key}（调用方从 .env 解析注入）。
    album_dir: 真人相簿根（local_dir 源用；photo/ video/ 子目录）。

    每个源产出一批候选后 yield 一次（str=URL 或 dict={ref, local}），grab 层逐个处理。
    """
    chain = cfg.get("chain") or ["pexels", "pixabay", "bing"]
    providers_cfg = cfg.get("providers") or {}
    ctx = {"card": card, "keys": keys or {}, "album_dir": album_dir or ""}
    for name in chain:
        spec = providers_cfg.get(name)
        # 配置缺失 → 回退内置 builtin 映射（配置缺/坏不阻塞，仍走默认链）
        if spec is None:
            spec = {"enabled": True, "entry": "builtin:%s" % name}
        if not isinstance(spec, dict) or spec.get("enabled") is False:
            continue
        entry = spec.get("entry")
        fn = sources.resolve_entry(entry)
        if fn is None:
            print("realphoto: provider %r 加载失败，跳过" % name, file=sys.stderr)
            continue
        opts = spec.get("options") or {}
        try:
            items = list(fn(query, ctx, opts) or [])
        except Exception as e:
            print("realphoto: provider %r 异常，跳过: %s" % (name, e), file=sys.stderr)
            continue
        if items:
            yield items, name
