"""config.py — 抓模特配置加载。

配置路径：`REALPHOTO_CONFIG` > `$REALPHOTO_HOME/config.json`。
缺文件 / 损坏 → 返回默认（n=5, stream=true, chain=[pexels,pixabay,bing]）。

配置结构：
  grab:     {n: 每批张数, stream: 流式开关}
  chain:    [provider 名按优先级]（主渠道 → fallback）；不在 chain 的一律不调
  album:    {dir: 素材库根（photo/ video/ 子目录）}
  storage:  {dir: 抓取缓存根（model-grab/model-pool 上级目录）}
  profiles: {id: {keywords, verify_prompt}}  人群画像
  intent_words: {口语词: 画像 id}
  user_prefs:  {}
"""
import json
import os

from . import paths

DEFAULTS = {
    "grab": {"n": 5, "stream": True},
    "chain": ["pexels", "pixabay", "bing"],
    "album": {},
    "storage": {},
    "profiles": {},
    "intent_words": {},
    "user_prefs": {},
}


def config_path():
    return os.environ.get("REALPHOTO_CONFIG") or os.path.join(paths.home(), "config.json")


def load_config(path=None):
    """读配置；缺文件/损坏 → 默认。"""
    p = path or config_path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else DEFAULTS
    except Exception:
        return DEFAULTS


def resolve_profile(profile, cfg=None):
    """口语 / 画像名 → 画像配置 dict；未命中 / 空 → None（调用方回退默认）。

    支持两种入参：口语词（经 intent_words 映射到画像 id）或画像 id 本身。
    """
    cfg = cfg if cfg is not None else load_config()
    if not profile:
        return None
    words = cfg.get("intent_words") or {}
    key = words.get(profile) or profile
    prof = (cfg.get("profiles") or {}).get(key)
    if prof:
        prof = dict(prof)
        prof["id"] = key
    return prof


def chain_of(cfg=None):
    """chain 列表（缺省默认链）。"""
    cfg = cfg if cfg is not None else load_config()
    c = cfg.get("chain")
    return list(c) if isinstance(c, list) and c else list(DEFAULTS["chain"])


def album_dir_of(cfg=None):
    """素材库根（photo/ video/ 子目录）。配置没写就回退 env / 缺省目录。"""
    cfg = cfg if cfg is not None else load_config()
    d = (cfg.get("album") or {}).get("dir")
    return os.path.expanduser(d) if d else paths.album_dir()


def storage_dir_of(cfg=None):
    """抓取缓存根（model-grab/model-pool 上级目录）。配置没写就回退 REALPHOTO_HOME。"""
    cfg = cfg if cfg is not None else load_config()
    d = (cfg.get("storage") or {}).get("dir")
    return os.path.expanduser(d) if d else paths.home()
