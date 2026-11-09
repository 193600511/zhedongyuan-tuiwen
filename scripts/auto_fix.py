# -*- coding: utf-8 -*-
"""auto_fix.py —— 浙东院推文「自动按要求优化」：读入文章，按学院规范自动修，修完自动复检。

用法：
  python auto_fix.py <article.html>                    # 修复并写回 <stem>-fixed.html，打印前后对比
  python auto_fix.py <article.html> --out out.html     # 指定输出路径
  python auto_fix.py <article.html> --flatten          # 深度模式：模板降级（剥背景图/旋转/弹性布局），保住粘贴不散架
  python auto_fix.py <article.html> --strip-head       # 删除开头超大标题装饰块（默认关，防误删）
  python auto_fix.py <article.html> --json             # 机器可读修复清单

自动修什么（全部可客观判定，不碰文风）：
  1 正文段字号归一 17px（含未声明的补声明——96 模板靠继承，粘贴会被降级）
  2 行距归一 1.75（em/倍数 >1.8 的都拉回）
  3 字间距非 0 → 0
  4 首行缩进 → 2em（缺失补、非 2em 纠正）
  5 成段右对齐 → 两端对齐；未声明对齐 → 两端对齐
  6 纯黑 #000 文字 → #3e3e3e
  7 图片容器上下留白 8px（缺失补）；图片补块级显示 + 最大宽度 100%
  8 落款：二审「责 编」误写 → 「责 审」；缺失三审行按标准补插（来源/编辑姓名不臆造，只在报告提示）
  9 剥强制优先级样式；删编辑器残留标记
 10 --flatten：剥背景图（留底色）、剥旋转、弹性布局降级为块级
设计原则：与 check_article.py 同口径，修完保证体检零致命；只动样式与结构事实，不改一个字的文案。
"""
import io, json, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_article as checker  # 复用体检器做修复后验收

CN = re.compile(r'[\u4e00-\u9fa5]')
TAG_RE = re.compile(r'<(/?)(section|p|span|div|strong|em|b|i)\b([^>]*?)(/?)>', re.I)
STYLE_RE = re.compile(r'style\s*=\s*"([^"]*)"', re.I)
CLASS_RE = re.compile(r'\s*class\s*=\s*"[^"]*"\s*', re.I)
IMG_RE = re.compile(r'<img\b[^>]*>', re.I)

FLATTEN = [False]  # 模板降级开关（fix_style 内读取）

TAIL_N = 8000  # 落款检测窗口：窗口太短会把「落款后面还有空行和底部关注图」的稿子误判成缺行
SIGN_ROW_STYLE = 'font-size:12px;color:#888888;line-height:1.75;letter-spacing:0;'
SIGN_FIX = [
    # (匹配, 替换) —— 二审误写成责编
    (re.compile(r'责\s*编(\s|&nbsp;)*（\s*二\s*审\s*）'), '责 审（二审）'),
    (re.compile(r'责\s*编(\s|&nbsp;)*\(\s*二\s*审\s*\)'), '责 审（二审）'),
]


def get_style(attrs):
    m = STYLE_RE.search(attrs)
    return m.group(1) if m else None


def set_style(attrs, new_style):
    if STYLE_RE.search(attrs):
        return STYLE_RE.sub(lambda _: 'style="%s"' % new_style, attrs, count=1)
    return attrs.rstrip() + ' style="%s"' % new_style if attrs else ' style="%s"' % new_style


def parse_style(s):
    d = {}
    for part in re.split(r';', s or ''):
        if ':' in part:
            k, v = part.split(':', 1)
            d[k.strip().lower()] = v.strip()
    return d


def style_to_str(d):
    return ';'.join('%s:%s' % (k, v) for k, v in d.items() if v)


def strip_important(s):
    return re.sub(r'\s*!important', '', s, flags=re.I)


