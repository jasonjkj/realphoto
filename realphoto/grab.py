#!/usr/bin/env python3
"""grab.py — 抓模特：现场抓一张合格模特图。

主源: Pexels / Pixabay API（读 model-card.json providers 开关），必应兜底（agent_utils 图搜）。
流程: 搜关键词 → 本地校验真图 + 尺寸闸门 + md5 去重 → vision 预过滤（外部验货入口，
      不合格不落盘重抓）→ 落 <REALPHOTO_HOME>/model-grab/ 并返回路径。
可选: fill/consume 保留旧池化模式（<REALPHOTO_HOME>/model-pool/），供 cron 预抓备用。

vision 验货经 see_image 注入（缺省 vision.default_see_image = 外部脚本 subprocess）；
入口失败 = 验货不通过（fail-closed），连续失败达 VISION_FAIL_LIMIT 跳过该来源。
"""
import hashlib
import json
import os
import random
import re
import shutil
import sys
import time

from agent_utils.extras.imagesearch import bing_image_search
from agent_utils.extras.imgio import download_image, is_real_image, min_dim_ok

from . import config, paths, providers, sources, vision as vision_adapter

MAX_RECENT_MD5 = 6
VISION_FAIL_LIMIT = 4  # 同一来源连续 vision 失败达此阈值 → 跳过该来源（防死循环）
MIN_DIM = 100          # 本地硬闸门：最小边低于此像素直接拒（省 vision token）

# 必应兜底拒链黑名单（本包业务语义，不放进共享库）
REJECT_HOSTS = ["gettyimages", "stocksy.com", "shutterstock", "adobe stock",
                "alamy.com", "dreamstime", "123rf", "istockphoto", "youtube",
                "youtubeimg", "gstatic.com"]

_vision_fail = {}      # {来源名: 连续 vision 失败次数}，跨 grab 调用保留（进程内）


def load_env_value(key_name):
    """取 provider key：先读 `REALPHOTO_HOME/.env`，回退进程环境变量。

    只读本包自己的配置目录，不碰任何外部系统的 .env。文件缺失 / 读失败不崩。
    """
    try:
        with open(os.path.join(paths.home(), ".env"), encoding="utf-8") as f:
            m = re.search(r'^%s\s*=\s*["\']?([^"\'\s]+)' % re.escape(key_name),
                          f.read(), re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return os.environ.get(key_name, "")


def _provider_key(card, name):
    prov = card["providers"].get(name) or {}
    env_key = prov.get("env_key")
    return load_env_value(env_key) if env_key else ""


def _last_state(grab_dir):
    """去重状态文件路径（函数内取 grab_dir，保证 mock 时可替换为临时目录）。"""
    return os.path.join(grab_dir, "last.json")


def bing_images(query, n=10):
    """必应兜底（搜索机制在 agent-utils，拒链黑名单是本包语义）。"""
    return bing_image_search(query, n=n, reject=REJECT_HOSTS)


# 合格判据：这三个键必须全为 true（缺键按不通过处理）。
# **代码不预设"什么样的人算合格"** —— 具体条件写在档案自己的 verify_prompt 里，
# 由你的视觉模型判成 is_usable。改判据 → 改档案，不改代码。
ACCEPT_KEYS = ("is_person", "is_single_person", "is_usable")


def passes_accept(j):
    """验货 JSON → 是否合格（ACCEPT_KEYS 全 true 才放行）。"""
    return all(j.get(k) is True for k in ACCEPT_KEYS)


def pool_size(pool=None):
    pool = pool or paths.pool_dir()
    if not os.path.isdir(pool):
        return 0
    return len([f for f in os.listdir(pool)
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))])


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_md5s(grab_dir):
    """跨进程去重状态：最近已发图的 md5 列表（grab 专用，persist last.json）。"""
    try:
        with open(_last_state(grab_dir), encoding="utf-8") as f:
            d = json.load(f)
        return list(d.get("md5s", []))[:MAX_RECENT_MD5]
    except Exception:
        return []


def _save_md5(grab_dir, md5):
    """把刚发出去的图指纹记入 last.json（超 MAX_RECENT_MD5 裁尾）。"""
    cur = [m for m in _load_md5s(grab_dir) if m != md5]
    cur.append(md5)
    cur = cur[-MAX_RECENT_MD5:]
    os.makedirs(os.path.dirname(_last_state(grab_dir)), exist_ok=True)
    tmp = _last_state(grab_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"md5s": cur}, f, ensure_ascii=False)
    os.replace(tmp, _last_state(grab_dir))


