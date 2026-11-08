# -*- coding: utf-8 -*-
"""
浙东院推文排版合规检测器
用法:
  python check_article.py <article.html> [--json]
规范依据: 《采编部教程》+ 342 篇历史推文实证（详见 references/standards.md）
退出码: 0=通过(无致命)  1=存在致命问题
"""
import io, re, sys, json, collections
from html.parser import HTMLParser

LINE_HEIGHT = '1.75'
ACCEPT_FS = {'12', '13', '14', '15', '16', '17', '18',          # 正文/小注/图注
             '20', '22', '24', '26', '28', '32'}                # 标题类
REVIEW = {'一审': '孙舒', '二审': '吴昕灿', '三审': '武德力'}
MAX_IMAGES = 10
CN = re.compile(r'[\u4e00-\u9fa5]')


class StyleTextCollector(HTMLParser):
    """收集每个带 style 的元素的 (style, 自身直属文本)"""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.items = []          # (style, text) 仅含中文文本的元素
        self.all_items = []      # (style, text) 全部带 style 的元素
        self.text_buf = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.stack.append((tag, d.get('style', '') or '', len(self.text_buf)))

    def handle_endtag(self, tag):
        if not self.stack:
            return
        t, style, mark = self.stack.pop()
        text = ''.join(self.text_buf[mark:])
        if style:
            self.all_items.append((style, text))
            if CN.search(text):
                self.items.append((style, text))

    def handle_data(self, data):
        self.text_buf.append(data)


def strip_noise(s):
    s = re.sub(r'<script.*?</script>', '', s, flags=re.S | re.I)
    s = re.sub(r'<style.*?</style>', '', s, flags=re.S | re.I)
    s = re.sub(r'<!--.*?-->', '', s, flags=re.S)
    return s


def visible_text(s):
    t = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'&nbsp;?', ' ', t)


