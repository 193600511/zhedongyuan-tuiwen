# -*- coding: utf-8 -*-
"""把历史推文全量归档进 skill：assets/archive/

设计取舍（实测）：
  - 原始存档 342 篇共 75.6 MB，其中微信页面外壳/脚本/内联样式占绝大部分；
  - 只取 id="js_content" 正文后合计 11.2 MB，gzip 后约 1.7 MB —— 这是可接受的 skill 体积；
  - 因此归档为「正文 gzip」，渲染时由 scripts/render_archive.py 现场组装成可看页面。

用法：
  python build_archive.py [源目录]     # 默认 D:\\Desktop\\推文

产出：
  assets/archive/NNN-标题.html.gz   每篇一个，正文 HTML（data-src 已转 src）
  assets/archive/manifest.json      编号/标题/题材/字数/图数/日期/原文件名
  assets/archive/INDEX.md           按题材分组的人工索引
"""
import os, re, io, gzip, json, html, sys, time, collections

SRC = sys.argv[1] if len(sys.argv) > 1 else r'D:\Desktop\推文'
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(SKILL, 'assets', 'archive')

END_MARKS = ['id="js_pc_qr_code"', 'class="rich_media_tool"', 'id="js_article_bottom_bar"',
             '<script', '预览时标签不可点']

GENRES = [
    ('招生就业', ['招生', '章程', '简章', '报考', '志愿', '录取', '招聘', '就业', '双选', '岗位', '专业介绍', '新增3个专业']),
    ('理论学习', ['习近平', '八项规定', '政府工作报告', '理论', '学习贯彻', '全会精神', '重要论述', '论述摘编', '保密', '禁毒', '宪法', '条例', '形式主义', '官僚主义']),
    ('思政党建', ['党委', '党建', '党支部', '党员', '党课', '主题党日', '党风廉政', '意识形态', '团委', '团日', '工会', '双代会', '团代会', '学代会', '红色', '烈士', '纪念', '勿忘', '爱国', '工人先锋号', '劳模', '思政']),
    ('荣誉表彰', ['获奖', '喜报', '荣获', '表彰', '入选', '冠军', '斩获', '夺金', '折桂', '第一', '称号', '优秀', '获评', '获批', '再添', '再获', '名单公布', '多项省赛', '一等奖']),
    ('会议调研', ['召开', '会议', '论坛', '调研', '座谈', '揭牌', '签约', '来访', '代表团', '莅临', '指导', '年会', '成立', '推进会', '双代会', '教代会', '代表大会', '务虚会', '党委会', '工作会', '大培训', '大讨论', '贺词', '新年']),
    ('赛事大赛', ['大赛', '比赛', '竞赛', '赛项', '技能赛', '选拔', '决赛', '擂台', '运动会', '田径']),
    ('通知指南', ['通知', '指南', '须知', '公告', '提醒', '速览', '安排', '公示', '放假', '安全', '攻略', '告全体', '必看', '预警', '台风', '警戒线', '风雨', '请查收']),
    ('风景时节', ['秋', '春', '夏', '冬', '雪', '花', '桂', '荷', '美到', '光影', '风景', '校园美', '晚霞', '节气', '诗词', '雨纷纷']),
    ('活动节庆', ['节', '活动', '来袭', '开幕', '举办', '仪式', '晚会', '嘉年华', '游园', '集市', '典礼', '开学', '毕业', '迎新', '报到', '研学', '结营', '启动', '贺岁', '辞旧']),
    ('人物故事', ['学子', '老师', '教师', '校友', '故事', '专访', '人物', '榜样', '匠心', '青春', '他们', '她说', '他说', '奇遇', '人设', '家访', '慰问', '走访', '启程', '新兵', '团队']),
    ('互动栏目', ['Flag', '红包', '体验卡', '答题', '征集', '投票', '抽奖', '头像', '封面', '壁纸', '微课堂', '敬请期待', '限量']),
]


def genre_of(title):
    """按命中关键词的权重打分（长词更具体，权重=字数），取代首次命中——
    否则「新春慰问家访」会被 '春' 抢成风景时节。"""
    best, best_score = '其他', 0
    for g, kws in GENRES:
        s = sum(len(k) for k in kws if k in title)
        if s > best_score:
            best, best_score = g, s
    return best


def pick_title(h, path):
    for pat in (r'var msg_title\s*=\s*[\'"](.*?)[\'"]',
                r'property="og:title"\s*content="([^"]+)"',
                r'<title>\s*([^<]{2,80})'):
        m = re.search(pat, h, re.S)
        if m:
            t = html.unescape(m.group(1)).strip()
            if len(t) > 1:
                return t
    return re.sub(r'\.html?$', '', os.path.basename(path))


def pick_date(h):
    for pat in (r'var ct\s*=\s*"(\d{10})"',
                r'"publish_time"\s*:\s*"?(\d{10})"?',
                r'var create_time\s*=\s*"(\d{10})"'):
        m = re.search(pat, h)
        if m:
            try:
                return time.strftime('%Y-%m-%d', time.localtime(int(m.group(1))))
            except Exception:
                pass
    # 存档里没有发布日期（批量下载，文件时间全同），退回标题里的年份线索
    return ''


def pick_year(title):
    m = re.search(r'(20\d\d)', title)
    return m.group(1) if m else ''


def extract_body(h):
    i = h.find('id="js_content"')
    if i < 0:
        i = h.find('class="rich_media_content')
    if i < 0:
        return ''
    s = h.find('>', i)
    if s < 0:
        return ''
    s += 1
    ends = [h.find(m, s) for m in END_MARKS]
    ends = [e for e in ends if e > s]
    return h[s:min(ends) if ends else len(h)]