def fill(n, card, vprompt, *, see_image=None, pool=None, log=print):
    """抓 N 张合格图入池（旧池化模式，不经 md5 去重——池内自然多样）。"""
    see = see_image or vision_adapter.default_see_image
    pool = pool or paths.pool_dir()
    os.makedirs(pool, exist_ok=True)
    got = 0
    seen = set()

    def offer(cands):
        nonlocal got
        for u in cands:
            if u in seen or got >= n:
                continue
            seen.add(u)
            tmp = os.path.join(pool, "候-验证-%d.jpg" % len(seen))
            if not download_image(u, tmp, min_bytes=40000, check_magic=True):
                continue
            try:
                out = see(tmp, vprompt)
                j = json.loads(re.search(r"\{.*\}", out, re.S).group())
            except Exception:
                os.unlink(tmp)
                continue
            if passes_accept(j):
                # 文件名带序号防同秒覆盖（原名仅秒级时间戳，同秒两张会互相盖掉）
                new = os.path.join(pool, "model-%s-%d-%d.jpg" % (
                    re.sub(r"[^\w\u4e00-\u9fff-]", "", card["name"] or "model")[:20],
                    int(time.time()), got))
                os.rename(tmp, new)
                log("入池[%d] %s" % (got + 1, new))
                log("  reason: %s" % j.get("reason", ""))
                got += 1
            else:
                os.unlink(tmp)

    def pexels(card_, kw):
        return providers.pexels_images(card_, kw, _provider_key(card_, "pexels"))

    def pixabay(card_, kw):
        return providers.pixabay_images(card_, kw, _provider_key(card_, "pixabay"))

    # 1) Pexels API → 2) Pixabay API → 3) 必应兜底
    for src_name, fn in (("Pexels", pexels), ("Pixabay", pixabay)):
        for kw in card["search_keywords"]:
            if got >= n:
                break
            try:
                log("(%s: %s)" % (src_name, kw), file=sys.stderr)
                offer(fn(card, kw))
            except Exception as e:
                log("%s 失败 [%s] %s" % (src_name, kw, e), file=sys.stderr)
    for kw in card["search_keywords"]:
        if got >= n:
            break
        try:
            log("Bing 兜底: %s" % kw, file=sys.stderr)
            offer(bing_images(kw))
        except Exception as e:
            log("搜索失败 [%s] %s" % (kw, e), file=sys.stderr)
    return got


def consume(card, vprompt, *, see_image=None, pool=None, grab_dir=None):
    """从池消费一张（旧模式）；池空先补抓 1 张。"""
    pool = pool or paths.pool_dir()
    grab_dir = grab_dir or paths.grab_dir()
    files = []
    if os.path.isdir(pool):
        files = [os.path.join(pool, f) for f in os.listdir(pool)
                 if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
    if not files:
        print("池空, 补抓 1 张…", file=sys.stderr)
        fill(1, card, vprompt, see_image=see_image, pool=pool)
        files = [os.path.join(pool, f) for f in os.listdir(pool)
                 if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))] \
            if os.path.isdir(pool) else []
    if not files:
        print("NO_GOOD 池仍空, 抓不到合格模特图", file=sys.stderr)
        return None
    src = random.choice(files)
    os.makedirs(grab_dir, exist_ok=True)
    dst = os.path.join(grab_dir, "模特发-%s.jpg" % int(time.time()))
    shutil.move(src, dst)
    return dst


def _offer_grab(cands, src_name, seen, max_candidates, grab_dir, pool,
                recent_md5s=None, vprompt=None, fail_budget=None, stats=None,
                see_image=None):
    """逐个处理候选：本地硬闸门（真图/尺寸/md5 去重）→ vision 验货，
    全部通过才搬到 grab_dir；不合格删 tmp 继续下一候选（重抓不落盘）。
    cands 元素：str=URL（下载）或 dict={ref, local}（local=True 本地相簿直出）。
    see_image=None 时不 vision 验货。fail_budget 达 VISION_FAIL_LIMIT 停该来源。
    返回 (dst, src_name)；本轮无合格/超上限返回 None。"""
    see = see_image
    recent_md5s = recent_md5s or []
    budget = fail_budget if fail_budget is not None else {}
    st = stats if stats is not None else {}
    if budget.get(src_name, 0) >= VISION_FAIL_LIMIT:
        return None
    for cand in list(cands or [])[:5]:
        local = False
        if isinstance(cand, dict):
            ref = cand.get("ref") or ""
            local = bool(cand.get("local"))
        else:
            ref = cand
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if len(seen) > max_candidates:
            return None
        if local:
            # 本地相簿直出：不下载，直接走后续闸门（免网、免 vision 可选）
            tmp = ref
        else:
            tmp = os.path.join(pool, "抓-临时-%d.jpg" % len(seen))
            if not download_image(ref, tmp, min_bytes=40000, check_magic=True):
                continue
        if not min_dim_ok(tmp, MIN_DIM):
            print("跳过过小图: %s" % ref, file=sys.stderr)
            if not local:
                os.unlink(tmp)
            continue
        if md5_file(tmp) in recent_md5s:
            print("跳过已发过的重复图: %s" % ref, file=sys.stderr)
            if not local:
                os.unlink(tmp)
            continue
        if see is not None and vprompt is not None:
            st["vision"] = st.get("vision", 0) + 1
            try:
                out = see(tmp, vprompt)
                j = json.loads(re.search(r"\{.*\}", out, re.S).group())
                ok = passes_accept(j)
            except Exception:
                ok = False
            if not ok:
                st["retry"] = st.get("retry", 0) + 1
                budget[src_name] = budget.get(src_name, 0) + 1
                if not local:
                    os.unlink(tmp)
                if budget[src_name] >= VISION_FAIL_LIMIT:
                    print("告警: %s 连续 vision 失败达 %d 次, 跳过该来源" % (
                        src_name, VISION_FAIL_LIMIT), file=sys.stderr)
                    return None
                continue
            budget[src_name] = 0
        dst = os.path.join(grab_dir, "模特-%s.jpg" % int(time.time()))
        if local:
            shutil.copy2(tmp, dst)
        else:
            os.replace(tmp, dst)
        return dst, src_name
    return None


