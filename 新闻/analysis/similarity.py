# -*- coding: utf-8 -*-
"""
M2 · 双通道相似度（构建文档 §7.2/§7.3）
综合分 = 语义精排分 + 实体重叠加成；阈值均为余弦相似度（初始值，§11 回归集标定）。
语义向量为唯一特征通道，无 TF-IDF 降级分支。
"""


# §7.3 阈值表（初始值，以 data/eval_pairs.json 标定）
T_DUP = 0.92    # ≥ : 同一报道（转载），去重但计次
T_SAME = 0.62   # ~T_DUP : 同一事件（保持高精确，漏合并由相关边召回）
T_REL = 0.42    # ~T_SAME : 相关事件（保持独立）
                # <T_REL : 无关
T_ENTITY_REL = 0.35  # 实体召回通道下限：共享实体时允许在更低语义分建相关边
# 标定依据（calibrate.py, 2026-11-09）：干净 bge 下同事件对 0.52~0.68、相关对约 0.47、
# 无关对 0.28~0.60（含「苹果」类歧义），单一阈值无法全分对，故保留高 T_SAME + 实体门控。

ENTITY_BONUS = 0.08   # 实体 Jaccard 加成上限之外的权重（综合分 = sem + bonus）


def entity_jaccard(a, b):
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def combine(sem, ent_j):
    """综合分 = 语义余弦 + 实体重叠加成（唯一通道）。"""
    return float(min(1.0, sem + ENTITY_BONUS * ent_j))


def band(s):
    if s >= T_DUP:
        return "dup"
    if s >= T_SAME:
        return "same"
    if s >= T_REL:
        return "related"
    return "none"


def pair_score(sem, ent_j):
    s = combine(sem, ent_j)
    return {"combined": s, "band": band(s), "sem": sem, "entity": ent_j}
