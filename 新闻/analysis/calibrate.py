# -*- coding: utf-8 -*-
"""
阈值标定（构建文档 §11）
用「干净」语义向量重算回归集相似度，输出三档分布、当前阈值判定表现，
并以弱标签网格搜索建议的 T_SAME / T_REL。

用法（请用服务所用解释器）：python analysis/calibrate.py
注意：eval_pairs 的 prelabel 是自动预标（intra 来自簇内，可能含噪声），
本脚本同时给出仅由人工种子构成的 seed 子集结果，以 seed 为准。
"""
import collections
import json
import os
import sys

import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import similarity
import vectorize


def load_title_vecs():
    z = np.load(vectorize.VEC_CACHE, allow_pickle=True)
    keys = [str(k) for k in z["keys"]]
    vecs = z["vecs"]
    if len(keys) != vecs.shape[0]:
        raise RuntimeError("向量缓存 keys/vecs 行数不一致，请先运行 --encode-only")
    t2v = {}
    for k, v in zip(keys, vecs):
        parts = k.split("|", 2)
        t = parts[2] if len(parts) == 3 else k
        t2v.setdefault(t, v)
    return t2v


def main():
    pairs = json.load(open(os.path.join(BASE_DIR, "data", "eval_pairs.json"), encoding="utf-8"))
    t2v = load_title_vecs()
    missing = sorted({p[k] for p in pairs for k in ("a", "b") if p[k] not in t2v})
    if missing:
        emb = vectorize.Embedder()
        mat = emb.encode(missing)
        t2v.update(zip(missing, mat))
    for p in pairs:
        p["sim"] = float(t2v[p["a"]] @ t2v[p["b"]])

    print("=== 三档相似度分布（prelabel，弱标签）===")
    by = collections.defaultdict(list)
    for p in pairs:
        by[p["prelabel"]].append(p["sim"])
    for lab in ("同事件", "相关", "无关"):
        s = sorted(by[lab])
        q = [round(s[min(int(len(s) * x), len(s) - 1)], 3)
             for x in (0, .1, .25, .5, .75, .9, 1.0)]
        print(f"  {lab:4s} n={len(s):3d} 分位 {q}")

    print("\n=== 人工种子子集（label 可信）===")
    for p in pairs:
        if p["note"].startswith("seed"):
            print(f"  {p['id']} sim={p['sim']:.3f} 标={p['prelabel']:4s} "
                  f"{p['a'][:24]} <> {p['b'][:24]}")

    def f1_grid(pos_key, lo=0.30, hi=0.85, step=0.01, subset=None):
        data = subset if subset is not None else pairs
        best = (0.0, None, 0, 0, 0)
        t = lo
        while t <= hi + 1e-9:
            tp = fp = fn = 0
            for p in data:
                pred = p["sim"] >= t
                gold = pos_key(p)
                if pred and gold:
                    tp += 1
                elif pred and not gold:
                    fp += 1
                elif not pred and gold:
                    fn += 1
            prec = tp / (tp + fp) if tp + fp else 0
            rec = tp / (tp + fn) if tp + fn else 0
            f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
            if f1 > best[0]:
                best = (f1, round(t, 2), tp, fp, fn)
            t += step
        return best

    print("\n=== 网格搜索（弱标签，仅作参考）===")
    for name, key in [
        ("T_SAME（同事件 vs 其余）", lambda p: p["prelabel"] == "同事件"),
        ("T_REL（同事件+相关 vs 无关）", lambda p: p["prelabel"] != "无关"),
    ]:
        f1, t, tp, fp, fn = f1_grid(key)
        print(f"  {name:34s} 建议 {t:.2f} · F1={f1:.3f} (TP={tp} FP={fp} FN={fn})")

    print("\n=== 当前阈值下的判定（seed 子集）===")
    seed = [p for p in pairs if p["note"].startswith("seed")]
    ok = 0
    for p in seed:
        pred = ("同事件" if p["sim"] >= similarity.T_SAME else
                "相关" if p["sim"] >= similarity.T_REL else "无关")
        ok += pred == p["prelabel"]
        print(f"  {p['id']} {p['sim']:.3f} 判={pred:4s} 标={p['prelabel']:4s} "
              f"{'OK' if pred == p['prelabel'] else 'X'}")
    print(f"  seed 准确率 {ok}/{len(seed)}")
    print(f"\n当前常量: T_DUP={similarity.T_DUP} T_SAME={similarity.T_SAME} "
          f"T_REL={similarity.T_REL} T_ENTITY_REL={similarity.T_ENTITY_REL}")


if __name__ == "__main__":
    main()
