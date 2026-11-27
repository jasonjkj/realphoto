# realphoto

**纯资源抓取的真人素材包**：从本地素材库随机直发图片，或按 provider 链现场抓取模特图（带本地硬闸门与可选视觉验货）。**不生成、不做换脸、不绑任何外部系统。**

- import 名 / dist 名都是 `realphoto`
- 有一个 CLI：`realphoto-bff`

## 1. 能做什么

| 能力 | 说明 |
|---|---|
| **素材库直发** | 从本地相簿（`REALPHOTO_ALBUM_DIR`）随机取图直发，不重复、上限 9 张；**不生成、不验货** |
| **抓模特** | provider 链（内置 pexels / pixabay / bing / local_dir，可接外部函数）；本地硬闸门（magic-byte / 最小尺寸 / md5 去重）+ **可选视觉验货**，不合格不落盘直接重抓 |

**边界（刻意不做）**：无图像生成 / 无背景替换 / 不持任何 API key / 不读外部配置文件。验货能力由你注入（见 §4）。

## 2. 安装

```bash
git clone https://github.com/jasonjkj/realphoto.git
cd realphoto
python -m pip install -e ".[dev]"
```

依赖 [`agent-utils`](https://github.com/jasonjkj/agent-utils)（必应图搜 + 图片字节工具），pip 会从 git 一并装 `v0.5.0`。

**注意别装错包**：本包没有发布到 PyPI，且 PyPI 上的 `agent-utils` 是另一个人的同名项目。
单独装依赖时务必带 git 地址：

```bash
python -m pip install "agent-utils @ git+https://github.com/jasonjkj/agent-utils.git@v0.5.0"
```

## 3. 快速开始

### 3.1 模特档案

包里带一份 `realphoto/data/model-card.example.json`（示例档案，provider 全关），开箱即可读。

要换成自己的对象：

```bash
mkdir -p ~/.realphoto
cp realphoto/data/model-card.example.json ~/.realphoto/model-card.json
# 编辑 name / alias / identity / source_accounts / search_keywords / verify_prompt
```

档案查找顺序（先命中先用）：

1. `REALPHOTO_HOME/model-card.json` —— 运行态覆盖，不动包
2. 包内 `realphoto/data/model-card.json` —— 你自己放进去的档案
3. 包内 `realphoto/data/model-card.example.json` —— 示例档案

### 3.2 provider key

抓图 provider 需要各自 API key。设环境变量（或写进 `REALPHOTO_HOME/.env`），并在档案的 `providers.<name>.enabled` 置 `true`：

| provider | 环境变量 |
|---|---|
| Pexels | `PEXELS_API_KEY` |
| Pixabay | `PIXABAY_API_KEY` |
| Unsplash | `UNSPLASH_API_KEY` |

`bing` 兜底不需要 key。

### 3.3 素材库

把要直发的图片放进 `REALPHOTO_HOME/album/photo/`（可被 `REALPHOTO_ALBUM_DIR` 覆盖），即可随机取用。

## 4. 验货：为什么要"配一下才生效"

抓到的图在落盘前可以被一道视觉检查过滤掉。本包**不绑定任何视觉实现**，你有两种给法：

| 方式 | 做法 |
|---|---|
| **注入 callable**（推荐） | `grab.grab_one(card, ..., see_image=lambda path, prompt: "...")`，进程内直接调你的模型 |
| **外部脚本** | 设 `REALPHOTO_VISION_CMD=/path/to/vision.py`，按 `<python> <脚本> <图片> --prompt <提示>` 调用，从输出里抠 JSON |
| **不验货** | 显式传 `see_image=None`，只走本地硬闸门 |

**fail-closed 是刻意的**：没配入口时验货判不通过（而不是放过）。所以如果你什么都不配又不显式传 `None`，
抓模特会一张也抓不进来 —— 这是设计，不是 bug。同一来源连续失败 ≥4 次会熔断该来源。

验货要返回一段含 JSON 的文本，判据是 `grab.ACCEPT_KEYS` 里三个键**全为 true**：

```
{"is_person": true, "is_single_person": true, "is_usable": true, "reason": "..."}
```

**"什么样算合格"代码不预设** —— 种族、性别、风格、年龄条件全部写在你档案的 `verify_prompt` 里，
由你的模型判成 `is_usable`。换对象只改档案，不改代码。

## 5. CLI（`realphoto-bff`）

| 子命令 | 行为 | 输出 |
|---|---|---|
| `send-asset [--video] [-n N]` | 素材库直发 | 每行 `MEDIA:<绝对路径>`；无素材 `NO_IMAGE` rc=1 |
| `grab-model [--kw "<关键词>"]` | 现场抓一张合格模特图 | `MEDIA:<路径>` + 来源行；无合格 `NO_GOOD` rc=1 |
| `pool-status` | 缓存查询 | 单行 JSON（目录 / 数量 / 验货入口 / 档案路径 / 版本） |
| `inspect <图片>` | 只验货单张，不抓 | 验货原文 |
| `fill N` / `consume` | 预抓入池 / 从池取一张 | 入池数 / `MEDIA:<路径>` |

## 6. Python API

```python
from realphoto import bff

bff.send_asset(video=False, n=1)   # -> rc；stdout 打 MEDIA 行
bff.grab_model(kw=None)            # -> rc；stdout 打 MEDIA 行
bff.pool_status()                  # -> rc；stdout 打 JSON
```

底层模块：`realphoto.pick`（素材库）/ `realphoto.grab`（抓模特）/ `realphoto.providers` / `realphoto.card`（档案）/ `realphoto.paths`（路径）/ `realphoto.vision`（验货适配）/ `realphoto.config`（配置）。

## 7. env 变量表

| 变量 | 缺省 | 用途 |
|---|---|---|
| `REALPHOTO_HOME` | `~/.realphoto` | 运行态根：`model-grab/`、`model-pool/`、`last.json`、可选 `model-card.json`、可选 `.env` |
| `REALPHOTO_ALBUM_DIR` | `$REALPHOTO_HOME/album` | 素材库根（`photo/`、`video/` 子目录） |
| `REALPHOTO_CONFIG` | `$REALPHOTO_HOME/config.json` | 抓模特配置（chain / providers / album / storage） |
| `REALPHOTO_VISION_CMD` | 未设 | 外部验货脚本；不设则验货 fail-closed |
| `PEXELS_API_KEY` / `PIXABAY_API_KEY` / `UNSPLASH_API_KEY` | — | provider key |

全部缺省都落在**你自己的数据目录**下，不依赖任何外部目录结构 —— 换机器、换路径直接可用。

## 8. 数据

- `realphoto/data/model-card.example.json` — 示例档案（provider 全关，无真实人物信息），复制改造即用。
- 真实档案（`model-card.json`）**不入库**，只在你的 `REALPHOTO_HOME` 下。
- 必应兜底的拒链黑名单是本包语义，在 `grab.REJECT_HOSTS`，不外露给依赖库。

## 9. 测试

```bash
python -m pytest tests/ -q      # 57 项，全 mock（零真网 / 零真 key / 零 ffmpeg）
```

覆盖：直发不重复与上限、空库；抓模特的命中链路、验货正反用例与 fail-closed、熔断、md5 历史去重、尺寸闸门、关键词覆盖、必应兜底；BFF 的 `MEDIA:` 协议与 CLI；档案加载与三级回退。

## 10. 已知缺口

- **不做意图路由**：本包只管"有素材就发 / 给定关键词就抓"，把用户自然语言映射成关键词是你那一层的事。
- **不内置视觉模型**：见 §4，要自己接。
- **不生成图像**：换背景、换脸这类能力不在本包范围内。

## License

MIT，见 [LICENSE](LICENSE)。
