#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ctx.py · 长篇上下文工程工具（纯标准库，零依赖）

三个子命令：
  pack   装配本章上下文包（A常驻 + B近期 + C按需），自动裁剪到预算内
  roll   把本章摘要并入 04-context/CURRENT.md 并压缩旧条目
  check  一致性硬检查：时间单调 / 人物复活 / 伏笔超期 / 字数区间 / 摘要缺失

用法：
  python tools/ctx.py pack  --chapter 12 [--chars C001,C003] [--budget 4500] [--out 04-context/pack-0012.md]
  python tools/ctx.py roll  --chapter 12
  python tools/ctx.py check [--fore]
"""
import argparse
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------- 路径
def get_root(args):
    if getattr(args, "root", None):
        return os.path.abspath(args.root)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def P(root, *parts):
    return os.path.join(root, *parts)


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------- 解析
FIELD_RE = re.compile(r"^([^\s:：]{2,10})\s*[:：]\s*(.*)$")
DAY_RE = re.compile(r"D\+(\d+)")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
CH_RE = re.compile(r"第\s*(\d+)\s*章")
CODE_RE = re.compile(r"C\d{3}")


def parse_summary(text):
    """解析章节摘要的 yaml 块，返回字段字典。"""
    d = {}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```") or s.startswith("#") or s.startswith(">"):
            continue
        m = FIELD_RE.match(s)
        if m:
            d[m.group(1).strip()] = m.group(2).strip()
    return d


def list_summaries(root):
    """返回 [(章号int, 路径, 字段dict)]，按章号排序。"""
    out = []
    d = P(root, "03-chapters", "summaries")
    if not os.path.isdir(d):
        return out
    for fn in os.listdir(d):
        if not fn.endswith(".md") or fn.startswith("_"):
            continue
        txt = read(os.path.join(d, fn))
        f = parse_summary(txt)
        num = f.get("章号") or re.sub(r"\D", "", fn)
        try:
            num = int(re.sub(r"\D", "", str(num)) or 0)
        except Exception:
            num = 0
        out.append((num, os.path.join(d, fn), f))
    out.sort(key=lambda x: x[0])
    return out


def time_key(s):
    """把时间字段转成可比较的整数：优先 D+NN，其次 YYYY-MM-DD。"""
    if not s:
        return None
    m = DAY_RE.search(s)
    if m:
        return int(m.group(1))
    m = DATE_RE.search(s)
    if m:
        return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))
    return None


def iter_tables(text):
    """yield (header_cells, rows) —— rows 为 cell 列表的列表。"""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("|"):
            header = None
            rows = []
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    j += 1
                    continue
                if header is None:
                    header = cells
                else:
                    rows.append(cells)
                j += 1
            if header:
                yield header, rows
            i = j
        else:
            i += 1


def find_table(text, keyword):
    for header, rows in iter_tables(text):
        if any(keyword in h for h in header):
            return header, rows
    return None, []


def clean(s):
    return re.sub(r"[*`#]", "", s or "").strip()


# ---------------------------------------------------------------- 人物卡压缩
KEEP_SECTIONS = ("动机层", "能力边界", "语言习惯", "降智护栏", "状态", "关系")


def condense_char(text):
    """只保留写正文真正需要的段落，压缩人物卡体积。"""
    lines = text.splitlines()
    out, keep = [], True
    for ln in lines:
        s = ln.strip()
        m = re.match(r"^【(.+?)】", s)
        if m:
            keep = any(k in m.group(1) for k in KEEP_SECTIONS)
        if keep:
            out.append(ln)
    res = "\n".join(out).strip()
    return res if len(res) < len(text) else text


def find_char_file(root, code):
    d = P(root, "01-story-bible", "characters")
    if not os.path.isdir(d):
        return None
    for fn in sorted(os.listdir(d)):
        if fn.upper().startswith(code.upper()):
            return os.path.join(d, fn)
    return None


# ---------------------------------------------------------------- pack
SECTION_RE = re.compile(r"^##\s*【([A-D])\s*区", re.M)


def split_current(text):
    """把 CURRENT.md 切成 {A:…, B:…, C:…, D:…}。"""
    marks = [(m.start(), m.group(1)) for m in SECTION_RE.finditer(text)]
    out = {}
    if not marks:
        out["A"] = text
        return out
    for idx, (pos, key) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(text)
        out[key] = text[pos:end].rstrip()
    return out


def cmd_pack(args):
    root = get_root(args)
    n = args.chapter
    budget = args.budget
    cur = read(P(root, "04-context", "CURRENT.md"))
    secs = split_current(cur)

    blocks = []   # (优先级, 标题, 内容)  优先级越大越先被裁
    blocks.append((0, "A · 常驻上下文", secs.get("A", "_（CURRENT.md 未初始化 A 区）_")))
    blocks.append((0, "B · 近期上下文（最近 3 章）", secs.get("B", "_（未初始化）_")))

    # ---- C 按需
    summ = list_summaries(root)
    prev = [s for s in summ if s[0] < n]
    prev_cast = []
    if prev:
        prev_cast = CODE_RE.findall(prev[-1][2].get("出场人物", ""))
    codes = []
    if args.chars:
        codes += CODE_RE.findall(args.chars)
    codes += prev_cast
    codes += CODE_RE.findall("C001")
    seen, ordered = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    char_txt = []
    for c in ordered:
        fp = find_char_file(root, c)
        if fp:
            char_txt.append("#### %s\n%s" % (os.path.basename(fp)[:-3], condense_char(read(fp))))
    if char_txt:
        blocks.append((2, "C1 · 本章相关人物卡", "\n\n".join(char_txt)))

    # 伏笔：未回收且计划回收章在窗口内
    _, rows = find_table(read(P(root, "02-plot", "09-伏笔台账.md")), "编号")
    fore = []
    for r in rows:
        if len(r) < 8:
            continue
        code, content, plant, strengthen, plan, _way, status = (
            r[0], r[1], clean(r[3]), clean(r[4]), clean(r[5]), clean(r[6]), clean(r[7]))
        if status not in ("待回收", "已强化"):
            continue
        pm = CH_RE.search(plan)
        if pm and int(pm.group(1)) > n + args.window:
            continue
        fore.append("| %s | %s | %s | %s | %s | %s |" % (code, content, plant, strengthen, plan, status))
    if fore:
        head = "| 编号 | 伏笔内容 | 埋于 | 强化节点 | 计划回收 | 状态 |\n|---|---|---|---|---|---|"
        blocks.append((3, "C2 · 相关未回收伏笔", head + "\n" + "\n".join(fore)))

    # 时间线：最近若干行
    _, trows = find_table(read(P(root, "02-plot", "10-时间线台账.md")), "章号")
    tl = ["| " + " | ".join(r) + " |" for r in trows[-args.timeline:]]
    if tl:
        blocks.append((4, "C3 · 时间线（最近 %d 行）" % len(tl), "\n".join(tl)))

    # 名词规范表
    _, nrows = find_table(read(P(root, "01-story-bible", "00-故事圣经.md")), "标准名")
    nb = ["| " + " | ".join(r[:5]) + " |" for r in nrows[:args.terms]]
    if nb:
        blocks.append((5, "C4 · 名词规范表", "| 标准名 | 类型 | 禁用别名 | 首次出现章 | 释义 |\n|---|---|---|---|---|\n" + "\n".join(nb)))

    # 借鉴库：默认不载入，只有显式 --ref 才载「可移植清单」中已勾选的条目
    if args.ref:
        base = P(root, "10-reference")
        picked = []
        if os.path.isdir(base):
            for code in [c.strip().upper() for c in args.ref.split(",") if c.strip()]:
                folder = next((f for f in sorted(os.listdir(base))
                               if f.upper().startswith(code) and os.path.isdir(os.path.join(base, f))), None)
                if not folder:
                    print("🟡 未找到借鉴目录：%s" % code)
                    continue
                txt = read(os.path.join(base, folder, "03-可移植清单.md"))
                _h, rws = find_table(txt, "借鉴层")
                kept = []
                for r in rws:
                    if any(("☑" in c) or ("[x]" in c.lower()) or ("✅" in c) for c in r):
                        kept.append("| " + " | ".join(r) + " |")
                if kept:
                    picked.append("**%s · %s**（已勾选条目）\n\n| 借鉴层 | 抽象后的功能描述 | 我准备怎么用 | 融合来源 | 改造度 |\n|---|---|---|---|---|\n%s"
                                  % (code, folder, "\n".join(kept)))
        if picked:
            blocks.append((6, "C5 · 借鉴可移植条目（仅抽象描述，无原文）", "\n\n".join(picked)))

    # ---- 预算裁剪
    def total(bs):
        return sum(len(b[2]) for b in bs)

    dropped = []
    while blocks and total(blocks) > budget:
        cand = max(blocks, key=lambda b: (b[0], len(b[2])))
        if cand[0] == 0:
            break
        blocks.remove(cand)
        dropped.append(cand[1])

    body = ["# 上下文包 · 第 %d 章\n" % n]
    body.append("> 预算 %d 字 ｜ 实际 %d 字 ｜ 已裁掉：%s\n" % (budget, total(blocks), "、".join(dropped) or "无"))
    for _p, title, content in sorted(blocks, key=lambda b: b[0]):
        body.append("## %s\n" % title)
        body.append(content + "\n")
    out = "\n".join(body)

    if args.out:
        write(P(root, args.out), out)
        print("已生成：%s（%d 字，预算 %d）" % (P(root, args.out), total(blocks), budget))
        if dropped:
            print("已裁掉：%s" % "、".join(dropped))
    else:
        print(out)


# ---------------------------------------------------------------- roll
def cmd_roll(args):
    root = get_root(args)
    n = args.chapter
    spath = P(root, "03-chapters", "summaries", "ch%04d.md" % n)
    txt = read(spath)
    if not txt:
        print("🔴 找不到摘要：%s（先跑 P4 生成摘要）" % spath)
        return
    f = parse_summary(txt)
    one = "- **第 %s 章**（%s / %s）｜目标：%s｜事件：%s｜钩子：%s" % (
        f.get("章号", n), f.get("时间", "?"), f.get("地点", "?"),
        f.get("本章目标", ""), f.get("核心事件", ""), f.get("章末钩子", ""))

    cur_path = P(root, "04-context", "CURRENT.md")
    cur = read(cur_path)
    if not cur:
        print("🔴 CURRENT.md 不存在：%s" % cur_path)
        return
    marks = [(m.start(), m.group(1)) for m in SECTION_RE.finditer(cur)]
    keys = [k for _p, k in marks]
    if "B" not in keys:
        print("🔴 CURRENT.md 缺少【B 区】标题（形如 `## 【B 区 · 近期块】`），无法定位。")
        return

    # 按原始位置切出各区（含各自的 ## 标题行）
    slices = {}
    for idx, (pos, key) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(cur)
        slices[key] = cur[pos:end].rstrip()

    # --- B 区：替换条目列表，只保留最近 3 条（忽略占位符行 "第 ___ 章"）
    b = slices["B"]
    lines = b.splitlines()
    is_bullet = lambda l: l.strip().startswith("- **第")
    bullets = [l for l in lines if is_bullet(l) and "___" not in l]
    bullets.append(one)
    keep, moved = bullets[-3:], bullets[:-3]

    kept = [l for l in lines if not is_bullet(l)]
    idxs = [i for i, l in enumerate(lines) if is_bullet(l)]
    if idxs:
        before = sum(1 for i in range(idxs[0]) if not is_bullet(lines[i]))
    else:
        before = next((i for i, l in enumerate(kept) if "紧邻上文结尾" in l), len(kept))
    new_b = "\n".join(kept[:before] + list(keep) + kept[before:]) + "\n"

    # --- 上一章结尾 200 字
    body = read(P(root, "03-chapters", "ch%04d.md" % n))
    if body and "## 章末自检速记" in body:
        body = body.split("## 章末自检速记")[0]
    raw = "\n".join(l for l in body.splitlines()
                    if l.strip() and not l.strip().startswith(("#", ">", "章号")))
    tail = re.sub(r"\s+", " ", raw.strip())[-200:] if raw.strip() else ""
    if tail:
        m = re.search(r"(紧邻上文结尾[^\n]*\n)```[\s\S]*?```", new_b)
        if m:
            new_b = new_b[:m.start()] + m.group(1) + "```\n" + tail + "\n```" + new_b[m.end():]
        else:
            print("   🟡 CURRENT.md 未找到「紧邻上文结尾」代码块，已跳过结尾片段更新")

    # --- D 区：被挤出去的压成一行
    if moved:
        compact = "\n".join("- " + re.sub(r"^\s*-\s*", "", re.sub(r"\*\*", "", m).strip()) for m in moved)
        d = slices.get("D", "## 【D 区 · 历史压缩块】")
        slices["D"] = d.rstrip() + "\n\n<!-- 自动压缩 -->\n" + compact + "\n"
    slices["B"] = new_b

    preamble = cur[:marks[0][0]].rstrip()
    rebuilt = "\n\n".join(slices[k] for k in keys)
    write(cur_path, (preamble + "\n\n" if preamble else "") + rebuilt + "\n")
    print("✅ 第 %d 章摘要已并入 CURRENT.md" % n)
    print("   B 区保留：%s" % "、".join(re.findall(r"第 (\d+) 章", "\n".join(keep))))
    if moved:
        print("   已压缩进 D 区：%s" % "、".join(re.findall(r"第 (\d+) 章", "\n".join(moved))))
    if tail:
        print("   已更新「紧邻上文结尾」（%d 字）" % len(tail))
    else:
        print("   🟡 未找到正文 ch%04d.md，未更新结尾片段" % n)


# ---------------------------------------------------------------- check
def cmd_check(args):
    root = get_root(args)
    issues = []   # (级别, 文本)

    def add(lv, msg):
        issues.append((lv, msg))

    summ = list_summaries(root)
    if not summ and not args.fore:
        add("🟡", "尚未生成任何章节摘要，跳过章节类检查")

    # 1. 摘要缺失
    if not args.fore:
        ch_dir = P(root, "03-chapters")
        if os.path.isdir(ch_dir):
            have = set()
            for fn in os.listdir(ch_dir):
                if fn.endswith(".md") and not fn.startswith("_"):
                    m = re.search(r"(\d{3,4})", fn)
                    if m:
                        have.add(int(m.group(1)))
            missing = sorted(have - {s[0] for s in summ})
            if missing:
                add("🔴", "正文已写但无摘要：第 %s 章" % "、".join(map(str, missing)))

    # 2. 字数 / 摘要长度 / 注水
    for num, path, f in summ:
        w = re.sub(r"\D", "", f.get("字数", "")) 
        if w:
            w = int(w)
            if not (args.min <= w <= args.max):
                add("🟡", "第 %d 章字数 %d，超出 [%d, %d] 区间" % (num, w, args.min, args.max))
        if f.get("信息增量", "").strip() in ("无", ""):
            add("🟡", "第 %d 章「信息增量」为空 → 注水风险" % num)
        body = "\n".join(l for l in read(path).splitlines() if not l.strip().startswith(("```", "#", ">")))
        if len(body.strip()) > 300:
            add("🟡", "第 %d 章摘要 %d 字，超过 300 字上限（在写复述，不是索引）" % (num, len(body.strip())))

    # 3. 时间单调
    last_t, last_n = None, None
    for num, path, f in summ:
        t = time_key(f.get("时间", ""))
        if t is None:
            add("🟡", "第 %d 章时间字段缺失或不可解析：%r" % (num, f.get("时间", "")))
            continue
        back = ("回溯" in f.get("时间", "")) or ("回溯" in f.get("核心事件", ""))
        if last_t is not None and t < last_t and not back:
            add("🔴", "时间倒退：第 %d 章(D+%d) → 第 %d 章(D+%d)" % (last_n, last_t, num, t))
        last_t, last_n = (last_t if back else t), num

    # 4. 人物复活
    dead = {}   # code -> 死亡章号
    for num, path, f in summ:
        for m in re.finditer(r"(C\d{3})[^\n]*?死亡", f.get("人物状态变更", "")):
            dead.setdefault(m.group(1), num)
    for num, path, f in summ:
        for c in CODE_RE.findall(f.get("出场人物", "")):
            if c in dead and num > dead[c]:
                add("🔴", "人物复活：%s 在第 %d 章已死亡，第 %d 章又出场" % (c, dead[c], num))

    # 5. 伏笔健康度
    _, rows = find_table(read(P(root, "02-plot", "09-伏笔台账.md")), "编号")
    if not rows:
        add("🟡", "伏笔台账为空或表头不含「编号」列")
    else:
        cur_max = summ[-1][0] if summ else 0
        open_n, overdue, stale, no_plan = 0, [], [], []
        for r in rows:
            if len(r) < 8:
                continue
            code, content, strengthen, plan, status = (
                clean(r[0]), clean(r[1]), clean(r[4]), clean(r[5]), clean(r[7]))
            if status in ("待回收", "已强化"):
                open_n += 1
            pm = CH_RE.search(plan)
            if not pm and status != "已回收":
                no_plan.append(code)
            elif pm and status != "已回收" and int(pm.group(1)) < cur_max:
                overdue.append("%s(计划第%s章)" % (code, pm.group(1)))
            if status == "已强化":
                st = [int(x) for x in CH_RE.findall(strengthen)]
                if st and cur_max - max(st) > 50:
                    stale.append(code)
        if open_n > 8:
            add("🟡", "待回收伏笔 %d 个，超过 8 个预警线" % open_n)
        if overdue:
            add("🔴", "伏笔超期未回收：%s" % "、".join(overdue))
        if stale:
            add("🔴", "伏笔超 50 章未强化（读者会忘）：%s" % "、".join(stale))
        if no_plan:
            add("🟡", "伏笔无回收计划章号：%s" % "、".join(no_plan))
        print("伏笔健康度：开启中 %d ｜ 超期 %d ｜ 失养 %d ｜ 无计划 %d" % (open_n, len(overdue), len(stale), len(no_plan)))

    if args.fore:
        return

    # 6. 人物卡与摘要的出场一致性（连续 15 章未出场提醒）
    d = P(root, "01-story-bible", "characters")
    if os.path.isdir(d) and summ:
        cur_max = summ[-1][0]
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".md") or fn.startswith("_"):
                continue
            code = fn[:4]
            appeared = [s[0] for s in summ if code in s[2].get("出场人物", "")]
            if appeared and cur_max - max(appeared) > 15:
                add("🟡", "%s（%s）已连续 %d 章未出场 → 收束或删除" % (code, fn[5:-3], cur_max - max(appeared)))

    # 7. 输出
    if not issues:
        print("✅ 一致性检查通过，无问题")
        return
    print("\n一致性检查结果：")
    for lv in ("🔴", "🟡"):
        for l, m in issues:
            if l == lv:
                print("  %s %s" % (l, m))
    red = sum(1 for l, _ in issues if l == "🔴")
    print("\n🔴 必改 %d 条 ｜ 🟡 建议 %d 条" % (red, len(issues) - red))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="长篇上下文工程工具（纯标准库）")
    ap.add_argument("--root", default=None, help="项目根目录，默认为 tools 的上级目录")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("pack", help="装配本章上下文包")
    p1.add_argument("--chapter", type=int, required=True)
    p1.add_argument("--chars", default="", help="本章出场人物编号，逗号分隔，如 C001,C003")
    p1.add_argument("--budget", type=int, default=4500)
    p1.add_argument("--window", type=int, default=30, help="伏笔计划回收章在本章之后多少章内才载入")
    p1.add_argument("--timeline", type=int, default=8, help="载入时间线最近多少行")
    p1.add_argument("--terms", type=int, default=40, help="名词表最多载入多少行")
    p1.add_argument("--ref", default="", help="显式载入借鉴库条目，如 R01,R02；默认不载（隔离）")
    p1.add_argument("--out", default=None)
    p1.set_defaults(func=cmd_pack)

    p2 = sub.add_parser("roll", help="把本章摘要并入滚动上下文")
    p2.add_argument("--chapter", type=int, required=True)
    p2.set_defaults(func=cmd_roll)

    p3 = sub.add_parser("check", help="一致性硬检查")
    p3.add_argument("--fore", action="store_true", help="只检查伏笔健康度")
    p3.add_argument("--min", type=int, default=1800)
    p3.add_argument("--max", type=int, default=3000)
    p3.set_defaults(func=cmd_check)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
