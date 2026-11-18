# -*- coding: utf-8 -*-
"""事件脉络分析系统（构建文档 v1.3）。"""
import os
import sys

# 允许「import analysis.xxx」与「直接跑 analysis/xxx.py」两种方式的兄弟模块导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

__version__ = "1.3"
