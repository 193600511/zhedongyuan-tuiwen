# -*- coding: utf-8 -*-
"""为 assets/examples/ 下每篇历史代表稿生成结构摘要，汇总成 references/style-cases.md。
摘要只看"能直接用的排版指纹"：色值/字号/行距/圆角、段落粒度、小标题原文、开篇结尾原文、落款格式。
"""
import os, re, io, collections, sys

EX = r'C:\Users\Administrator\.workbuddy\skills\zhedongyuan-tuiwen\assets\examples'
OUT = r'C:\Users\Administrator\.workbuddy\skills\zhedongyuan-tuiwen\references\style-cases.md'


def text_of(t):
    t = re.sub(r'<!--.*?-->', '', t, flags=re.S)
    t = re.sub(r'<(script|style)\b.*?</\1>', '', t, flags=re.S | re.I)
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = re.sub(r'</(p|section|div|h[1-6]|li|tr|table)>', '\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    t = t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    lines = [x.strip() for x in t.split('\n')]
    return [x for x in lines if x]


def analyze(path):
    raw = io.open(path, encoding='utf-8').read()
    body = raw[raw.find('<div class="zjdf-ref">'):]
    body = re.split(r'预览时标签不可点', body)[0]
    txt = text_of(body)
    joined = ''.join(txt)
    # 有的稿子整篇塞在一个 section 里（无 </p>），按句号粗切成段以还原"段均字数"
    pills = []
    for x in txt:
        if len(x) <= 260:
            pills.append(x)
        else:
            buf = ''
            for s in re.split(r'(?<=。)', x):
                buf += s
                if len(buf) >= 120:
                    pills.append(buf)
                    buf = ''
            if buf:
                pills.append(buf)
    colors = collections.Counter(re.findall(r'#[0-9a-fA-F]{3,8}', body))
    sizes = collections.Counter(re.findall(r'font-size\s*:\s*(\d+(?:\.\d+)?(?:px|em|rem))', body))
    lh = collections.Counter(re.findall(r'line-height\s*:\s*([\d.]+)', body))
    rad = collections.Counter(re.findall(r'border-radius\s*:\s*([^;"]+)', body))
    align = collections.Counter(re.findall(r'text-align\s*:\s*(\w+)', body))
    indent = len(re.findall(r'text-indent', body))
    # 图片占位与分布
    imgs = re.findall(r'<!--IMG([^>]*)-->', body)
    dash = len(re.findall(r'border[^;"]*(?:dashed|dotted)', body))
    blockbg = len(re.findall(r'background(?:-color)?\s*:\s*#(?!fff)', body))
    # 段落
    paras = [x for x in pills if len(x) >= 20]
    if len(paras) <= 1 and len(joined) > 200:
        # 极短句排版（一图一句）：按 60 字一块估算段均，避免出现 0 段
        paras = [joined[i:i + 60] for i in range(0, len(joined), 60)]
    plen = [len(x) for x in paras]
    avg_p = round(sum(plen) / len(plen)) if plen else 0
    # 小标题：短行 + 含粗体/较大字号
    heads = []
    for m in re.finditer(r'<(p|section|div)\b[^>]*>(?:(?!</?\1).){0,400}?</\1>', body, re.S):
        seg = m.group(0)
        st = re.search(r'style="([^"]*)"', seg)
        if not st:
            continue
        s = st.group(1)
        fs = re.search(r'font-size\s*:\s*(\d+)', s)
        bold = ('font-weight:bold' in s.replace(' ', '') or 'font-weight:700' in s.replace(' ', '')
                or '<strong' in seg)
        big = bool(fs) and int(fs.group(1)) >= 18
        if (big or (fs and int(fs.group(1)) >= 17 and bold)):
            h = ''.join(text_of(seg)).strip()
            if (2 <= len(h) <= 22 and not re.search(r'[，。；！？]', h)
                    and h not in heads and not h.endswith(('的', '了'))):
                heads.append(h)
        if len(heads) >= 14:
            break
    # 落款
    tail = txt[-8:]
    return dict(raw=raw, chars=len(joined), paras=len(paras), avg_p=avg_p, imgs=len(imgs),
                dash=dash, blockbg=blockbg,
                colors=colors, sizes=sizes, lh=lh, rad=rad, align=align, indent=indent,
                heads=heads, open=''.join(txt[:4])[:160], close=''.join(tail)[-200:], txt=txt)


def header_meta(raw, fname=''):
    def g1(pat):
        m = re.search(pat, raw)
        return m.group(1).strip() if m else ''
    g = g1(r'题材：(.+)')
    ti = g1(r'原标题：(.+)')
    lp = g1(r'可学点：(.+)')
    src = g1(r'来源文件：(.+)')
    if not ti:  # 兜底：用档案文件名
        ti = re.sub(r'^\d+-[^-]+-', '', re.sub(r'\.html$', '', fname))
    return g, ti, lp, src


def fmt_counter(c, n=6, unit=''):
    return '、'.join('%s%s×%d' % (k, unit, v) for k, v in c.most_common(n))


def main():
    files = sorted(f for f in os.listdir(EX) if f.endswith('.html'))
    out = ['# 历史代表稿 · 结构速查（写稿/改稿前先看这份，不要先读 HTML 原文）', '',
           '> 这里是从 10 篇院内历史稿里榨出的**排版指纹**：色值、字号、行距、小标题命名、开篇结尾语气。',
           '> 需要看完整 inline style 时，才去 `assets/examples/` 打开对应 `.html`（体积大，别整篇读，用 grep 定位）。', '',
           '## 速查表', '',
           '| # | 题材 | 标题 | 字数 | 段数 | 段均字 | 图数 | 虚线框 |', '|---|---|---|---|---|---|---|---|']
    data = {}
    for i, f in enumerate(files, 1):
        d = analyze(os.path.join(EX, f))
        g, ti, lp, src = header_meta(d['raw'], f)
        data[f] = (d, g, ti, lp, src)
        out.append('| %d | %s | %s | %d | %d | %d | %d | %d |' % (
            i, g, ti, d['chars'], d['paras'], d['avg_p'], d['imgs'], d['dash']))
    out.append('')

    # 汇总型规律
    allcolors = collections.Counter()
    allsizes = collections.Counter()
    allalign = collections.Counter()
    for f, (d, g, ti, lp, src) in data.items():
        allcolors.update(d['colors'])
        allsizes.update(d['sizes'])
        allalign.update(d['align'])
    out += ['## 全院历史稿共性（10 篇统计）', '',
            '- 高频色值：' + fmt_counter(allcolors, 10),
            '- 高频字号：' + fmt_counter(allsizes, 8),
            '- 对齐分布：' + fmt_counter(allalign, 4),
            '']

    out += ['## 反例登记（不许拿"历史从不用 X"当论据）', '',
            '- **虚线框在院内确实出现过**：`01-风景时节-又被校园美到了` 有 6 处 `border:1px dashed #2aa593`（青色虚线包在照片外）；'
            '`04-招生章程` 有 33 处虚线（表格分隔，公文类常规）。',
            '- 所以 2026-11-08 定的「风景/时节类不套虚线框」是**用户偏好**，不是历史事实。出稿按用户口径（不用虚线、头图不描边），'
            '但点评或解释时只能说"按院里现在的口径不用虚线"，**不得声称"院内从来不用虚线"**。',
            '- `04-招生章程` 的虚线属公文表格分隔线，不受风景稿口径约束。', '']

    out += ['## 逐篇指纹', '']
    for f, (d, g, ti, lp, src) in data.items():
        out += ['### %s ｜ %s' % (ti, g), '',
                '- 档案：`assets/examples/%s`（源：%s）' % (f, src),
                '- 体量：%d 字 / %d 段 / 段均 %d 字 / %d 图' % (d['chars'], d['paras'], d['avg_p'], d['imgs']),
                '- 色值：' + fmt_counter(d['colors'], 8),
                '- 字号：' + fmt_counter(d['sizes'], 8),
                '- 行距：' + (fmt_counter(d['lh'], 4) or '未显式设置'),
                '- 圆角：' + (fmt_counter(d['rad'], 4) or '无'),
                '- 虚线/点线框：%d 处；非白底色块：%d 处' % (d['dash'], d['blockbg']),
                '- text-indent 出现次数：%d' % d['indent'],
                '- 可学点：' + lp,
                '',
                '**小标题原文（照这个语气起）**：' + (
                    ('（本篇通篇同字号、无标题层级，以下为短行样例）' if len(d['heads']) >= 6 else '')
                    + ('｜ '.join(d['heads']) if d['heads'] else '（本篇无显式小标题）')),
                '',
                '**开篇**：' + d['open'],
                '',
                '**收尾/落款**：' + d['close'],
                '']
    io.open(OUT, 'w', encoding='utf-8').write('\n'.join(out))
    print('[OK]', OUT, round(len('\n'.join(out).encode()) / 1024, 1), 'KB')
    print('共性色值 top:', allcolors.most_common(6))
    print('共性字号 top:', allsizes.most_common(6))


if __name__ == '__main__':
    main()