def check(path):
    raw = io.open(path, encoding='utf-8', errors='ignore').read()
    s = strip_noise(raw)
    fatal, warn, info = [], [], []

    # ---------- 解析元素 ----------
    p = StyleTextCollector()
    try:
        p.feed(s)
        p.close()
    except Exception as e:
        fatal.append(f'HTML 解析失败: {e}')
        return {'file': path, 'ok': False, 'fatal': fatal, 'warn': warn, 'info': info,
                'stats': {'images': 0, 'body_font_size': None, 'paragraphs': 0}}

    # ---------- 1. 正文段落（成段中文 ≥20 字、有明确字号且非 12px；父子嵌套去重） ----------
    cands = []
    for style, text in p.items:
        fs_m = re.search(r'font-size\s*:\s*([\d.]+)\s*px', style)
        if len(CN.findall(text)) >= 20 and fs_m and fs_m.group(1) != '12':
            cands.append((re.sub(r'\s+', '', text), style))
    # 去重：父容器文本包含子段文本，删除包含别人的父级，保留叶子段
    paras = []
    for t_a, s_a in cands:
        contains_other = any(t_a != t_b and t_b in t_a for t_b, _ in cands)
        if not contains_other:
            paras.append(s_a)
    body_fs = None
    fs_of_para = []
    for st in paras:
        m = re.search(r'font-size\s*:\s*([\d.]+)\s*px', st)
        if m:
            fs_of_para.append(m.group(1))
    if fs_of_para:
        body_fs = collections.Counter(fs_of_para).most_common(1)[0][0]
        if body_fs != '17':
            fatal.append(f'正文字号主流为 {body_fs}px，规范要求 17px')
    else:
        fs_all = [m.group(1) for st, tx in p.items if len(CN.findall(tx)) >= 8
                  for m in [re.search(r'font-size\s*:\s*([\d.]+)\s*px', st)] if m]
        if not fs_all:
            info.append('未检测到成段文字（模板占位符未填充或纯图推文）')
        else:
            info.append('未解析到 ≥20 字的正文段落，改按较长文本元素统计')
            body_fs = collections.Counter(fs_all).most_common(1)[0][0]
            if body_fs != '17':
                fatal.append(f'全篇主流字号 {body_fs}px，规范要求正文 17px')
    bad_fs = sorted({m.group(1) for st, tx in p.items
                     for m in [re.search(r'font-size\s*:\s*([\d.]+)\s*px', st)]
                     if m and m.group(1) not in ACCEPT_FS}, key=float)
    if bad_fs:
        warn.append('出现规范外字号: ' + ', '.join(k + 'px' for k in bad_fs) +
                    '（合法: 正文 17 / 小注 12–15 / 金句 18 / 标题 20–32px）')

    # ---------- 2. 字体 ----------
    if re.search(r'font-family', s, re.I):
        fatal.append('出现 font-family（规范要求系统默认字体，不得指定字体）')

    # ---------- 3. 行距 / 字距 / 缩进 / 对齐 ----------
    n = len(paras)
    if n:
        bad_lh = sum(1 for st in paras if not re.search(r'line-height\s*:\s*1\.75', st))
        bad_ls = sum(1 for st in paras if re.search(r'letter-spacing\s*:\s*([1-9]|0\.[1-9])', st))
        # 缩进/对齐只查 17px 正文段（金句 18px、小标题等强调块本就不缩进）
        body_paras = [st for st in paras if re.search(r'font-size\s*:\s*17\s*px', st)]
        no_ind = sum(1 for st in body_paras if 'text-indent' not in st)
        no_jus = sum(1 for st in body_paras if 'justify' not in st)
        if bad_lh: warn.append(f'{bad_lh}/{n} 个正文段落行距非 1.75')
        if bad_ls: warn.append(f'{bad_ls}/{n} 个正文段落字间距非 0')
        if no_ind: warn.append(f'{no_ind}/{len(body_paras)} 个 17px 正文段缺首行缩进 text-indent:2em')
        if no_jus: warn.append(f'{no_jus}/{len(body_paras)} 个 17px 正文段未两端对齐 text-align:justify')
    else:
        info.append('未解析到典型正文段落（纯图推文可忽略行距/缩进检查）')

    # ---------- 4. 落款 ----------
    t = visible_text(s)
    for label, pat in [('来 源', r'来\s*源'), ('编 辑', r'编\s*辑'),
                       ('责 编（一审）', r'责\s*编.{0,4}一\s*审'),
                       ('责 审（二审）', r'责\s*审.{0,4}二\s*审'),
                       ('终 核（三审）', r'终\s*[核审].{0,4}三\s*审')]:
        if not re.search(pat, t):
            fatal.append(f'落款缺少「{label}」行')
    tail = t[-2000:]
    if '吴昕灿' not in tail and re.search(r'责\s*审.{0,4}二\s*审', tail):
        warn.append('二审姓名未见「吴昕灿」（当前固定口径）')
    if '武德力' not in tail and re.search(r'终\s*[核审].{0,4}三\s*审', tail):
        warn.append('三审姓名未见「武德力」（当前固定口径）')
    if re.search(r'责\s*编.{0,4}一\s*审', tail) and not re.search(r'孙舒|于紫梦|衎', tail):
        warn.append('一审姓名未见「孙舒」（当前固定口径）')

    # ---------- 5. 图片（与评分器 v1.4 同口径：只数真实照片，装饰图/gif 不计） ----------
    img_tags = re.findall(r'<img\b[^>]*>', raw)
    photos = []
    for tag in img_tags:
        if re.search(r'data-isicon', tag, re.I):
            continue
        ms = re.search(r'\ssrc="([^"]+)"', tag)
        if not ms:
            continue
        if re.search(r'wx_fmt=gif|\.gif(?:\?|$|")', ms.group(1), re.I):
            continue
        photos.append(ms.group(1))
    if not photos:
        photos = [re.search(r'\ssrc="([^"]+)"', t).group(1) for t in img_tags
                  if re.search(r'\ssrc="([^"]+)"', t)]
    imgs = photos
    n_img = len(imgs)
    if n_img > MAX_IMAGES:
        fatal.append(f'照片 {n_img} 张，超过上限 {MAX_IMAGES} 张')
    external = [u for u in imgs if u.startswith('http') and not re.search(r'mmbiz\.qpic\.cn|qlogo\.cn', u)]
    if external:
        info.append(f'外链图床图片 {len(external)} 张：微信会拦截外链，发布前需上传素材库替换')
    local = [u for u in imgs if not u.startswith('http')]
    if local:
        info.append(f'本地路径图片 {len(local)} 张：发布前需上传公众号素材库替换')
    seg = re.findall(r'<(section|p)[^>]*style="([^"]*)"[^>]*>\s*(?:<[^>]+>\s*)*<img', raw)
    no8 = [st for tag, st in seg if 'margin:8px' not in st.replace(' ', '')]
    if seg and len(no8) == len(seg):
        warn.append('图片容器均未见 margin:8px（规范要求图片段前/段后距 8px）')
    elif no8:
        info.append(f'{len(no8)}/{len(seg)} 个图片容器未显式声明 margin:8px（继承外层样式可忽略）')

    # ---------- 6. 编辑器残留 ----------
    n_cls = len(re.findall(r'class="_editor"', raw))
    if n_cls:
        info.append(f'{n_cls} 处 class="_editor" 为编辑器残留，无实际作用，建议清理')
    n_imp = len(re.findall(r'!important', raw))
    if n_imp > 8:
        warn.append(f'{n_imp} 处 !important，易与编辑器默认样式冲突')
    if re.search(r'(?:^|[\s:;])color\s*:\s*#000\b', s, re.I | re.M):
        warn.append('存在纯黑 #000 文字色，建议改 #3e3e3e 系')
    if re.search(r'viewbox=', raw):
        info.append('SVG 为小写 viewbox/foreignobject，微信可兼容；规范写法 viewBox/foreignObject')

    return {'file': path, 'ok': not fatal, 'fatal': fatal, 'warn': warn, 'info': info,
            'stats': {'images': n_img, 'body_font_size': body_fs, 'paragraphs': n}}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    r = check(sys.argv[1])
    if '--json' in sys.argv:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print('=' * 56)
        print('浙东院推文排版体检:', r['file'])
        print('=' * 56)
        if r['fatal']:
            print('❌ 致命问题（必须修复）')
            for x in r['fatal']:
                print('   -', x)
        else:
            print('✅ 无致命问题')
        if r['warn']:
            print('⚠️  建议修改')
            for x in r['warn']:
                print('   -', x)
        if r['info']:
            print('ℹ️  提示')
            for x in r['info']:
                print('   -', x)
        st = r['stats']
        print('-' * 56)
        print(f"图片 {st['images']} 张 | 正文字号 {st['body_font_size']}px | 正文段落 {st['paragraphs']} 个")
        print('结论:', '✅ 符合规范，可发布' if r['ok'] else '❌ 存在致命问题，修复后重检')
    sys.exit(0 if r['ok'] else 1)


if __name__ == '__main__':
    main()
