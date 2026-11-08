# -*- coding: utf-8 -*-
"""从历史推文库 (D:\\Desktop\\推文) 抽取代表作全文档案，写入 skill assets/examples/。
保留：结构 + 全部 inline style + 文字（可学语气/小标题/落款）
去掉：图片二进制与 base64（替换为 <!--IMG--> 标记，只留宽度提示），data-* 属性
"""
import os, re, io, json, html, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else r'D:\Desktop\推文'
DST = r'C:\Users\Administrator\.workbuddy\skills\zhedongyuan-tuiwen\assets\examples'

# (文件名, 题材, 历史标题关键词, 可学点)
PICKS = [
    ('01-风景时节-又被校园美到了', '风景时节', '又被校园美到了',
     '治愈系风景稿的标准骨架：短句开篇→大图铺陈→一句一景→金句收束，全篇无虚线框，靠米底卡与白边相框分区'),
    ('02-风景时节-桂香满溢', '风景时节', '桂香满溢秋日里的温柔气息',
     '气味/季节双线写法：以桂花香作叙事钩子，段落短、留白多，适合秋季节气稿'),
    ('03-风景时节-文成看雪', '风景时节', '今天我在文成校区看雪',
     '短稿范式（全篇约600字）：单一场景深写，标题口语化，正文克制不堆辞藻'),
    ('04-招生章程-2025提前招生', '招生章程', '浙江东方职业技术学院2025年高职提前招生章程',
     '官方发布体：编号条款+表格+层级标题，全篇不抒情，字号/行距比文艺稿更紧'),
    ('05-活动节庆-爱生节', '活动节庆', '东方学子第四届爱生节超燃来袭',
     '活动预热稿：时间线+亮点清单+参与方式三段式，动感动词密集'),
    ('06-荣誉表彰-军训总结表彰', '荣誉表彰', '军训成果汇报暨总结表彰大会',
     '会议/表彰稿：领导出席名单体例→议程复述→表彰名单→寄语收尾'),
    ('07-纪念-九一八', '思政纪念', '九一八勿忘勿忘九一八',
     '重大纪念日稿：史实密度高、黑红配色、金句排比，情绪递进但事实克制'),
    ('08-通知指南-考生须知', '通知指南', '考生须知浙江东方职院提招综合素质测试安排',
     '服务型通知：必读信息前置、分点编号、加粗关键时间地点，末尾留联系方式'),
    ('09-赛事大赛-国家级大赛', '赛事大赛', '这场国家级大赛将在浙江东方职院举行',
     '赛事预告稿：规格背书→赛项介绍→筹备进展→期待收尾'),
    ('10-人物故事-网安竞赛团队', '人物故事', '网安竞赛团队的攻防之道',
     '人物群像稿：一人一段+引语，小标题用人名/标签，结尾升到精神层面'),
]

END_MARKS = ['id="js_pc_qr_code"', 'class="rich_media_tool"', 'id="js_pc_qr_code"',
             'class="qr_code_pc', '<script', 'id="js_article_bottom_bar"']


def find_file(keyword):
    for root, dirs, files in os.walk(SRC):
        for f in files:
            if f.lower().endswith(('.html', '.htm')) and keyword in f:
                return os.path.join(root, f)
    # 退化：按标题内容匹配
    for root, dirs, files in os.walk(SRC):
        for f in files:
            if not f.lower().endswith(('.html', '.htm')):
                continue
            p = os.path.join(root, f)
            try:
                h = io.open(p, encoding='utf-8', errors='ignore').read(20000)
            except Exception:
                continue
            if keyword in h:
                return p
    return None


def extract_body(h):
    i = h.find('id="js_content"')
    if i < 0:
        i = h.find('class="rich_media_content')
    if i < 0:
        return ''
    start = h.find('>', i)
    if start < 0:
        return ''
    start += 1
    ends = [h.find(m, start) for m in END_MARKS]
    ends = [e for e in ends if e > start]
    end = min(ends) if ends else len(h)
    return h[start:end]


