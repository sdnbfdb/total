# -*- coding: utf-8 -*-
"""
M2 · 特征层（构建文档 §7.2）
jieba 分词/实体抽取 + 同义词归一 + bge-small-zh 语义向量（唯一特征通道，带本地缓存）。
语义模型不可用属于致命错误，直接抛出；不提供 TF-IDF/SVD 降级通道。
"""
import os
import re
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
VEC_CACHE = os.path.join(DATA_DIR, "vectors.npz")

EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
EMBED_DIM = 512                       # bge-small-zh-v1.5 输出维度
MODEL_TAG = "fastembed:" + EMBED_MODEL
HF_ENDPOINT = "https://hf-mirror.com"  # 国内镜像，可用环境变量 HF_ENDPOINT 覆盖
BODY_CTX = 256  # 预留：灰区仲裁时正文参与编码的截断长度（当前向量只用标题，见 embed_text）

# 同义词典（词面零重叠的同义对兜底，§7.2 召回增强）；规范词 → 变体集
SYNONYMS = {
    "土豆": {"马铃薯", "洋芋", "山药蛋", "薯仔"},
    "红薯": {"地瓜", "白薯", "番薯", "红苕", "甘薯"},
    "番茄": {"西红柿"},
    "玉米": {"苞谷", "苞米", "棒子"},
    "人工智能": {"AI", "ai"},
    "自动驾驶": {"无人驾驶"},
    "手机": {"智能手机"},
    "新能源汽车": {"电动车", "电车"},
    "新冠": {"新冠肺炎", "新冠病毒"},
    "激光": {"镭射"},
    "视频": {"影片", "短片"},
}
_CANON = {}
for _c, _vs in SYNONYMS.items():
    _CANON[_c] = _c
    for _v in _vs:
        _CANON[_v] = _c

_PUNCT_RE = re.compile(r"[\s\u3000，。！？、：；“”‘’（）《》【】…—\-_,.;:!?'\"()]+]")
_NUM_RE = re.compile(r"^\d+(\.\d+)?[%万亿]?$")


def canonical(w):
    return _CANON.get(w, w)


def tokenize(text):
    """jieba 分词 → 规范化 token 列表（同义词映射为规范词）。"""
    import jieba
    toks = []
    for w in jieba.cut(_PUNCT_RE.sub(" ", text or "")):
        w = w.strip()
        if not w:
            continue
        toks.append(w)
        c = canonical(w)
        if c != w:
            toks.append(c)
    return toks


def entities(text):
    """抽取实体集：人名/地名/机构/名词/英文缩写/数字（经同义词归一）。"""
    import jieba.posseg as pseg
    ents = set()
    for w, flag in pseg.cut(_PUNCT_RE.sub(" ", text or "")):
        w = w.strip()
        if not w or len(w) > 12:
            continue
        if flag in ("nr", "ns", "nt", "nz", "eng") and len(w) >= 2:
            ents.add(canonical(w))
        elif flag == "m" and _NUM_RE.match(w):
            ents.add(w)
        elif flag.startswith("n") and len(w) >= 3:
            ents.add(canonical(w))
    return ents


def embed_text(rec):
    """记录 → 编码文本：只用标题。
    标题是事件判定主信号；snippet/正文保留在 body_pool 与摘要中，不参与向量编码，
    避免长文本冲淡标题语义并把 CPU 编码拖慢一倍（待灰区仲裁实现时可单独编码正文）。
    """
    return rec.get("title", "") or ""


class Embedder:
    """bge-small-zh 语义向量封装。依赖或模型不可用时直接抛错，绝不静默降级。"""

    def __init__(self, model_name=EMBED_MODEL):
        os.environ.setdefault("HF_ENDPOINT", HF_ENDPOINT)
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise RuntimeError(
                "语义向量通道不可用：缺少 fastembed，请安装（pip install fastembed）。"
                "本系统不提供 TF-IDF 降级通道。"
            ) from e
        try:
            self.model = TextEmbedding(model_name, threads=os.cpu_count() or 4)
        except Exception as e:
            raise RuntimeError(
                f"语义模型加载失败（{model_name}）：{type(e).__name__}: {e}。"
                "请检查网络/镜像（HF_ENDPOINT）或模型缓存。"
            ) from e
        self.dim = EMBED_DIM

    def encode(self, texts, batch_size=256):
        """→ float32 [n, EMBED_DIM]，L2 归一化。"""
        vecs = np.array(list(self.model.embed(texts, batch_size=batch_size)), dtype=np.float32)
        if vecs.ndim != 2 or vecs.shape[1] != self.dim:
            raise RuntimeError(f"语义向量维度异常：{vecs.shape}，期望 (*, {self.dim})")
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.clip(norms, 1e-9, None)


class VecCache:
    """记录级向量缓存：key = date|source|title。
    严格校验模型签名、keys/vecs 行数一致性与维度；任一不符一律丢弃重建，
    避免不同模型空间的向量混用导致相似度失真。
    """

    def __init__(self, path=VEC_CACHE, model_tag=MODEL_TAG, dim=EMBED_DIM):
        self.path = path
        self.model_tag = model_tag
        self.dim = dim
        self.keys = {}          # key -> 行号
        self.key_list = []      # 与 self.vecs 行一一对应
        self.vecs = None
        if not os.path.exists(path):
            return
        try:
            z = np.load(path, allow_pickle=True)
            tag = str(z["model"]) if "model" in z else ""
            keys = [str(k) for k in z["keys"]]
            vecs = z["vecs"]
            if tag != model_tag:
                print(f"  [cache] 模型签名缺失/不符（{tag or '无签名'}），丢弃旧缓存")
            elif len(keys) != vecs.shape[0]:
                print(f"  [cache] keys({len(keys)}) 与 vecs({vecs.shape[0]}) 行数不符，丢弃旧缓存")
            elif vecs.ndim != 2 or vecs.shape[1] != dim:
                print(f"  [cache] 向量维度不符 {vecs.shape}，丢弃旧缓存")
            else:
                self.key_list = keys
                self.vecs = vecs
                self.keys = {k: i for i, k in enumerate(keys)}
        except Exception as e:
            print(f"  [cache] 缓存读取失败，将全量重算：{type(e).__name__}: {e}")
            self.keys, self.key_list, self.vecs = {}, [], None

    @staticmethod
    def rec_key(rec):
        return f"{rec['date']}|{rec['source']}|{rec['title']}"

    def lookup(self, recs):
        """返回 (命中向量矩阵或 None, 未命中的记录列表)。"""
        miss = [r for r in recs if self.rec_key(r) not in self.keys]
        return self.vecs, miss

    def put(self, recs, mat):
        """按 key 去重合并后整体写回，保证 keys 与 vecs 严格对齐。"""
        merged = ({k: v for k, v in zip(self.key_list, self.vecs)}
                  if self.vecs is not None else {})
        for r, v in zip(recs, mat):
            merged[self.rec_key(r)] = v
        self.key_list = list(merged)
        self.vecs = np.stack([merged[k] for k in self.key_list]).astype(np.float32)
        self.keys = {k: i for i, k in enumerate(self.key_list)}
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        np.savez_compressed(self.path, keys=np.array(self.key_list), vecs=self.vecs,
                            model=np.array(self.model_tag))

    def get_vec(self, rec):
        return self.vecs[self.keys[self.rec_key(rec)]]

    def get_vec_or_none(self, rec):
        i = self.keys.get(self.rec_key(rec))
        return None if i is None else self.vecs[i]
