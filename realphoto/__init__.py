"""realphoto — 纯资源抓取的真人素材包（无生成）。

两块能力：
  - 素材库直发：从本地相簿随机取图直发，不生成、不验货
  - 抓模特：provider 链（内置 pexels / pixabay / bing / local_dir，可接外部函数），
    本地硬闸门（magic-byte / 最小尺寸 / md5 去重）+ 可选视觉验货

本包不持任何 API key，也不读外部配置文件；验货能力由调用方注入（见 README §4）。
"""
__version__ = "0.2.0"