def clean_body(b):
    b = re.sub(r'<script\b.*?</script>', '', b, flags=re.S | re.I)
    b = re.sub(r'<!--(?!IMG).*?-->', '', b, flags=re.S)
    # 懒加载图：data-src 才是真地址
    def fix_img(m):
        tag = m.group(0)
        ds = re.search(r'data-src\s*=\s*"([^"]+)"', tag)
        if ds and 'src="' not in tag:
            tag = tag.replace('<img', '<img src="%s"' % ds.group(1), 1)
        elif ds:
            tag = re.sub(r'src\s*=\s*"[^"]*"', 'src="%s"' % ds.group(1), tag, count=1)
        return tag
    b = re.sub(r'<img\b[^>]*>', fix_img, b, flags=re.I)
    b = re.sub(r'\s+data-(?:src|srcset|croporiginext|ratio|type|w|origin|from|p\|img|galleryimg|index|fingerprint|reporttime|reportid|reportkey|report)\s*=\s*"[^"]*"', '', b, flags=re.I)
    b = re.sub(r'\s+(?:srcset|loading|decoding|draggable|referrerpolicy)\s*=\s*"[^"]*"', '', b, flags=re.I)
    b = re.split(r'预览时标签不可点', b)[0]
    b = re.sub(r'<div\s*$', '', b.strip())
    b = re.sub(r'<[^<>]{0,40}$', '', b)
    b = re.sub(r'[ \t]*\r?\n[ \t]*', '\n', b)
    b = re.sub(r'\n{3,}', '\n\n', b)
    return b.strip()


def slug(t, n=14):
    t = re.sub(r'[\\/:*?"<>|\s\u3000]+', '', t)
    return t[:n] or 'untitled'


def main():
    os.makedirs(DST, exist_ok=True)
    files = []
    for root, dirs, fs in os.walk(SRC):
        for f in fs:
            if f.lower().endswith(('.html', '.htm')):
                files.append(os.path.join(root, f))
    files.sort()

    recs = []
    for idx, p in enumerate(files, 1):
        h = io.open(p, encoding='utf-8', errors='ignore').read()
        title = pick_title(h, p)
        body = clean_body(extract_body(h))
        if len(body) < 500:
            print('[SKIP]', os.path.basename(p), len(body))
            continue
        chars = len(re.sub(r'<[^>]+>', '', body))
        imgs = len(re.findall(r'<img\b', body, re.I))
        raw = body.encode('utf-8')
        gz = gzip.compress(raw, 6)
        name = '%03d-%s.html.gz' % (idx, slug(title))
        io.open(os.path.join(DST, name), 'wb').write(gz)
        recs.append(dict(id=idx, file=name, title=title, genre=genre_of(title),
                         chars=chars, imgs=imgs,
                         kb=round(len(raw) / 1024, 1), gz_kb=round(len(gz) / 1024, 1),
                         date=pick_date(h) or pick_year(title), src=os.path.basename(p)))
        if idx % 50 == 0:
            print('...', idx)

    recs.sort(key=lambda r: r['id'])
    io.open(os.path.join(DST, 'manifest.json'), 'w', encoding='utf-8').write(
        json.dumps(recs, ensure_ascii=False, indent=1))

    # INDEX.md
    L = ['# 历史推文全量归档（assets/archive/）', '',
         '> %d 篇，正文 gzip 存档，合计 %.1f MB（未压缩 %.1f MB）。' % (
             len(recs), sum(r['gz_kb'] for r in recs) / 1024, sum(r['kb'] for r in recs) / 1024),
         '> **要看长什么样**：`python scripts/render_archive.py render <编号或关键词>` —— 解压并渲染成公众号长图 + 逐屏截图。',
         '> **要查参数**：`python scripts/render_archive.py cat <编号>` 打印正文 HTML；或 render 后直接看 HTML。',
         '> 十篇精华版（已剥图、可直接读）在 `assets/examples/`，结构速查在 `references/style-cases.md`。',
         '> 注：存档不含发布日期（批量下载，文件时间被统一），表中「年份」来自标题里出现的年份，空白即无从判断。', '']
    by_g = collections.defaultdict(list)
    for r in recs:
        by_g[r['genre']].append(r)
    L += ['## 题材分布', '', '| 题材 | 篇数 |', '|---|---|']
    for g, rs in sorted(by_g.items(), key=lambda x: -len(x[1])):
        L.append('| %s | %d |' % (g, len(rs)))
    L.append('')
    for g, rs in sorted(by_g.items(), key=lambda x: -len(x[1])):
        L += ['## %s（%d 篇）' % (g, len(rs)), '',
              '| 编号 | 标题 | 字数 | 图 | 年份 |', '|---|---|---|---|---|']
        for r in sorted(rs, key=lambda x: -x['chars']):
            L.append('| %d | %s | %d | %d | %s |' % (r['id'], r['title'], r['chars'], r['imgs'], r['date']))
        L.append('')
    io.open(os.path.join(DST, 'INDEX.md'), 'w', encoding='utf-8').write('\n'.join(L))

    print('\n归档完成：%d 篇，gzip %.2f MB' % (len(recs), sum(r['gz_kb'] for r in recs) / 1024))
    print('题材分布：', dict(collections.Counter(r['genre'] for r in recs)))


if __name__ == '__main__':
    main()