def fix_style(style, kind, cn, changes):
    """对单个元素的 style 做归一化。
    kind: block_leaf(块级正文叶子) / inline_leaf(行内文字) / imgbox(纯图容器) / container(其他容器)"""
    if style is None:
        style = ''
    st = parse_style(strip_important(style))
    is_para = kind == 'block_leaf'
    # 字号可以安全归一的两类：正文叶子 + 文字承载容器（字号由容器继承给叶子）
    fs_scope = kind in ('block_leaf', 'container') and cn >= 20
    has_text = kind in ('block_leaf', 'inline_leaf', 'container')

    # 1 字号：18(金句)/19-32(标题)/12(图注) 不动
    if fs_scope:
        fs = st.get('font-size')
        m = re.match(r'([\d.]+)px', fs or '')
        if fs and m and 12 <= float(m.group(1)) < 18 and abs(float(m.group(1)) - 17) > 0.5:
            st['font-size'] = '17px'; changes['正文段字号→17px'] += 1
        elif not fs and is_para:
            st['font-size'] = '17px'; changes['正文段补字号17px'] += 1

    # 2 行距（缺失补 1.75；em/倍数 >1.8 拉回 1.75）
    lh = st.get('line-height')
    if is_para and not lh:
        st['line-height'] = '1.75'; changes['正文段补行距1.75'] += 1
    elif has_text and lh:
        m = re.match(r'([\d.]+)\s*(em)?', lh)
        if m and float(m.group(1)) > 1.8:
            st['line-height'] = '1.75'; changes['行距→1.75'] += 1

    # 3 字距
    ls = st.get('letter-spacing')
    if has_text and ls:
        mv = re.match(r'-?[\d.]+', ls)
        if mv and abs(float(mv.group(0))) > 0.05:
            st['letter-spacing'] = '0'; changes['字距→0'] += 1

    # 4 缩进（块级才有效）
    if is_para:
        ind = st.get('text-indent')
        if not ind:
            st['text-indent'] = '2em'; changes['补缩进2em'] += 1
        else:
            mi = re.match(r'([\d.]+)em', ind)
            if mi and abs(float(mi.group(1)) - 2) > 0.05:
                st['text-indent'] = '2em'; changes['缩进→2em'] += 1

    # 5 对齐：成段文字一律两端对齐（叶子 + 文字承载容器都归一；容器声明会兜底继承给子级）
    if fs_scope:
        al = st.get('text-align')
        if al == 'right':
            st['text-align'] = 'justify'; changes['右对齐→两端对齐'] += 1
        elif al != 'justify':
            st['text-align'] = 'justify'; changes['对齐→两端对齐'] += 1

    # 6 纯黑
    col = st.get('color')
    if has_text and col and re.fullmatch(r'#000000?|rgb\(0,\s*0,\s*0\)|black', col.strip(), re.I):
        st['color'] = '#3e3e3e'; changes['纯黑→#3e3e3e'] += 1

    # 6.5 font-family（规范禁指定字体）
    if 'font-family' in st:
        st.pop('font-family'); changes['删指定字体'] += 1

    # 7 纯图容器边距
    if kind == 'imgbox' and 'margin' not in st:
        st['margin'] = '8px 0'; changes['图片容器补上下留白8px'] += 1

    # 10 模板降级
    if FLATTEN[0]:
        for k in list(st):
            v = st[k]
            if k.startswith('background') and 'image' in k:
                st.pop(k, None); changes['剥背景图'] += 1
            elif k.endswith('transform') and 'rotate' in v:
                st.pop(k); changes['去旋转'] += 1
            elif k == 'display' and v == 'flex':
                st[k] = 'block'; changes['弹性布局→块级'] += 1

    return style_to_str(st)


def collect_elements(html):
    """栈匹配 section/p/span/div 的开闭，返回 [(name, open_s, open_e, close_s, attrs)]"""
    stack, out = [], []
    for m in TAG_RE.finditer(html):
        closing, name, attrs, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    nm, s, e, at = stack.pop(i)
                    out.append((nm, s, e, m.start(), at))
                    break
        elif not selfclose:
            stack.append((name, m.start(), m.end(), attrs))
    return out


