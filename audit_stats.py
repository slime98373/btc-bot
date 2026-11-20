#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_stats.py
Zero-dependency statistical testing utilities for financial time series:
  - Exact Welch's t-test (Welch-Satterthwaite df + Incomplete Beta student-t CDF)
  - Mann-Whitney U test (tie-corrected, fat-tail robust)
  - Two-proportion Z test (win-rate comparison)
  - Block Permutation test (autocorrelation-robust p-value)
  - Benjamini-Hochberg FDR multiple-testing correction
"""

import math
import random
from typing import Dict, List, Tuple


def summarize(vals: List[float]) -> Tuple[int, float, float, float]:
    """Return (n, mean, std, up_rate_pct)."""
    n = len(vals)
    if n == 0:
        return 0, 0.0, 0.0, 0.0
    m = sum(vals) / n
    var = sum((x - m) ** 2 for x in vals) / max(1, n - 1)
    up = sum(1 for x in vals if x > 0) / n * 100.0
    return n, m, math.sqrt(var), up


def _betacf(a: float, b: float, x: float) -> float:
    max_it, eps, fpmin = 200, 3e-12, 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_it + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def student_t_p_two_sided(t_stat: float, df: float) -> float:
    if df <= 0:
        return 1.0
    if df > 500.0:
        return math.erfc(abs(t_stat) / math.sqrt(2.0))
    x = df / (df + t_stat * t_stat)
    return min(1.0, max(0.0, _betainc(df / 2.0, 0.5, x)))


def welch_t_test(a: List[float], b: List[float], min_n: int = 10) -> Tuple[float, float, float]:
    """Return (diff_mean, t_stat, exact_two_sided_p)."""
    na, ma, sa, _ = summarize(a)
    nb, mb, sb, _ = summarize(b)
    if na < min_n or nb < min_n:
        return ma - mb, 0.0, 1.0
    va = (sa * sa) / na
    vb = (sb * sb) / nb
    se = math.sqrt(va + vb)
    if se <= 1e-12:
        return ma - mb, 0.0, 1.0
    denom = (va * va) / max(1, na - 1) + (vb * vb) / max(1, nb - 1)
    df = ((va + vb) ** 2) / denom if denom > 1e-18 else float(na + nb - 2)
    t_stat = (ma - mb) / se
    return ma - mb, t_stat, student_t_p_two_sided(t_stat, df)


def mann_whitney_u_test(a: List[float], b: List[float], min_n: int = 10) -> float:
    """Two-sided tie-corrected Mann-Whitney U p-value (robust to fat tails)."""
    na, nb = len(a), len(b)
    if na < min_n or nb < min_n:
        return 1.0
    combined = [(v, 0) for v in a] + [(v, 1) for v in b]
    combined.sort(key=lambda x: x[0])
    n = na + nb

    rank_sum_a = 0.0
    tie_corr = 0.0
    i = 0
    while i < n:
        j = i + 1
        while j < n and combined[j][0] == combined[i][0]:
            j += 1
        t = j - i
        avg_rank = 0.5 * (i + 1 + j)
        for k in range(i, j):
            if combined[k][1] == 0:
                rank_sum_a += avg_rank
        if t > 1:
            tie_corr += (t * t * t - t)
        i = j

    u1 = rank_sum_a - na * (na + 1) / 2.0
    mu = na * nb / 2.0
    var_factor = (n + 1.0) - tie_corr / (n * (n - 1.0)) if n > 1 else 0.0
    sigma = math.sqrt(max(0.0, (na * nb / 12.0) * var_factor))
    if sigma <= 1e-12:
        return 1.0
    z = max(0.0, abs(u1 - mu) - 0.5) / sigma
    return math.erfc(z / math.sqrt(2.0))


def proportion_z_test(a: List[float], b: List[float], min_n: int = 10) -> Tuple[float, float]:
    """Compare positive-return rates (Up%) of group a vs group b. Return (diff_pct, p_val)."""
    na, nb = len(a), len(b)
    if na < min_n or nb < min_n:
        return 0.0, 1.0
    ka = sum(1 for x in a if x > 0)
    kb = sum(1 for x in b if x > 0)
    pa, pb = ka / na, kb / nb
    p_pool = (ka + kb) / (na + nb)
    se = math.sqrt(max(0.0, p_pool * (1.0 - p_pool) * (1.0 / na + 1.0 / nb)))
    if se <= 1e-12:
        return (pa - pb) * 100.0, 1.0
    z = (pa - pb) / se
    return (pa - pb) * 100.0, math.erfc(abs(z) / math.sqrt(2.0))


def block_permutation_p(
    series_rets: List[float],
    series_labels: List[int],
    block_size: int = 12,
    n_perm: int = 400,
    seed: int = 42,
    min_n: int = 10,
) -> float:
    """
    Block permutation test preserving serial autocorrelation.
    series_labels: +1 for expected bullish group, -1 for expected bearish group, 0 ignored.
    """
    n = len(series_rets)
    idx_pos = [i for i, lbl in enumerate(series_labels) if lbl == 1]
    idx_neg = [i for i, lbl in enumerate(series_labels) if lbl == -1]
    na, nb = len(idx_pos), len(idx_neg)
    if na < min_n or nb < min_n or n < block_size * 2:
        return 1.0

    obs = (sum(series_rets[i] for i in idx_pos) / na) - (sum(series_rets[i] for i in idx_neg) / nb)
    abs_obs = abs(obs)

    blocks = [series_rets[i:i + block_size] for i in range(0, n, block_size)]
    rng = random.Random(seed)
    exceed = 0
    for _ in range(n_perm):
        perm_blocks = blocks[:]
        rng.shuffle(perm_blocks)
        shuf = [x for blk in perm_blocks for x in blk]
        diff = (sum(shuf[i] for i in idx_pos) / na) - (sum(shuf[i] for i in idx_neg) / nb)
        if abs(diff) >= abs_obs:
            exceed += 1
    return (exceed + 1.0) / (n_perm + 1.0)


def bh_fdr(p_map: Dict[str, float]) -> Dict[str, float]:
    """Benjamini-Hochberg FDR adjusted q-values."""
    items = sorted(p_map.items(), key=lambda x: x[1])
    m = len(items)
    if m == 0:
        return {}
    raw_q = [min(1.0, p * m / (rank + 1)) for rank, (_, p) in enumerate(items)]
    for i in range(m - 2, -1, -1):
        if raw_q[i] > raw_q[i + 1]:
            raw_q[i] = raw_q[i + 1]
    return {items[i][0]: raw_q[i] for i in range(m)}
