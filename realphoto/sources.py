"""sources.py — 模特图 provider 链源函数。

每个源 = 一个 fetch(query, ctx, opts) -> 候选迭代（str=URL / dict={ref, local}）。
  query  实际搜索串（调用方给）
  ctx    只读上下文（card=档案、keys=各源 API key、album_dir=本地相簿根）
  opts   provider options（per_page / n / suffix / reject / dir 等）

内置源：pexels / pixabay / bing / local_dir（本地相簿目录）。
拒链黑名单等业务语义留在本模块；key 由 grab 层解析后注入 ctx，本模块不碰 .env。
"""
import importlib.util
import os

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 必应兜底拒链黑名单（本包业务语义，不放进共享库）
REJECT_HOSTS = ["gettyimages", "stocksy.com", "shutterstock", "adobe stock",
                "alamy.com", "dreamstime", "123rf", "istockphoto", "youtube",
                "youtubeimg", "gstatic.com"]

_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")


def _ctx_keys(ctx, name):
    """从 ctx.keys 取某源 API key；无 → ""（provider 未配 key → 源跳过）。"""
    keys = (ctx or {}).get("keys") or {}
    return keys.get(name) or ""


def _ctx_card(ctx):
    return (ctx or {}).get("card") or {}


def pexels_fetch(query, ctx, opts):
    """Pexels API 搜图 → large2x 直链列表。provider 未启用 / 无 key → []。"""
    from . import providers  # noqa: PLC0415  延迟 import（providers 顶层依赖本模块，防环）
    card = _ctx_card(ctx)
    key = _ctx_keys(ctx, "pexels")
    return providers.pexels_images(card, query, key)


def pixabay_fetch(query, ctx, opts):
    """Pixabay API 搜图 → largeImageURL/webformatURL 列表。provider 未启用 / 无 key → []。"""
    from . import providers  # noqa: PLC0415
    card = _ctx_card(ctx)
    key = _ctx_keys(ctx, "pixabay")
    return providers.pixabay_images(card, query, key)


def bing_fetch(query, ctx, opts):
    """必应兜底（搜索机制在 agent-utils，拒链黑名单是本包语义）。"""
    from agent_utils.extras.imagesearch import bing_image_search  # noqa: PLC0415
    n = int((opts or {}).get("n") or 10)
    reject = (opts or {}).get("reject") or REJECT_HOSTS
    suffix = (opts or {}).get("suffix") or ""
    q = (query + " " + suffix).strip() if suffix else query
    return bing_image_search(q, n=n, reject=reject)


def local_dir_fetch(query, ctx, opts):
    """本地相簿目录直出（local=True，免下载免验货直接落盘）。

    opts.dir 或 ctx.album_dir 决定目录（缺省 $REALPHOTO_HOME/album/photo）。
    返回 list[dict]（{ref, local}），供 chain 作为本地候选源。
    """
    d = (opts or {}).get("dir") or (ctx or {}).get("album_dir")
    if not d:
        return []
    d = os.path.expanduser(d)
    if not os.path.isdir(d):
        return []
    return [{"ref": os.path.join(d, f), "local": True}
            for f in sorted(os.listdir(d))
            if os.path.isfile(os.path.join(d, f))
            and f.lower().endswith(_IMG_EXTS)]


# 内置源注册表（resolve_entry 用）
BUILTINS = {
    "pexels": pexels_fetch,
    "pixabay": pixabay_fetch,
    "bing": bing_fetch,
    "local_dir": local_dir_fetch,
}


def resolve_entry(entry):
    """解析 provider entry → callable；解析失败 → None（调用方 stderr + 跳过）。

    支持三种形态：
      builtin:<name>             内置源（本文件 BUILTINS）
      <module>:<func>            import 模块（如 agent_utils.extras.imagesearch:bing_image_search）
      <路径.py>:<func>           任意文件按路径延迟加载（可把自己写的源放在任意路径）
    """
    if not entry or not isinstance(entry, str):
        return None
    if entry.startswith("builtin:"):
        return BUILTINS.get(entry[len("builtin:"):])
    if ":" not in entry:
        return None
    head, _, func = entry.rpartition(":")
    if os.sep in head or head.endswith(".py"):
        mod_path = os.path.expanduser(head)
        if not os.path.exists(mod_path):
            return None
        try:
            spec = importlib.util.spec_from_file_location(
                "realphoto_ext_%d" % abs(hash(mod_path)), mod_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:
            return None
        return getattr(mod, func, None)
    try:
        mod = __import__(head, fromlist=[func])
    except Exception:
        return None
    return getattr(mod, func, None)