def fix_signature(html, changes, notes):
    """落款修正：二审误写纠正 + 缺失三审行补插（来源/编辑姓名不臆造）。"""
    for pat, rep in SIGN_FIX:
        n = len(pat.findall(html))
        if n:
            html = pat.sub(rep, html)
            changes['落款二审纠字'] += n
    tail = html[-TAIL_N:]
    plain = re.sub(r'<[^>]+>', '', tail)
    need = [('二审', r'责\s*审.{0,6}二\s*审|责\s*审（二审）'), ('三审', r'终\s*[核审].{0,6}三\s*审')]
    # 找一审行 </p> 位置作为插队点
    m1 = re.search(r'<p\b[^>]*>[^<]*责\s*编[^<]*一\s*审[^<]*</p>', tail, re.I)
    if m1 and not re.search(need[0][1], plain):
        row = '\n    <p style="%s">责 审（二审） | 吴昕灿</p>' % SIGN_ROW_STYLE
        pos = len(html) - len(tail) + m1.end()
        html = html[:pos] + row + html[pos:]
        changes['补落款二审行'] += 1
        plain = plain  # 已补
    if not re.search(need[1][1], re.sub(r'<[^>]+>', '', html[-TAIL_N:])):
        # 找二审行（可能是刚补的）
        m2 = re.search(r'<p\b[^>]*>[^<]*(?:责\s*审|责\s*编)[^<]*二\s*审[^<]*</p>', html[-TAIL_N:], re.I)
        if m2:
            row = '\n    <p style="%s">终 核（三审） | 武德力</p>' % SIGN_ROW_STYLE
            pos = len(html) - TAIL_N + m2.end()
            html = html[:pos] + row + html[pos:]
            changes['补落款三审行'] += 1
    if not re.search(r'来\s*源', plain):
        notes.append('落款缺「来 源」行——不知道供稿部门，未臆造，请补')
    if not re.search(r'编\s*辑|发\s*布', plain):
        notes.append('落款缺「编 辑」行——不知道撰稿人姓名，未臆造，请补')
    return html


def strip_head_deco(html, changes):
    """删除开头（前 30%）font-size≥33px 的整个元素块。"""
    els = collect_elements(html)
    cut = len(html) * 0.30
    spans = []
    for nm, s, e, cs, attrs in els:
        if s > cut:
            continue
        st = get_style(attrs) or ''
        m = re.search(r'font-size\s*:\s*(3[3-9]|[4-9]\d)\s*px', st, re.I)
        if m:
            spans.append((s, cs))
    for s, cs in sorted(spans, reverse=True):
        html = html[:s] + html[cs:]
        changes['删开头超大标题块'] += 1
    return html


def cleanup(html, changes):
    n = len(CLASS_RE.findall(html))
    if n:
        html = CLASS_RE.sub(' ', html)
        changes['删编辑器残留标记'] += n
    return html


def fix_imgs(html, changes):
    def img_fix(m):
        tag = m.group(0)
        deco = bool(re.search(r'data-isicon', tag, re.I))
        orig = get_style(tag)
        st = orig or ''
        if FLATTEN[0] and st and 'rotate' in st:
            kept = []
            for p in st.split(';'):
                key = p.split(':', 1)[0].strip().lower()
                if key.endswith('transform') and 'rotate' in p:
                    changes['去旋转'] += 1
                    continue
                kept.append(p)
            st = ';'.join(kept)
        add = ''
        if not deco:
            if 'display' not in st:
                add += 'display:block;'
            if 'max-width' not in st:
                add += 'max-width:100%;'
        if add:
            st = (st.rstrip(';') + ';' + add).lstrip(';')
            changes['图片补块级显示与最大宽度'] += 1
        if st == (orig or ''):
            return tag
        if 'style="' in tag:
            return re.sub(r'(\sstyle=")[^"]*(")', lambda mm: mm.group(1) + st + mm.group(2), tag, count=1)
        return tag.replace('<img', '<img style="%s"' % st, 1)
    return IMG_RE.sub(img_fix, html)