def grab_one(card, max_candidates=30, kw=None, *, see_image="__default__",
             grab_dir=None, pool=None, vprompt=None):
    """现场抓一张合格模特图：本地硬闸门 + vision 预过滤（默认走外部验货入口）。

    kw 非空时临时覆盖 card search_keywords。see_image:
      "__default__" → 外部入口 subprocess（vision.default_see_image）；
      None          → 不验货（仅本地硬闸门）；
      callable      → 注入验货（测试 / 调用方定制）。
    同一来源连续 vision 失败达 VISION_FAIL_LIMIT → 跳过该来源。
    返回 (dst, src_name) / None。每轮结束向 stderr 打印一行指标。"""
    see = vision_adapter.default_see_image if see_image == "__default__" else see_image
    grab_dir = grab_dir or paths.grab_dir()
    pool = pool or paths.pool_dir()
    stats = {"vision": 0, "retry": 0}
    try:
        os.makedirs(grab_dir, exist_ok=True)
        os.makedirs(pool, exist_ok=True)
        # 清掉上次崩溃残留的临时文件（会被旧 consume 当合格货发出）
        if os.path.isdir(pool):
            for f in os.listdir(pool):
                if f.startswith("抓-临时-"):
                    try:
                        os.unlink(os.path.join(pool, f))
                    except OSError:
                        pass
        seen = set()
        recent_md5s = set(_load_md5s(grab_dir))
        # 已发过的历史图指纹一并纳入去重，避免换一轮又撞旧图
        if os.path.isdir(grab_dir):
            for f in os.listdir(grab_dir):
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    try:
                        recent_md5s.add(md5_file(os.path.join(grab_dir, f)))
                    except OSError:
                        pass
        recent_md5s = list(recent_md5s)
        vprompt = vprompt if vprompt is not None else card["verify_prompt"]

        def do_offer(urls, src_name):
            if len(seen) > max_candidates:
                return None
            if _vision_fail.get(src_name, 0) >= VISION_FAIL_LIMIT:
                print("告警: %s 连续 vision 失败达 %d 次, 跳过该来源" % (
                    src_name, VISION_FAIL_LIMIT), file=sys.stderr)
                return None
            return _offer_grab(urls, src_name, seen, max_candidates,
                               grab_dir, pool, recent_md5s, vprompt,
                               _vision_fail, stats, see)

        keywords = [kw] if kw else list(card["search_keywords"])
        cfg = config.load_config()
        keys = {n: _provider_key(card, n)
                for n in config.chain_of(cfg) if card.get("providers", {}).get(n, {}).get("env_key")}
        album = config.album_dir_of(cfg)
        # 按 chain 顺序遍历 provider（主渠道 → fallback；单源失败隔离自动跳过）
        for k in keywords:
            for items, src_name in providers.chain_candidates(cfg, card, k,
                                                              keys=keys, album_dir=album):
                if len(seen) > max_candidates:
                    return None
                hit = do_offer(items, src_name)
                if hit:
                    _save_md5(grab_dir, md5_file(hit[0]))
                    return hit
        return None
    finally:
        print("grab 指标: vision=%d 重抓=%d" % (stats["vision"], stats["retry"]),
              file=sys.stderr)


def grab_many(card, n=5, profile_cfg=None, *, see_image="__default__",
              grab_dir=None, pool=None):
    """按画像抓 n 张合格（流式 generator：每张合格 yield (dst, src_name)）。

    profile_cfg: 画像配置（keywords + verify_prompt）；None → 用 card 默认。
    串行；跨张 md5 去重靠 grab_one 落盘 last.json（下一张自动避重）。
    """
    kw_list = (profile_cfg or {}).get("keywords") or list(card["search_keywords"])
    vprompt = (profile_cfg or {}).get("verify_prompt") or card["verify_prompt"]
    for i in range(max(1, int(n))):
        kw = kw_list[i % len(kw_list)]
        hit = grab_one(card, kw=kw, see_image=see_image,
                       grab_dir=grab_dir, pool=pool, vprompt=vprompt)
        if hit:
            yield hit
        else:
            break
