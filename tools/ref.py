#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ref.py · 借鉴库管理工具（纯标准库，零依赖）

  add     新建一本参考书的五件套目录（从 _模板 复制）
  scan    反洗稿扫描：我的正文 vs 借鉴库禁区语料，连续相同 ≥N 字即报警
  report  借鉴度报告：单源占比 / 依赖度 / 改造度 / L3 表达层

用法：
  python tools/ref.py add    --code R02 --title "书名" --track "赛道"
  python tools/ref.py scan   [--min-gram 12] [--chapter 001]
  python tools/ref.py report
"""
import argparse
import os
import re
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REF_DIR = "10-reference"
TPL_DIR = "_模板"
TPL_FILES = [
    "00-七维基因卡.md",
    "01-结构节拍表.md",
    "02-人物原型库.md",
    "03-可移植清单.md",
    "04-禁区清单.md",
]

BLOCK_RE = re.compile(r"```[^\n]*\n([\s\S]*?)```")
KEEP_RE = re.compile(r"[^\u4e00-\u9fff0-9A-Za-z]")


def get_root(args):
    if getattr(args, "root", None):
        return os.path.abspath(args.root)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def norm(s):
    """只保留汉字/字母/数字，去标点与空白，用于连续相同比对。"""
    return KEEP_RE.sub("", s or "")


def ref_dirs(root):
    base = os.path.join(root, REF_DIR)
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        if os.path.isdir(p) and name.upper().startswith("R") and not name.startswith("_"):
            out.append((name, p))
    return out


def corpus(root):
    """收集禁区语料：04-禁区清单.md 的代码块 + 目录下所有 .txt。"""
    items = []
    for code, d in ref_dirs(root):
        txt = read(os.path.join(d, "04-禁区清单.md"))
        for m in BLOCK_RE.finditer(txt):
            for line in m.group(1).splitlines():
                line = line.strip()
                if line and not line.startswith("（"):
                    items.append((code, line))
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".txt"):
                for line in read(os.path.join(d, fn)).splitlines():
                    line = line.strip()
                    if line:
                        items.append((code, line))
    return items


# ---------------------------------------------------------------- add
def cmd_add(args):
    root = get_root(args)
    base = os.path.join(root, REF_DIR)
    tpl = os.path.join(base, TPL_DIR)
    if not os.path.isdir(tpl):
        print("🔴 找不到模板目录：%s" % tpl)
        return
    safe = re.sub(r'[\\/:*?"<>|]', "", args.title).strip() or args.code
    target = os.path.join(base, "%s-%s" % (args.code, safe))
    if os.path.isdir(target):
        print("🟡 已存在，未覆盖：%s" % target)
        return
    os.makedirs(target, exist_ok=True)
    for fn in TPL_FILES:
        src = os.path.join(tpl, fn)
        dst = os.path.join(target, fn)
        if os.path.isfile(src):
            txt = read(src)
            if args.title:
                txt = txt.replace("《书名》", "《%s》" % args.title)
                txt = txt.replace("R0x", args.code)
                if args.track:
                    txt = txt.replace("赛道: \n", "赛道: %s\n" % args.track)
                    txt = txt.replace("赛道: ", "赛道: %s " % args.track, 1)
            with open(dst, "w", encoding="utf-8") as f:
                f.write(txt)
    print("✅ 已创建：%s" % target)
    for fn in TPL_FILES:
        print("   - %s" % fn)
    print("   下一步：在 01-溯源索引.md 加一行，然后按 RA→RB→RC 拆书。")


# ---------------------------------------------------------------- scan
def my_chapters(root, only=None):
    d = os.path.join(root, "03-chapters")
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md") or fn.startswith("_"):
            continue
        m = re.search(r"(\d{3,4})", fn)
        num = int(m.group(1)) if m else 0
        if only and str(num) not in only and ("%04d" % num) not in only:
            continue
        out.append((num, fn, read(os.path.join(d, fn))))
    return out


def cmd_scan(args):
    root = get_root(args)
    n = args.min_gram
    items = corpus(root)
    chaps = my_chapters(root, set(args.chapter or []))

    if not chaps:
        print("🟡 没有可扫描的正文（03-chapters/*.md）")
        return
    if not items:
        print("🟡 禁区语料为空：请在 10-reference/R0x/04-禁区清单.md 的代码块里粘贴原文片段")
        return

    # 预处理语料 n-gram
    grams = {}   # gram -> (code, line)
    for code, line in items:
        nl = norm(line)
        if len(nl) < n:
            continue
        for i in range(len(nl) - n + 1):
            grams.setdefault(nl[i:i + n], (code, line))

    total_hits = 0
    for num, fn, text in chaps:
        body = text
        if "## 章末自检速记" in body:
            body = body.split("## 章末自检速记")[0]
        nb = norm(body)
        hits = []
        for i in range(len(nb) - n + 1):
            g = nb[i:i + n]
            if g in grams:
                hits.append((i, g, grams[g][0]))
        if not hits:
            continue
        # 只合并位置相邻、且同源的命中，避免把两处独立片段接成一条
        merged = []   # [片段, 最后位置, 来源]
        for i, g, code in hits:
            if merged and i == merged[-1][1] + 1 and code == merged[-1][2]:
                merged[-1][0] += g[-1]
                merged[-1][1] = i
            else:
                merged.append([g, i, code])
        uniq = {}
        for frag, _last, code in merged:
            key = frag[:min(len(frag), 24)]
            uniq.setdefault(key, [frag, code, 0])
            uniq[key][2] += 1
        total_hits += len(uniq)
        print("\n🔴 第 %d 章（%s）：命中 %d 处" % (num, fn, len(uniq)))
        for frag, code, cnt in list(uniq.values())[:args.show]:
            print("   来源 %s ｜ 连续相同 %d 字 ｜ 片段：%s…" % (code, len(frag), frag[:24]))
        if len(uniq) > args.show:
            print("   …另有 %d 处" % (len(uniq) - args.show))

    if total_hits == 0:
        print("✅ 未发现表达污染（连续相同 ≥%d 字，扫描 %d 章 / 语料 %d 条）" % (n, len(chaps), len(items)))
    else:
        print("\n共命中 %d 处。🔴 每处都必须改：不是换同义词，是重写这个意思。" % total_hits)
        print("改完重跑：python tools/ref.py scan")


# ---------------------------------------------------------------- report
def col_of(cells, header, keyword):
    for k, v in zip(header, cells):
        if keyword in k:
            return v.strip()
    return ""


def parse_ledger(text):
    header, rows = None, []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and "来源编号" in s:
            header = [c.strip() for c in s.strip("|").split("|")]
            continue
        if header and s.startswith("|") and not re.fullmatch(r"\|[\s:|-]+\|", s):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) == len(header) and cells[0] and not cells[0].startswith("---"):
                src = col_of(cells, header, "来源编号")
                if src:                                 # 跳过未填来源的空模板行
                    rows.append(dict(zip(header, cells)))
    return rows


def cmd_report(args):
    root = get_root(args)
    rows = parse_ledger(read(os.path.join(root, REF_DIR, "90-移植审批台账.md")))
    if not rows:
        print("🟡 移植审批台账为空或表头不含「来源编号」列")
        return

    def col(r, *names):
        for k in r:
            if any(nm in k for nm in names):
                return r[k]
        return ""

    stat = {}
    l3 = 0
    rework, sim = [], []
    for r in rows:
        src = col(r, "来源编号").strip() or "未填"
        layer = col(r, "借鉴层")
        if "L3" in layer or "表达" in layer:
            l3 += 1
        stat[src] = stat.get(src, 0) + 1
        for key, bucket in (("改造度", rework), ("相似度", sim)):
            m = re.search(r"(\d+)\s*%", col(r, key))
            if m:
                bucket.append(int(m.group(1)))

    total = len(rows)
    print("移植条目总数：%d\n" % total)
    print("| 来源 | 条目数 | 占比 | 判定 |")
    print("|---|---|---|---|")
    for src, c in sorted(stat.items(), key=lambda x: -x[1]):
        pct = c * 100.0 / total
        flag = "🔴 超 25%" if pct > 25 else ("🟡 接近上限" if pct > 20 else "✅")
        print("| %s | %d | %.1f%% | %s |" % (src, c, pct, flag))

    print("\n硬指标：")
    top_pct = max(stat.values()) * 100.0 / total
    print("  单一来源最高占比：%.1f%%（红线 ≤25%%）%s" % (top_pct, "🔴" if top_pct > 25 else "✅"))
    if rework:
        avg = sum(rework) / len(rework)
        print("  平均改造度：%.0f%%（红线 ≥60%%）%s" % (avg, "✅" if avg >= 60 else "🔴"))
    if sim:
        avg = sum(sim) / len(sim)
        print("  平均相似度：%.0f%%（红线 ≤40%%）%s" % (avg, "✅" if avg <= 40 else "🔴"))
    print("  L3 表达层条目：%d（红线 = 0）%s" % (l3, "✅" if l3 == 0 else "🔴"))

    if l3 or top_pct > 25:
        print("\n处理：L3 条目立即删除并记入禁区清单；超比例来源再引入 1 本同赛道 + 1 本跨赛道来源做融合。")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="借鉴库管理工具（纯标准库）")
    ap.add_argument("--root", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="新建一本参考书的五件套")
    a.add_argument("--code", required=True, help="如 R02")
    a.add_argument("--title", default="", help="书名")
    a.add_argument("--track", default="", help="赛道")
    a.set_defaults(func=cmd_add)

    s = sub.add_parser("scan", help="反洗稿扫描")
    s.add_argument("--min-gram", type=int, default=12, help="连续相同多少字算命中，默认 12")
    s.add_argument("--chapter", nargs="*", default=None, help="只扫指定章，如 001 002")
    s.add_argument("--show", type=int, default=5, help="每章最多显示多少条")
    s.set_defaults(func=cmd_scan)

    r = sub.add_parser("report", help="借鉴度报告")
    r.set_defaults(func=cmd_report)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