def auto_fix(path, out_path, flatten=False, strip_head=False, as_json=False):
    raw = io.open(path, encoding='utf-8', errors='ignore').read()
    changes = {}
    notes = []
    FLATTEN[0] = flatten
    for k in ['正文段字号→17px', '正文段补字号17px', '正文段补行距1.75', '行距→1.75', '字距→0', '补缩进2em', '缩进→2em',
              '右对齐→两端对齐', '对齐→两端对齐', '纯黑→#3e3e3e', '删指定字体', '图片容器补上下留白8px',
              '图片补块级显示与最大宽度', '剥背景图', '去旋转', '弹性布局→块级', '落款二审纠字',
              '补落款二审行', '补落款三审行', '删编辑器残留标记', '剥强制样式', '删开头超大标题块']:
        changes[k] = 0

    # 1 落款（文本层）
    html = fix_signature(raw, changes, notes)

    # 2 元素级 style 归一（收集替换点，从后往前应用）
    edits = []
    INLINE = {'span', 'b', 'em', 'strong', 'i'}
    BLOCK = {'p', 'section', 'div'}
    for nm, s, e, cs, attrs in collect_elements(html):
        inner = html[e:cs]
        text = re.sub(r'<[^>]+>', '', inner)
        cn = len(CN.findall(text))
        style = get_style(attrs)
        if style and '!important' in style.lower():
            changes['剥强制样式'] += len(re.findall(r'!important', style, re.I))
        # 元素分类
        has_block_child = bool(re.search(r'<(p|section|div)\b', inner, re.I))
        if nm in INLINE:
            kind = 'inline_leaf'
        elif nm in BLOCK and not has_block_child:
            kind = 'block_leaf' if cn >= 20 else ('imgbox' if '<img' in inner.lower() else 'container')
        else:
            kind = 'container'
        new_style = fix_style(style, kind, cn, changes)
        if new_style != style:
            new_attrs = set_style(attrs, new_style)
            edits.append((s, e, '<%s%s>' % (nm, new_attrs)))
    for s, e, rep in sorted(edits, reverse=True):
        html = html[:s] + rep + html[e:]

    # 3 img 自身样式
    html = fix_imgs(html, changes)

    # 4 模板降级兜底：background-image 写在 style 之外的情况已由 fix_style 覆盖
    # 5 清理
    html = cleanup(html, changes)
    if strip_head:
        html = strip_head_deco(html, changes)

    # 6 写出
    io.open(out_path, 'w', encoding='utf-8').write(html)

    # 7 复检（临时落盘，直接调用体检器函数）
    def run_check(txt):
        import types
        tmp = tempfile.NamedTemporaryFile('w', suffix='.html', delete=False, encoding='utf-8')
        tmp.write(txt); tmp.close()
        try:
            r = checker.check(tmp.name)
        finally:
            os.unlink(tmp.name)
        return r

    before = run_check(raw)
    after = run_check(html)

    # 评分对比（走子进程拿 --brief，保持口径与命令行一致）
    def brief(txt):
        tmp = tempfile.NamedTemporaryFile('w', suffix='.html', delete=False, encoding='utf-8')
        tmp.write(txt); tmp.close()
        try:
            r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'score_article.py'), tmp.name, '--brief'],
                               capture_output=True, timeout=120)
            return r.stdout.decode('utf-8', 'ignore').strip().splitlines()[-1] if r.stdout else '?'
        finally:
            os.unlink(tmp.name)
    score_before = brief(raw)
    score_after = brief(html)

    if as_json:
        print(json.dumps({'file': out_path, 'changes': changes, 'notes': notes,
                          'check_before': {'fatal': len(before['fatal']), 'warn': len(before['warn'])},
                          'check_after': {'fatal': len(after['fatal']), 'warn': len(after['warn'])},
                          'score_before': score_before, 'score_after': score_after},
                         ensure_ascii=False, indent=2))
        return

    print('=' * 60)
    print('自动优化完成 →', out_path)
    print('=' * 60)
    print('修改清单：')
    for k, v in changes.items():
        if v:
            print('  · %s ×%d' % (k, v))
    if not any(changes.values()):
        print('  （无可修项，文章已合规）')
    for nt in notes:
        print('  ⚠ ' + nt)
    print('-' * 60)
    print('体检：修复前 致命%d/建议%d → 修复后 致命%d/建议%d'
          % (len(before['fatal']), len(before['warn']), len(after['fatal']), len(after['warn'])))
    print('评分：%s  →  %s' % (score_before, score_after))


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__); sys.exit(0)
    path = args[0]
    out = None; flatten = False; strip_head = False; as_json = False
    if '--out' in args:
        out = args[args.index('--out') + 1]
    flatten = '--flatten' in args
    strip_head = '--strip-head' in args
    as_json = '--json' in args
    if not out:
        stem, ext = os.path.splitext(path)
        out = stem + '-fixed' + (ext or '.html')
    auto_fix(path, out, flatten, strip_head, as_json)


if __name__ == '__main__':
    main()