def clean(body):
    # 去 base64 图
    body = re.sub(r'src\s*=\s*"data:[^"]*"', 'src="__IMG__"', body, flags=re.I)
    # 图片 → 注释标记（保留 style 里的 width 线索）
    def imgrep(m):
        tag = m.group(0)
        w = re.search(r'width\s*:\s*([\d.]+%?)', tag)
        return '<!--IMG%s-->' % ((' width=' + w.group(1)) if w else '')
    body = re.sub(r'<img\b[^>]*>', imgrep, body, flags=re.I)
    # 去 data-* 属性
    body = re.sub(r'\s+data-[\w-]+\s*=\s*"[^"]*"', '', body, flags=re.I)
    # 去空的 class/_editor 残留
    body = re.sub(r'\s+class\s*=\s*"_editor"[^>]*', '', body, flags=re.I)
    # 压缩连续空白（不动标签内单个空格）
    body = re.sub(r'[ \t]*\r?\n[ \t]*', '\n', body)
    body = re.sub(r'\n{3,}', '\n\n', body)
    body = re.sub(r'>\s+<', '><', body)
    # 掐掉微信阅读页的尾部垃圾
    body = re.split(r'预览时标签不可点', body)[0]
    body = re.sub(r'<div\s*$', '', body.strip())
    body = re.sub(r'<[^<>]{0,40}$', '', body).strip()
    return body


def main():
    os.makedirs(DST, exist_ok=True)
    index = []
    for name, genre, kw, lesson in PICKS:
        p = find_file(kw)
        if not p:
            print('[MISS]', kw)
            continue
        h = io.open(p, encoding='utf-8', errors='ignore').read()
        title = ''
        for pat in (r'var msg_title\s*=\s*[\'"](.*?)[\'"]',
                    r'property="og:title"\s*content="([^"]+)"',
                    r'<title>\s*([^<]{2,80})'):
            m = re.search(pat, h, re.S)
            if m:
                title = html.unescape(m.group(1)).strip()
                if len(title) > 1:
                    break
        if len(title) < 2:  # 兜底：用文件名
            title = re.sub(r'\.html?$', '', os.path.basename(p))
        body = clean(extract_body(h))
        if len(body) < 3000:
            print('[SHORT]', kw, len(body), p)
            continue
        chars = len(re.sub(r'<[^>]+>', '', body))
        imgs = body.count('<!--IMG')
        head = ('<!--\n'
                '  ZJDF 历史代表稿 · 参考档案（非模板，勿整篇套用）\n'
                '  题材：%s\n'
                '  原标题：%s\n'
                '  来源文件：%s\n'
                '  正文纯文字约 %d 字 / 含 %d 处图片占位\n'
                '  可学点：%s\n'
                '  注意：图片已剥离，只保留 <!--IMG--> 占位；inline style 全部原样保留\n'
                '-->\n' % (genre, title, os.path.basename(p), chars, imgs, lesson))
        doc = head + '<div class="zjdf-ref">\n' + body + '\n</div>\n'
        out = os.path.join(DST, name + '.html')
        io.open(out, 'w', encoding='utf-8').write(doc)
        index.append(dict(file=name + '.html', genre=genre, title=title,
                          chars=chars, imgs=imgs, kb=round(len(doc.encode()) / 1024, 1),
                          lesson=lesson, src=os.path.basename(p)))
        print('[OK]', name, chars, '字', imgs, '图', round(len(doc.encode()) / 1024, 1), 'KB')

    # INDEX.md
    lines = ['# 历史代表稿索引（assets/examples/）', '',
             '> 用途：写稿前先按题材取 1-2 篇同类历史稿，学它的**骨架、语气、分区手法**，不要抄内容。',
             '> 图片已被剥离（正文里的 `<!--IMG-->` 是原图位置），inline style 全部保留，可直接看排版参数。', '',
             '| 文件 | 题材 | 原标题 | 字数 | 图数 | 体积 | 可学点 |',
             '|---|---|---|---|---|---|---|']
    for r in index:
        lines.append('| `%s` | %s | %s | %d | %d | %.1f KB | %s |' % (
            r['file'], r['genre'], r['title'], r['chars'], r['imgs'], r['kb'], r['lesson']))
    lines += ['', '## 按题材取稿', '']
    genres = {}
    for r in index:
        genres.setdefault(r['genre'], []).append(r['file'])
    for g, fs in genres.items():
        lines.append('- **%s** → %s' % (g, ' / '.join('`%s`' % f for f in fs)))
    lines += ['', '## 反向用法（体检/评分时）', '',
              '某篇稿子的排版被判"不像院内稿"，就按题材调出这里 1 篇对比：看小标题写法、图片留白、段落长度、落款格式，']
    lines += ['指出差异点，而不是套通用审美。', '']
    io.open(os.path.join(DST, 'INDEX.md'), 'w', encoding='utf-8').write('\n'.join(lines))
    print('\nINDEX.md written, examples:', len(index))


if __name__ == '__main__':
    main()
