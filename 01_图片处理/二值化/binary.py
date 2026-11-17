#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
binarix - 图片二值化命令行程序（零依赖，仅用 Python 标准库）

支持读取: PNG(灰度/RGB/调色板/RGBA, 8/16 位) / PGM / PPM
支持输出: 8 位灰度 PNG

用法示例:
    python binary.py photo.jpg.png                     # 自动 Otsu
    python binary.py in.png -o out.png -m sauvola -b 31 -k 0.2
    python binary.py in.png -m mean -b 25 -c 8 --denoise
    python binary.py a.png b.png --outdir ./out       # 批量
    python binary.py in.png --preview                  # 只看统计不写文件

算法:
    otsu    类间方差最大化，全自动，适合光照均匀的扫描件
    fixed   固定阈值，手动精确控制
    mean    自适应均值 (Bradley-Roth)，抗光照不均
    sauvola 局部均值+标准差，笔迹细节保留最好
    dither  Floyd-Steinberg 误差扩散，适合照片/插画
"""

import argparse
import os
import struct
import sys
import zlib

# --------------------------------------------------------------------------
# PNG 解码
# --------------------------------------------------------------------------

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read_png(path):
    """返回 (width, height, gray: bytearray)"""
    data = open(path, "rb").read()
    if data[:8] != PNG_SIG:
        raise ValueError("不是有效的 PNG 文件")

    pos = 8
    idat = []
    palette = None
    trns = None
    w = h = depth = ctype = interlace = 0

    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length

        if typ == b"IHDR":
            w, h, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", chunk)
        elif typ == b"PLTE":
            palette = chunk
        elif typ == b"tRNS":
            trns = chunk
        elif typ == b"IDAT":
            idat.append(chunk)
        elif typ == b"IEND":
            break

    if interlace:
        raise ValueError("暂不支持隔行扫描(interlaced) PNG，请另存为普通 PNG")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise ValueError("不支持的 PNG 颜色类型: %d" % ctype)
    if ctype == 3 and palette is None:
        raise ValueError("调色板 PNG 缺少 PLTE 块")

    raw = zlib.decompress(b"".join(idat))
    stride = (w * channels * depth + 7) // 8
    bpp = max(1, channels * depth // 8)

    # --- 反滤波，逐行还原 ---
    lines = []
    prev = bytearray(stride)
    p = 0
    for _y in range(h):
        ft = raw[p]
        p += 1
        cur = bytearray(raw[p:p + stride])
        p += stride

        if ft == 0:
            pass
        elif ft == 1:  # Sub
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif ft == 2:  # Up
            for i in range(stride):
                cur[i] = (cur[i] + prev[i]) & 0xFF
        elif ft == 3:  # Average
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:  # Paeth
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + _paeth(a, prev[i], c)) & 0xFF
        else:
            raise ValueError("未知的 PNG 滤波类型: %d" % ft)

        lines.append(cur)
        prev = cur

    # --- 转灰度 ---
    gray = bytearray(w * h)

    if depth == 8:
        if ctype == 0:
            for y in range(h):
                gray[y * w:(y + 1) * w] = lines[y][:w]
        elif ctype == 2:
            for y in range(h):
                ln = lines[y]
                base = y * w
                for x in range(w):
                    r, g, b = ln[x * 3], ln[x * 3 + 1], ln[x * 3 + 2]
                    gray[base + x] = (299 * r + 587 * g + 114 * b) // 1000
        elif ctype == 3:
            for y in range(h):
                ln = lines[y]
                base = y * w
                for x in range(w):
                    idx = ln[x]
                    r, g, b = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
                    gray[base + x] = (299 * r + 587 * g + 114 * b) // 1000
        elif ctype == 4:
            for y in range(h):
                ln = lines[y]
                gray[y * w:(y + 1) * w] = ln[0::2][:w]
        elif ctype == 6:
            for y in range(h):
                ln = lines[y]
                base = y * w
                for x in range(w):
                    q = x * 4
                    r, g, b = ln[q], ln[q + 1], ln[q + 2]
                    a = ln[q + 3]
                    # 透明区域按白纸处理
                    if a < 250:
                        r = (r * a + 255 * (255 - a)) // 255
                        g = (g * a + 255 * (255 - a)) // 255
                        b = (b * a + 255 * (255 - a)) // 255
                    gray[base + x] = (299 * r + 587 * g + 114 * b) // 1000

    elif depth == 16:
        step = channels * 2
        for y in range(h):
            ln = lines[y]
            base = y * w
            for x in range(w):
                q = x * step
                if ctype in (0, 4):
                    gray[base + x] = ln[q]
                else:
                    r, g, b = ln[q], ln[q + 2], ln[q + 4]
                    gray[base + x] = (299 * r + 587 * g + 114 * b) // 1000

    else:  # 1 / 2 / 4 位（仅灰度与调色板）
        maxv = (1 << depth) - 1
        per_byte = 8 // depth
        mask = maxv
        for y in range(h):
            ln = lines[y]
            base = y * w
            for x in range(w):
                byte = ln[x // per_byte]
                shift = 8 - depth * (x % per_byte + 1)
                v = (byte >> shift) & mask
                if ctype == 3:
                    r, g, b = palette[v * 3], palette[v * 3 + 1], palette[v * 3 + 2]
                    gray[base + x] = (299 * r + 587 * g + 114 * b) // 1000
                else:
                    gray[base + x] = v * 255 // maxv

    return w, h, gray


def read_pnm(path):
    """P5 灰度 / P6 彩色 的简单解码"""
    data = open(path, "rb").read()
    tokens = []
    i = 0
    while len(tokens) < 4 and i < len(data):
        while i < len(data) and data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while i < len(data) and data[i:i + 1] not in (b"\n", b"\r"):
                i += 1
            continue
        start = i
        while i < len(data) and not data[i:i + 1].isspace():
            i += 1
        tokens.append(data[start:i])
    i += 1

    magic = tokens[0]
    w, h = int(tokens[1]), int(tokens[2])
    body = data[i:i + w * h * (3 if magic == b"P6" else 1)]
    gray = bytearray(w * h)
    if magic == b"P6":
        for p in range(w * h):
            r, g, b = body[p * 3], body[p * 3 + 1], body[p * 3 + 2]
            gray[p] = (299 * r + 587 * g + 114 * b) // 1000
    else:
        gray[:] = body
    return w, h, gray


def read_image(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        return read_png(path)
    if ext in (".pgm", ".ppm", ".pnm"):
        return read_pnm(path)
    raise ValueError("不支持的格式 %s（本程序只读 PNG / PGM / PPM；"
                     "JPG 请先用网页版或先转成 PNG）" % ext)


# --------------------------------------------------------------------------
# PNG 编码（8 位灰度）
# --------------------------------------------------------------------------

def _chunk(typ, payload):
    return (struct.pack(">I", len(payload)) + typ + payload
            + struct.pack(">I", zlib.crc32(typ + payload) & 0xFFFFFFFF))


def write_png_gray(path, w, h, px):
    raw = bytearray()
    for y in range(h):
        raw.append(0)                      # filter: None
        raw += px[y * w:(y + 1) * w]
    out = [PNG_SIG,
           _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)),
           _chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
           _chunk(b"IEND", b"")]
    with open(path, "wb") as f:
        f.write(b"".join(out))


# --------------------------------------------------------------------------
# 前置校正
# --------------------------------------------------------------------------

def gauss_blur(gray, w, h):
    """3x3 二项式平滑（可分离，压掉纸纹与传感器噪点）"""
    kern = (1, 2, 1)
    tmp = bytearray(w * h)
    out = bytearray(w * h)
    for y in range(h):
        base = y * w
        for x in range(w):
            acc = 0
            for d in (-1, 0, 1):
                xx = x + d
                if xx < 0:
                    xx = 0
                elif xx >= w:
                    xx = w - 1
                acc += gray[base + xx] * kern[d + 1]
            tmp[base + x] = acc >> 2
    for y in range(h):
        for x in range(w):
            acc = 0
            for d in (-1, 0, 1):
                yy = y + d
                if yy < 0:
                    yy = 0
                elif yy >= h:
                    yy = h - 1
                acc += tmp[yy * w + x] * kern[d + 1]
            out[y * w + x] = acc >> 2
    return out


def normalize_bg(gray, w, h, strength):
    """用大窗口均值估计纸面亮度，做除法归一化，消除阴影"""
    W = w + 1
    s = [0] * (W * (h + 1))
    for y in range(h):
        rs = 0
        yo, yp = (y + 1) * W, y * W
        for x in range(w):
            rs += gray[y * w + x]
            s[yo + x + 1] = s[yp + x + 1] + rs

    r = max(10, min(w, h) // 8)
    a = strength / 100.0
    out = bytearray(w * h)
    for y in range(h):
        y0 = max(0, y - r)
        y1 = min(h, y + r + 1)
        y0W, y1W = y0 * W, y1 * W
        base = y * w
        for x in range(w):
            x0 = max(0, x - r)
            x1 = min(w, x + r + 1)
            area = (y1 - y0) * (x1 - x0)
            total = s[y1W + x1] - s[y0W + x1] - s[y1W + x0] + s[y0W + x0]
            bg = max(8.0, total / area)
            v = gray[base + x] / bg * 205
            if v > 255:
                v = 255
            out[base + x] = int(gray[base + x] * (1 - a) + v * a + 0.5)
    return out


def stretch_contrast(gray, w, h):
    """按 2% / 98% 分位线性拉伸"""
    hist = [0] * 256
    for v in gray:
        hist[v] += 1
    total = len(gray)
    cut = total * 0.02

    lo, hi, acc = 0, 255, 0
    for i in range(256):
        acc += hist[i]
        if acc >= cut:
            lo = i
            break
    acc = 0
    for i in range(255, -1, -1):
        acc += hist[i]
        if acc >= cut:
            hi = i
            break
    if hi - lo < 8:
        return gray

    scale = 255.0 / (hi - lo)
    out = bytearray(len(gray))
    for i, v in enumerate(gray):
        val = (v - lo) * scale
        if val < 0:
            val = 0
        elif val > 255:
            val = 255
        out[i] = int(val + 0.5)
    return out


def preprocess(gray, w, h, args):
    g = gray
    if args.blur:
        g = gauss_blur(g, w, h)
    if args.norm:
        g = normalize_bg(g, w, h, args.norm_strength)
    if args.stretch:
        g = stretch_contrast(g, w, h)
    return g


# --------------------------------------------------------------------------
# 二值化算法
# --------------------------------------------------------------------------

def otsu(gray):
    hist = [0] * 256
    for v in gray:
        hist[v] += 1
    total = len(gray)
    sum_all = sum(i * hist[i] for i in range(256))
    sum_b = w_b = 0
    best, thr = -1.0, 127
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best:
            best, thr = var, t
    return thr


def binarize_fixed(gray, thr):
    return bytearray(255 if v > thr else 0 for v in gray)


def binarize_adaptive(gray, w, h, block, param, mode):
    """mode: mean | niblack | sauvola | wolf"""
    W = w + 1
    s = [0] * (W * (h + 1))
    q = [0] * (W * (h + 1))
    for y in range(h):
        rs = rq = 0
        yo, yp = (y + 1) * W, y * W
        row = y * w
        for x in range(w):
            v = gray[row + x]
            rs += v
            rq += v * v
            s[yo + x + 1] = s[yp + x + 1] + rs
            q[yo + x + 1] = q[yp + x + 1] + rq

    m_min = 255
    if mode == "wolf":
        for v in gray:
            if v < m_min:
                m_min = v

    out = bytearray(w * h)
    r = max(1, block // 2)
    for y in range(h):
        y0 = max(0, y - r)
        y1 = min(h, y + r + 1)
        y0W, y1W = y0 * W, y1 * W
        base = y * w
        for x in range(w):
            x0 = max(0, x - r)
            x1 = min(w, x + r + 1)
            area = (y1 - y0) * (x1 - x0)
            ssum = s[y1W + x1] - s[y0W + x1] - s[y1W + x0] + s[y0W + x0]
            mean = ssum / area

            if mode == "mean":
                t = mean - param
            else:
                qsum = q[y1W + x1] - q[y0W + x1] - q[y1W + x0] + q[y0W + x0]
                var = qsum / area - mean * mean
                if var < 0:
                    var = 0
                std = var ** 0.5

                if mode == "niblack":
                    t = mean + param * std
                elif mode == "sauvola":
                    t = mean * (1.0 + param * (std / 128.0 - 1.0))
                else:  # wolf
                    t = mean + param * (std / 128.0 - 1.0) * (mean - m_min)

            out[base + x] = 255 if gray[base + x] > t else 0
    return out


def sliding_minmax(gray, w, h, r):
    """滑动窗口最小/最大值，单调队列，O(n)"""
    from collections import deque
    r = max(0, min(r, w - 1, h - 1))

    min_h = bytearray(w * h)
    max_h = bytearray(w * h)
    for y in range(h):
        base = y * w
        dmin, dmax = deque(), deque()
        for x in range(w):
            add = x + r
            if add < w:
                va = gray[base + add]
                while dmin and gray[base + dmin[-1]] >= va:
                    dmin.pop()
                dmin.append(add)
                while dmax and gray[base + dmax[-1]] <= va:
                    dmax.pop()
                dmax.append(add)
            rem = x - r - 1
            if rem >= 0:
                if dmin and dmin[0] == rem:
                    dmin.popleft()
                if dmax and dmax[0] == rem:
                    dmax.popleft()
            min_h[base + x] = gray[base + dmin[0]]
            max_h[base + x] = gray[base + dmax[0]]

    mn = bytearray(w * h)
    mx = bytearray(w * h)
    for x in range(w):
        dmin, dmax = deque(), deque()
        for y in range(h):
            add = y + r
            if add < h:
                va = min_h[add * w + x]
                vb = max_h[add * w + x]
                while dmin and min_h[dmin[-1] * w + x] >= va:
                    dmin.pop()
                dmin.append(add)
                while dmax and max_h[dmax[-1] * w + x] <= vb:
                    dmax.pop()
                dmax.append(add)
            rem = y - r - 1
            if rem >= 0:
                if dmin and dmin[0] == rem:
                    dmin.popleft()
                if dmax and dmax[0] == rem:
                    dmax.popleft()
            mn[y * w + x] = min_h[dmin[0] * w + x]
            mx[y * w + x] = max_h[dmax[0] * w + x]
    return mn, mx


def binarize_bernsen(gray, w, h, block, contrast_thr):
    r = max(1, block // 2)
    mn, mx = sliding_minmax(gray, w, h, r)
    out = bytearray(w * h)
    for i in range(len(out)):
        lo, hi = mn[i], mx[i]
        if hi - lo < contrast_thr:
            out[i] = 255
        else:
            out[i] = 255 if gray[i] > (lo + hi) / 2 else 0
    return out


def binarize_dither(gray, w, h, thr):
    buf = [float(v) for v in gray]
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            i = y * w + x
            old = buf[i]
            nv = 0.0 if old < thr else 255.0
            out[i] = 0 if nv == 0 else 255
            err = old - nv
            if x + 1 < w:
                buf[i + 1] += err * 7 / 16
            if y + 1 < h:
                b = i + w
                if x > 0:
                    buf[b - 1] += err * 3 / 16
                buf[b] += err * 5 / 16
                if x + 1 < w:
                    buf[b + 1] += err * 1 / 16
    return out


def median_mask(mask, w, h):
    out = bytearray(len(mask))
    for y in range(h):
        for x in range(w):
            dark = 0
            for dy in (-1, 0, 1):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                b = yy * w
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if 0 <= xx < w and mask[b + xx] == 0:
                        dark += 1
            out[y * w + x] = 0 if dark >= 5 else 255
    return out


def close_mask(mask, w, h):
    """形态学闭运算：先膨胀黑再腐蚀黑，补上笔划里的小白洞（边界保持原值）"""
    dil = bytearray(mask)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            if mask[i] == 0:
                continue
            if (mask[i-1] == 0 or mask[i+1] == 0 or mask[i-w] == 0 or mask[i+w] == 0 or
                    mask[i-w-1] == 0 or mask[i-w+1] == 0 or mask[i+w-1] == 0 or mask[i+w+1] == 0):
                dil[i] = 0

    ero = bytearray(dil)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            if dil[i] == 255:
                continue
            if (dil[i-1] == 255 or dil[i+1] == 255 or dil[i-w] == 255 or dil[i+w] == 255 or
                    dil[i-w-1] == 255 or dil[i-w+1] == 255 or dil[i+w-1] == 255 or dil[i+w+1] == 255):
                ero[i] = 255
    return ero


def remove_small(mask, w, h, min_area):
    """清除面积小于 min_area 的黑色连通块（4 邻接，迭代 BFS）"""
    out = bytearray(mask)
    seen = bytearray(w * h)
    for start in range(len(mask)):
        if mask[start] != 0 or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        members = []
        while stack:
            p = stack.pop()
            members.append(p)
            x = p % w
            y = p // w
            if x > 0 and mask[p-1] == 0 and not seen[p-1]:
                seen[p-1] = 1
                stack.append(p-1)
            if x < w-1 and mask[p+1] == 0 and not seen[p+1]:
                seen[p+1] = 1
                stack.append(p+1)
            if y > 0 and mask[p-w] == 0 and not seen[p-w]:
                seen[p-w] = 1
                stack.append(p-w)
            if y < h-1 and mask[p+w] == 0 and not seen[p+w]:
                seen[p+w] = 1
                stack.append(p+w)
        if len(members) < min_area:
            for m in members:
                out[m] = 255
    return out


def run(gray, w, h, args):
    gray = preprocess(gray, w, h, args)
    method = args.method
    thr = None
    if method == "otsu":
        thr = otsu(gray)
        mask = binarize_fixed(gray, thr)
    elif method == "fixed":
        thr = args.threshold
        mask = binarize_fixed(gray, thr)
    elif method in ("mean", "bradley"):
        mask = binarize_adaptive(gray, w, h, args.block, args.C, "mean")
    elif method == "niblack":
        mask = binarize_adaptive(gray, w, h, args.block, args.kn, "niblack")
    elif method == "sauvola":
        mask = binarize_adaptive(gray, w, h, args.block, args.k, "sauvola")
    elif method == "wolf":
        mask = binarize_adaptive(gray, w, h, args.block, args.k, "wolf")
    elif method == "bernsen":
        mask = binarize_bernsen(gray, w, h, args.block, args.contrast)
    elif method == "dither":
        thr = args.threshold
        mask = binarize_dither(gray, w, h, thr)
    else:
        raise ValueError("未知算法: %s" % method)

    if args.close:
        mask = close_mask(mask, w, h)
    if args.median and method != "dither":
        mask = median_mask(mask, w, h)
    if args.min_area > 0:
        mask = remove_small(mask, w, h, args.min_area)
    if args.invert:
        mask = bytearray(255 - v for v in mask)

    black = sum(1 for v in mask if v == 0)
    return mask, thr, black


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="binarix",
        description="图片二值化（零依赖，支持 PNG/PGM/PPM）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python binary.py scan.png\n"
               "  python binary.py scan.png -m sauvola -b 31 -k 0.2 -o out.png\n"
               "  python binary.py a.png b.png --outdir out --median\n")
    ap.add_argument("inputs", nargs="+", help="输入图片路径")
    ap.add_argument("-o", "--output", help="输出路径（仅单文件时可用）")
    ap.add_argument("--outdir", default=".", help="批量输出目录（默认当前目录）")
    ap.add_argument("-m", "--method", default="otsu",
                    choices=["otsu", "fixed", "bradley", "mean", "niblack",
                             "sauvola", "wolf", "bernsen", "dither"],
                    help="二值化算法（默认 otsu；mean 是 bradley 的别名）")
    ap.add_argument("-t", "--threshold", type=int, default=128,
                    help="fixed/dither 的阈值 0-255（默认 128）")
    ap.add_argument("-b", "--block", type=int, default=31,
                    help="局部算法的邻域窗口（默认 31，建议奇数）")
    ap.add_argument("-c", "--C", type=int, default=10,
                    help="bradley 的偏移量 C（默认 10，越大白越多）")
    ap.add_argument("-k", "--k", type=float, default=0.2,
                    help="sauvola/wolf 的灵敏度 k（默认 0.2）")
    ap.add_argument("--kn", type=float, default=-0.2,
                    help="niblack 的灵敏度 k（默认 -0.2，取负值）")
    ap.add_argument("--contrast", type=int, default=15,
                    help="bernsen 的局部对比度门限（默认 15）")
    ap.add_argument("--norm", action="store_true",
                    help="光照归一化：按局部背景亮度做除法，消除阴影")
    ap.add_argument("--norm-strength", type=int, default=70,
                    help="光照归一化强度 0-100（默认 70）")
    ap.add_argument("--stretch", action="store_true",
                    help="对比度拉伸（2%%-98%% 分位重映射）")
    ap.add_argument("--blur", action="store_true", help="3x3 高斯预模糊")
    ap.add_argument("--close", action="store_true",
                    help="闭运算填孔，补上笔划里的小白洞")
    ap.add_argument("--min-area", type=int, default=0,
                    help="清除面积小于该值的黑色连通块（默认 0 关闭，可试 20）")
    ap.add_argument("--invert", action="store_true", help="反色（白字黑底）")
    ap.add_argument("--median", action="store_true", help="中值去噪，去除孤立椒盐点")
    ap.add_argument("--preview", action="store_true", help="只打印统计，不写文件")
    ap.add_argument("-q", "--quiet", action="store_true", help="静默模式")
    args = ap.parse_args(argv)

    if args.output and len(args.inputs) > 1:
        ap.error("-o 只能用于单个输入文件，批量请用 --outdir")

    if args.outdir and not os.path.isdir(args.outdir):
        os.makedirs(args.outdir, exist_ok=True)

    for path in args.inputs:
        if not os.path.isfile(path):
            print("跳过（文件不存在）: %s" % path, file=sys.stderr)
            continue
        try:
            w, h, gray = read_image(path)
        except Exception as e:
            print("读取失败 %s: %s" % (path, e), file=sys.stderr)
            continue

        mask, thr, black = run(gray, w, h, args)
        pct = black / len(mask) * 100

        if args.output:
            out_path = args.output
        else:
            stem = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(args.outdir, stem + "_bw.png")

        if not args.preview:
            write_png_gray(out_path, w, h, mask)

        if not args.quiet:
            t = "自动 %d" % thr if thr is not None else "局部自适应"
            print("%s  %dx%d  算法=%s  阈值=%s  黑像素=%.1f%%  ->  %s"
                  % (os.path.basename(path), w, h, args.method, t, pct,
                     "(preview)" if args.preview else out_path))

    return 0


if __name__ == "__main__":
    sys.exit(main())
