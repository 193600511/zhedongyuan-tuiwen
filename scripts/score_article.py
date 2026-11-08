# -*- coding: utf-8 -*-
"""
浙东院推文质量评分器（100 分制 · 五维评价 · 稿型自适应）

用法:
  python score_article.py <article.html>                  # 终端评分卡
  python score_article.py <article.html> --json           # 机器可读
  python score_article.py <article.html> --html out.html  # 可视化评分卡
  python score_article.py <article.html> --brief          # 只输出总分与等级

五维权重:
  格式规范 30 · 结构完整 20 · 内容质量 25 · 阅读体验 15 · 合规风险 10

稿型自适应（自动识别，不同稿型用不同尺子）:
  新闻/会议类  查导语时间锚点、主体引述、信息密度
  预告/赛事类  查时间地点/主办/参与方式，短段分行不扣分
  通知/服务类  查条目编号、联系方式
  风景/时节类  查画面感，不查信息密度与新闻要素
  人物类      查人物身份、引述、故事细节

设计原则:
  1. 格式项直接复用 check_article.py，避免两套标准打架
  2. 每个维度按「扣分项」记账，输出明细，不只给总分
  3. 只对可客观判定的事实扣分，主观好恶不入分
退出码: 0=可发布(≥80) 1=需修改(70-79) 2=明显不合格(<70)
"""
import io, os, re, sys, json, collections, html as htmlmod

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_article import (check, StyleTextCollector, strip_noise, visible_text,
                           CN, MAX_IMAGES)

VERSION = '1.4 (2026-11-05)'
GRADE_TABLE = [
    (90, 'A+', '可直接发布'),
    (84, 'A',  '小修即可发布'),
    (76, 'B',  '基本合格，按清单优化'),
    (68, 'C',  '存在明显短板'),
    (0,  'D',  '需返工重写'),
]
BASELINE = 80   # 342 篇已发布存档的评分中位数，用于参照（v1.2 标定）

ABSOLUTE = [
    (r'最(好|佳|优|强|棒|大|高|先进|权威|专业|领先)', '绝对化用语「最…」'),
    (r'第\s*一(名|位|家|个)|全国第一|全省第一', '排名类绝对化表述'),
    (r'唯一|独家(发布|报道|拥有)|史无前例|前所未有', '排他性表述'),
    (r'国家级|世界级|国际领先|行业领先|顶尖|顶级', '等级夸张表述'),
    (r'100\s*%|百分之百|彻底(解决|消除)|永久(有效|免费)', '绝对承诺表述'),
]
PLACEHOLDER = [r'X{2,}', r'\{\{.*?\}\}', r'待定', r'TBD', r'TODO']
SENSITIVE = [r'疫情|封控', r'上访|游行|示威', r'赌博|博彩', r'传销']
LEAD_TIME = r'(\d{1,2}\s*月\s*\d{1,2}\s*[日号])|(近日|日前|上午|下午|当天|\d{4}\s*年)'
ORG_WORDS = '主办|承办|协办|出席|参加|表示|指出|介绍|希望|强调'
SCENERY_WORDS = r'[春秋夏冬]|花|叶|风|光|暖|色|树|云|雨|晨|暮|金|霜|露|枝|光影|校园'
SENT_SPLIT = r'[。！？；!?;]'


def grade(total):
    for lo, g, desc in GRADE_TABLE:
        if total >= lo:
            return g, desc
    return 'D', '需返工重写'


def detect_genre(txt, paras):
    """稿型识别：返回 (key, 中文名)"""
    body = ''.join(t for t, _ in paras) or txt
    if re.search(r'通知|须知|关于.{0,14}的(通知|公告|安排)|报名流程|办理|申报', body):
        return 'notice', '通知/服务类'
    if re.search(r'大赛|赛项|总决赛|赛事|参赛|敬请期待|即将(开赛|举行|启幕)|邀您', body):
        return 'preview', '预告/赛事类'
    if re.search(r'榜样|匠心|专访|人物|风采|走近|故事|教师|同学', body) and \
       len(re.findall(r'(他|她)', body)) >= 2:
        return 'profile', '人物类'
    sc = len(re.findall(SCENERY_WORDS, body))
    if sc >= max(8, len(body) // 45):
        return 'scenery', '风景/时节类'
    return 'news', '新闻/会议类'


CHROME_IMG = re.compile(r'jump_author_avatar|wx_follow|rich_media_meta|avatar|profil|qrcode|emotion', re.I)
# 模板装饰图：96 模板的花叶/圆点/图标（data-isicon 标记，或 gif 动图装饰）
DECO_IMG = re.compile(r'data-isicon|wx_fmt=gif|\.gif(?:\?|$|")', re.I)


def extract_images(raw):
    """返回 [(src, pos)]，已剔除作者头像/关注条/表情等微信挂件"""
    out = []
    for m in re.finditer(r'<img\b[^>]*>', raw, re.I):
        tag = m.group(0)
        if CHROME_IMG.search(tag):
            continue
        src = re.search(r'\ssrc="([^"]+)"', tag) or re.search(r'\sdata-src="([^"]+)"', tag)
        if not src:
            continue
        out.append((src.group(1), m.start()))
    return out


def extract_photos(raw):
    """只数真实照片：剔除模板装饰图（data-isicon 图标 / gif 花叶动效）。
    data-isicon 是标签属性、不在 URL 里，必须按整个 <img> 标签判。
    若整篇都被判成装饰（例如全 gif 相册），退回全量，避免把图片数算成 0。"""
    allimg = extract_images(raw)
    photos = []
    for m in re.finditer(r'<img\b[^>]*>', raw, re.I):
        tag = m.group(0)
        if CHROME_IMG.search(tag) or 'data-isicon' in tag:
            continue
        src = re.search(r'\ssrc="([^"]+)"', tag) or re.search(r'\sdata-src="([^"]+)"', tag)
        if not src:
            continue
        if DECO_IMG.search(src.group(1)):
            continue
        photos.append((src.group(1), m.start()))
    return photos if photos else allimg


def first_text_pos(raw, para):
    """正文段落在原始 HTML 中的位置（按递降长度试探）"""
    for L in (24, 16, 10):
        if len(para) >= L:
            i = raw.find(para[:L])
            if i > 0:
                return i
    return -1


def split_sentences(body):
    """句长统计：先按句末标点切，超长串再按顿号细分（列举式不算长句）"""
    out = []
    for chunk in re.split(SENT_SPLIT, body):
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) > 80 and '、' in chunk:
            out.extend([x for x in chunk.split('、') if x.strip()])
        else:
            out.append(chunk)
    return out


def collect_paragraphs(raw):
    """正文段落（与 check_article 同口径：≥20 汉字、非 12px、父子去重）"""
    p = StyleTextCollector()
    p.feed(strip_noise(raw))
    p.close()
    cands = []
    for style, text in p.items:
        t = re.sub(r'\s+', '', text)                      # 先归一空白，再判长度/内容
        fs = re.search(r'font-size\s*:\s*([\d.]+)\s*px', style)
        if len(CN.findall(t)) < 20:
            continue
        if fs and fs.group(1) in ('10', '11', '12'):      # 图注/落款小字，不算正文
            continue
        if len(t) < 80 and re.search(r'来\s*源|编\s*辑|责\s*[编审]|终\s*[核审]', t):
            continue                                       # 落款行
        cands.append((t, style))
    uniq = {}
    for t, st in cands:
        uniq.setdefault(t, st)
    return [(t, st) for t, st in uniq.items()
            if not any(t != o and o in t for o in uniq)]


def score(path):
    raw = io.open(path, encoding='utf-8', errors='ignore').read()
    s = strip_noise(raw)
    base = check(path)
    txt = visible_text(s)
    paras = collect_paragraphs(raw)
    para_texts = [t for t, _ in paras]
    body = ''.join(para_texts)
    imgs_all = extract_images(raw)
    imgs = [u for u, _ in imgs_all]
    photos_all = extract_photos(raw)
    photos = [u for u, _ in photos_all]
    genre, gname = detect_genre(txt, paras)

    dims = []

    def bucket(weight):
        return [weight, []]

    # ================= 一、格式规范 30 =================
    b = bucket(30)

    def cut(n, why):
        n = min(n, b[0])
        if n <= 0:
            return
        b[0] -= n
        b[1].append((n, why))

    fs_list = [m.group(1) for _, st in paras
               for m in [re.search(r'font-size\s*:\s*([\d.]+)\s*px', st)] if m]
    fs_main = collections.Counter(fs_list).most_common(1)[0][0] if fs_list else None
    if fs_main == '17':
        pass
    elif fs_main in ('15', '16'):
        cut(4, f'正文字号主流 {fs_main}px，规范 17px（历史旧稿常见，建议统一到 17px）')
    elif fs_main:
        cut(8, f'正文字号主流 {fs_main}px，规范 17px')
    elif paras:
        cut(6, '正文段未声明 font-size，靠继承/默认（手机端通常落到 15–16px）')
    else:
        cut(3, '未解析到正文内容（纯图推文或模板未填充）')
    if re.search(r'font-family', s, re.I):
        cut(4, '出现 font-family，规范要求系统默认字体')

    n = len(paras)
    if n:
        # 行距：微信常在父级 section 声明，按「全篇是否使用 1.75」存在性判定
        if not re.search(r'line-height\s*:\s*1\.75', s):
            cut(4, '正文未使用行距 1.75')
        ls_bad = sum(1 for _, st in paras if re.search(r'letter-spacing\s*:\s*([1-9]|0\.[1-9])', st))
        if ls_bad:
            cut(min(2, max(1, round(2 * ls_bad / n))), f'{ls_bad}/{n} 段字间距非 0')
        body_st = [st for _, st in paras if re.search(r'font-size\s*:\s*17\s*px', st)]
        # 右对齐：96 模板常把 align 写在 <p> 上、正文被拆成短碎片，
        # 采集器拿到的是父容器 style，因此直接扫 <p> 标签内的成段文字
        right_hits = [st for st in body_st if re.search(r'text-align\s*:\s*right', st)]
        for m in re.finditer(r'<p\b[^>]*text-align\s*:\s*right[^>]*>(.*?)</p>', s, re.I | re.S):
            if len(CN.findall(re.sub(r'<[^>]+>', '', m.group(1)))) >= 12:
                right_hits.append('p')
        if body_st:
            has_ind = 'text-indent' in s
            has_jus = 'justify' in s
            no_ind = sum(1 for st in body_st if 'text-indent' not in st)
            no_jus = sum(1 for st in body_st if 'justify' not in st)
            ind_vals = sorted(set(re.findall(r'text-indent\s*:\s*([\d.]+)em', s)), key=float)
            odd_ind = [v for v in ind_vals if abs(float(v) - 2) > 0.05]
            if odd_ind:
                cut(1, '首行缩进用了 ' + '/'.join(v + 'em' for v in odd_ind) + '，规范 2em')
            elif not has_ind and no_ind == len(body_st):
                cut(2, '17px 正文段整体缺 text-indent:2em')
            elif has_ind and no_ind:
                cut(1, f'{no_ind}/{len(body_st)} 段未直接声明缩进（可能继承父级）')
            if right_hits:
                cut(2, f'{len(right_hits)} 处正文右对齐（中文成段右对齐难读，改 justify）')
            elif not has_jus and no_jus == len(body_st):
                cut(2, '17px 正文段未两端对齐 justify')
            elif has_jus and no_jus:
                cut(1, f'{no_jus}/{len(body_st)} 段未直接声明对齐（可能继承父级）')
    if len(photos) > MAX_IMAGES:
        cut(1, f'正文照片 {len(photos)} 张，超过建议上限 {MAX_IMAGES}（现场照片多可例外）')
    # margin:8px 多写在更外层容器上，存在性即可，不单独扣分
    dims.append(('格式规范', 30, b[0], b[1]))

    # ================= 二、结构完整 20 =================
    b = bucket(20)
    head = s[:1600]
    pos_first_para = first_text_pos(raw, para_texts[0]) if para_texts else -1
    head_imgs = [pos for _, pos in imgs_all if pos_first_para > 0 and pos < pos_first_para]
    # 位置定位失败时退化为「有任意图片即视为通过」，避免误杀
    has_head = head_imgs or re.search(r'<svg', head) or (pos_first_para <= 0 and imgs_all)
    if not has_head:
        cut(3, '开头缺头图（滑动 Logo / 主视觉）')

    deco = []
    if re.search(r'display:inline-block[^"]*border-radius:1em', head) or \
       re.search(r'border-radius\s*:\s*1em[^"]*background-color', head):
        deco.append('胶囊标签')
    if re.search(r'font-size\s*:\s*(2[2-9]|3[0-2])\s*px[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*<strong>', head):
        deco.append('居中大标题')
    # 模板封面卡：开头出现 33px+ 的超大标题字（96 模板常见的「大标题卡」）
    if len(re.findall(r'font-size\s*:\s*(?:3[3-9]|[4-9]\d)\s*px', head)) >= 1:
        deco.append('超大标题字')
    if re.search(r'linear-gradient\([^)]*\)[^"]*height\s*:\s*1px', head):
        deco.append('装饰分隔线')
    if deco:
        cut(3, '开头有 ' + '/'.join(deco) + '（标题入标题栏，正文直接进导语）')

    if para_texts:
        lead, lead_len = para_texts[0], len(para_texts[0])
        if genre in ('preview', 'notice'):
            pass                     # 时间/地点等关键信息统一在「内容质量」判，避免重复扣分
        elif genre == 'scenery':
            if not (12 <= lead_len <= 260):
                cut(3, f'开篇 {lead_len} 字，宜 12–260 字')
        else:
            if not (40 <= lead_len <= 300):
                cut(4, f'导语段长度 {lead_len} 字，宜 40–300 字')
            elif not re.search(LEAD_TIME, lead):
                cut(2, '导语段缺时间锚点（年月日/近日/当天）')
    else:
        cut(4, '未识别到导语段')

    sec_marks = len(re.findall(r'[一二三四五六七]、', txt))
    tag_titles = len(re.findall(r'background-color://s*#[0-9a-fA-F]{6}[^"]*"[^>]*>//s*(?:<section[^>]*>//s*)?<p>', s))
    need_sec = 3 if genre in ('news', 'notice') else 2
    short_piece = len(body) < 600          # 短稿一段到底可接受
    if sec_marks >= 2 or tag_titles >= 2 or short_piece:
        pass
    elif sec_marks == 1 or tag_titles == 1:
        cut(1, '仅 1 处分节标记，长文宜 2–4 个层次')
    else:
        cut(2, f'正文 {len(body)} 字无分节标记（「一、二、」或实底标签小标题）')

    tail = txt[-2200:]
    need = [('来 源', r'来\s*源'), ('编 辑', r'编\s*辑'), ('一审', r'责\s*编.{0,4}一\s*审'),
            ('二审', r'责\s*审.{0,4}二\s*审'), ('三审', r'终\s*[核审].{0,4}三\s*审')]
    miss = [nm for nm, pat in need if not re.search(pat, tail)]
    if miss:
        cut(min(6, len(miss) * 2), '落款缺 ' + '、'.join(miss))
    if re.search(r'责\s*编.{0,4}一\s*审', tail) and '孙舒' not in tail:
        cut(1, '一审姓名非「孙舒」')
    if re.search(r'终\s*[核审].{0,4}三\s*审', tail) and '武德力' not in tail:
        cut(1, '三审姓名非「武德力」')
    pos_last = first_text_pos(raw, para_texts[-1]) if para_texts else -1
    tail_imgs = [pos for _, pos in imgs_all if pos_last > 0 and pos > pos_last]
    if pos_last > 0 and not tail_imgs:
        cut(2, '正文结束后无图（底部关注图/二维码缺失）')
    dims.append(('结构完整', 20, b[0], b[1]))

    # ================= 三、内容质量 25 =================
    b = bucket(25)
    if para_texts:
        lens = [len(t) for t in para_texts]
        long_p = [x for x in lens if x > 300]
        short_p = [x for x in lens if x < 35]
        if long_p:
            cut(min(6, len(long_p) * 2), f'{len(long_p)} 段超过 300 字（移动端易弃读）')
        if genre in ('news', 'scenery') and len(short_p) > max(2, len(lens) // 3):
            cut(2, f'{len(short_p)} 段偏短（<35 字），信息碎片化')

        facts = len(re.findall(r'\d+', body))
        orgs = len(re.findall(r'[\u4e00-\u9fa5]{2,10}(学院|大学|中心|公司|局|委|部|办|基地|集团)', body))
        density = (facts + orgs * 2) / max(1, len(body) / 100)

        if genre == 'news':
            if density < 3:
                cut(5, f'信息密度偏低（每百字事实点 {density:.1f}，宜 ≥3）')
            elif density < 5:
                cut(2, f'信息密度一般（每百字 {density:.1f}）')
            if not re.search(ORG_WORDS, body) and len(body) > 300:
                cut(3, '缺主体/引述表述（出席、主办、表示等），新闻要素不全')
        elif genre == 'preview':
            must = [('主办/承办方', r'主办|承办|协办'),
                    ('比赛/活动时间', r'时间|月.{0,3}[日号]|\d{4}\s*年'),
                    ('地点', r'地点|地址|校区|举办地')]
            for nm, pat in must:
                if not re.search(pat, body):
                    cut(6, f'关键信息缺「{nm}」')
            if density < 4:
                cut(2, f'信息密度偏低（每百字 {density:.1f}）')
        elif genre == 'notice':
            if not re.search(r'[一二三四五六七]、|\d+[.、]', body):
                cut(4, '通知类缺分条编号（一、二、／1. 2.）')
            if not re.search(r'联系|咨询|电话|\d{3,4}-?\d{7,8}', body):
                cut(3, '缺咨询/联系方式')
            if not re.search(LEAD_TIME, body):
                cut(2, '缺时间信息')
        elif genre == 'scenery':
            sc = len(re.findall(SCENERY_WORDS, body))
            if sc < max(6, len(body) // 60):
                cut(3, f'画面感词偏少（{sc} 处），景物描写偏薄')
            if len(body) < 200:
                cut(3, f'正文仅 {len(body)} 字，散文类偏短（宜 300+）')
        elif genre == 'profile':
            if not re.search(r'(老师|同学|教师|校友|他|她).{0,10}(说|表示|坦言|回忆)', body):
                cut(4, '缺人物引述（人物类核心）')
            if not re.search(r'\d{4}\s*年|\d+\s*年|\d+\s*次|\d+\s*项', body):
                cut(2, '缺具体经历细节（年份/次数/成果）')

        abs_hits = {m.group(0) for pat, _ in ABSOLUTE for m in re.finditer(pat, body)}
        if abs_hits:
            cut(min(5, len(abs_hits) * 2), '绝对化/夸张表述：' + '、'.join(sorted(abs_hits)[:5]))

        ph = {m.group(0) for pat in PLACEHOLDER for m in re.finditer(pat, txt)}
        if ph:
            cut(min(4, len(ph) * 2), '占位符未替换：' + '、'.join(sorted(ph)[:5]))

        sents_all = [x.strip() for x in re.split(SENT_SPLIT, body) if len(x.strip()) >= 12]
        dup = [x for x in set(sents_all) if sents_all.count(x) >= 2]
        if dup:
            cut(2, '整句重复：' + dup[0][:18] + '…')
    else:
        cut(8, '无可评分正文')
    dims.append(('内容质量', 25, b[0], b[1]))

    # ================= 四、阅读体验 15 =================
    b = bucket(17)
    np_, ni = len(para_texts), len(imgs)
    if np_ >= 6:
        if ni == 0:
            cut(5, '长文无配图，阅读疲劳')
        elif np_ / max(1, ni) > 5:
            cut(3, f'图文比 {np_}:{ni} 偏干（宜每 2–4 段一张图）')
    if np_ and not (4 <= np_ <= 24):
        cut(3 if np_ < 4 else 2, f'段落数 {np_} 段，宜 4–24 段')
    if para_texts:
        sents = split_sentences(body)
        avg = sum(len(x) for x in sents) / max(1, len(sents))
        if avg > 55:
            cut(3, f'平均句长 {avg:.0f} 字，偏长（宜 ≤45）')
        elif avg > 45:
            cut(1, f'平均句长 {avg:.0f} 字，略长')
    if para_texts:
        lead120 = para_texts[0][:120]
        if genre == 'scenery':
            if not re.search(SCENERY_WORDS, lead120):
                cut(2, '首屏缺画面感（景物/时令意象），打开即被划走')
        elif genre in ('preview', 'notice'):
            if not re.search(r'\d|时间|地点|大赛|通知', lead120):
                cut(2, '首屏未交代关键信息（时间/事件）')
        else:
            if not re.search(LEAD_TIME, lead120):
                cut(2, '首屏未交代时间/事件，打开即被划走')
    if re.search(r'(<p>\s*(?:<span[^>]*>\s*)*\s*(?:&nbsp;)?\s*</p>\s*){2,}', s):
        cut(2, '存在连续空段落')
    dims.append(('阅读体验', 17, b[0], b[1]))

    # ================= 五、合规风险 10 =================
    b = bucket(8)
    hits = {m.group(0) for pat in SENSITIVE for m in re.finditer(pat, txt)}
    if hits:
        cut(min(6, len(hits) * 3), '敏感表述：' + '、'.join(sorted(hits)[:5]))
    # 外链/本地图片属发布流程（上传素材库），不计入内容评分
    if re.search(r'(?:^|[\s:;])color\s*:\s*#000\b', s, re.I | re.M):
        cut(1, '纯黑 #000 文字色，建议 #3e3e3e 系')
    # !important 数量仅参考，不影响渲染，不扣分
    dims.append(('合规风险', 8, b[0], b[1]))

    total = sum(x[2] for x in dims)
    g, desc = grade(total)
    fixes = sorted([(a, nm, why) for nm, w, sc, de in dims for a, why in de],
                   key=lambda x: -x[0])

    _tmp = {
        'file': path, 'version': VERSION, 'genre': genre, 'genre_name': gname,
        'total': total, 'grade': g, 'verdict': desc,
        'dims': [{'name': nm, 'weight': w, 'score': sc,
                  'items': [{'deduct': a, 'reason': why} for a, why in de]}
                 for nm, w, sc, de in dims],
        'stats': {'paragraphs': len(para_texts), 'images': len(photos),
                  'chars': len(body), 'body_font_size': fs_main or '未声明',
                  'sections': sec_marks, 'fatal': len(base['fatal']),
                  'warn': len(base['warn'])},
    }
    critique_dict = critique(_tmp)
    # 存在必改项时不给 A+（再好也不能叫「可直接发布」）
    if critique_dict['hard_count'] and g == 'A+':
        g, desc = 'A', '修掉必改项再发'
        _tmp['grade'], _tmp['verdict'] = g, desc
        critique_dict = critique(_tmp)

    return {
        'file': path, 'version': VERSION, 'genre': genre, 'genre_name': gname,
        'total': total, 'grade': g, 'verdict': desc,
        'dims': [{'name': nm, 'weight': w, 'score': sc,
                  'items': [{'deduct': a, 'reason': why} for a, why in de]}
                 for nm, w, sc, de in dims],
        'fixes': [{'deduct': a, 'dim': nm, 'reason': why} for a, nm, why in fixes],
        'critique': critique_dict,
        'stats': {'paragraphs': len(para_texts), 'images': len(photos),
                  'chars': len(body), 'body_font_size': fs_main or '未声明',
                  'sections': sec_marks, 'fatal': len(base['fatal']),
                  'warn': len(base['warn'])},
    }


# ==================== 编辑点评：把扣分项翻成人话 ====================

def _n(reason, pat, cast=float, default=0):
    m = re.search(pat, reason)
    try:
        return cast(m.group(1)) if m else default
    except Exception:
        return default


def _kw(reason, *words):
    return any(w in reason for w in words)


def _issue_text(reason, r):
    """返回 (key, 标题, 严重度, 点评正文)。hard=必改，soft=可更好"""
    if _kw(reason, '正文字号主流'):
        fs = _n(reason, r'主流\s*([\d.]+)px', str, '?')
        return ('fontsize', '字号不对', 'hard',
                f'全篇正文主流是 {fs}px，学院硬规范是 17px。这不是审美问题——17px 是 342 篇实证下来'
                f'手机端最耐读的字号。改法：全选正文统一设 17px，图注 12px、小标题 18–24px 保留。')
    if _kw(reason, '未声明 font-size'):
        return ('nofontsize', '正文没设字号', 'hard',
                '正文段没有显式声明字号，全靠继承或编辑器默认——在手机上通常落到 15–16px，'
                '微信不同机型还会不一样。给每段正文补 font-size:17px，这是唯一能保证全平台一致的做法。')
    if _kw(reason, 'font-family'):
        return ('fontfamily', '指定了字体', 'hard',
                '出现 font-family。微信在 iOS 和安卓上会各自替换成系统字体，指定了也不生效，'
                '反而容易出现「安卓好看、苹果变形」。全部删掉，交给系统默认。')
    if _kw(reason, '未使用行距', '行距非'):
        return ('lineheight', '行距不够', 'hard',
                '正文行距没到 1.75，字挤在一起读三行就串行。给正文段统一加 line-height:1.75——'
                '这是全院 342 篇的基准值，也是《采编部教程》里的要求。')
    if _kw(reason, '字间距'):
        return ('letterspacing', '字被撑开了', 'soft',
                'letter-spacing 不是 0。字距一撑开，一行能放的字变少，段落显得松散。'
                '正文段统一回 0，需要呼吸感用段间距解决，不是字距。')
    if _kw(reason, 'text-indent', '缺 text-indent', '缩进'):
        return ('indent', '首行没缩进', 'soft',
                '中文正文习惯首行空两格。给 17px 正文段补 text-indent:2em；'
                '标题、图注、金句不缩进，缩进只给成段的正文。')
    if _kw(reason, 'justify', '两端对齐'):
        return ('justify', '右边缘参差', 'soft',
                '正文段没设 text-align:justify，右边缘会参差不齐。补上 justify，两端对齐后整块文字更齐整。')
    if _kw(reason, '超过建议上限'):
        return ('toomanyimg', '图放太多了', 'soft',
                f'正文 {_n(reason, r"(?:图片|照片)\s*(\d+)\s*张", int, "?")} 张照片，超过建议的 10 张。'
                '读者划到第五屏还没看到字，很容易直接退出。同角度的照片删掉，只留信息量最大的；'
                '必须都留就做拼图。')
    if _kw(reason, '右对齐'):
        return ('rightalign', '正文右对齐', 'hard',
                '成段正文用了 text-align:right。中文成段右对齐，每行起笔位置都不同，读三行就找不到下一行开头；'
                '模板的杂志风可以保留标题和图片，但成段文字一律改 justify。')
    if _kw(reason, '开头缺头图'):
        return ('nohead', '开头没有头图', 'soft',
                '正文一上来就是字，缺了滑动 Logo / 主视觉。往期都是「头图 → 正文」的顺序，'
                '读者第一眼能确认这是我们学校的号。从组件库把头图补回来。')
    if _kw(reason, '开头有'):
        deco = reason.split('开头有')[1].split('（')[0]
        return ('deco', '开头堆了标题装饰', 'hard',
                f'开头放了{deco}。公众号标题栏已经有标题，正文再挂一遍是重复；'
                '而且首屏被装饰占掉一半，正文被挤到下面看不见。删掉，直接从导语开始。')
    if _kw(reason, '导语段长度'):
        n = _n(reason, r'长度\s*(\d+)\s*字', int)
        why = '读者要划两屏才读完第一段，很容易放弃' if n > 300 else '信息量不够，读者不知道值不值得往下看'
        return ('lead', '导语轻重不对', 'soft',
                f'首段 {n} 字，{why}。导语只干一件事：一句话说清谁、什么时候、干了什么，'
                '40–300 字之间最合适，其余信息交给后面的段落。')
    if _kw(reason, '导语段缺时间锚点'):
        return ('leadtime', '导语看不出时间', 'hard',
                '首段没有时间点，读者不知道这是不是新消息。新闻稿的时间要落在开头，'
                '比如「11 月 4 日上午」，一句话就把时效交代了。')
    if _kw(reason, '无分节标记', '处分节标记'):
        return ('section', '一个层次到底', 'soft',
                '正文通篇没有「一、二、」或实底小标题。长稿切成 2–4 块，读者能快速定位，'
                '配图也有自然的落点。')
    if _kw(reason, '落款缺'):
        miss = reason.split('落款缺')[1].strip()
        return ('sign', '落款不完整', 'hard',
                f'缺「{miss}」。学院口径是五件套：来 源 / 编 辑 / 责 编（一审）孙舒 / '
                '责 审（二审）吴昕灿 / 终 核（三审）武德力，一项都不能少。')
    if _kw(reason, '一审姓名'):
        return ('reviewer', '一审署名不对', 'hard',
                '一审固定「孙舒」，写错等于署错人。发布前逐行核对三审姓名。')
    if _kw(reason, '三审姓名'):
        return ('reviewer3', '三审署名不对', 'hard',
                '三审固定「武德力」，这类署名错会被直接看出来。改回来。')
    if _kw(reason, '正文结束后无图'):
        return ('footer', '结尾没有落点', 'soft',
                '正文结束就没了，缺底部关注图/二维码。这是关注转化的唯一入口，往期都有，补上。')
    if _kw(reason, '段超过 300 字'):
        n = _n(reason, r'(\d+)\s*段超过', int)
        return ('longpara', f'{n} 段太长', 'soft',
                f'{n} 段超过 300 字。手机一屏大约 150–180 字，300 字要划两屏，中间没有换气点。'
                '按语义拆成 2 段，读起来轻很多。')
    if _kw(reason, '段偏短'):
        return ('shortpara', '段落太碎', 'soft',
                '好几段不足 35 字，一句一段读起来一顿一顿。语义相连的短句合并成完整段落。')
    if _kw(reason, '信息密度'):
        x = _n(reason, r'每百字[^0-9\-]{0,8}([\d.]+)', str, '?')
        return ('density', '内容偏虚', 'soft',
                f'每百字只有 {x} 个事实点（数字/机构/时间），读下来多是形容词。'
                '补具体数据——参与人数、投入金额、覆盖范围，比「高度重视、成效显著」有说服力。')
    if _kw(reason, '缺主体/引述'):
        return ('attrib', '新闻要素不全', 'soft',
                '没有「出席、主办、表示」这类主体表述，读者不知道这事是谁做的、谁说的。'
                '补一句主办方或负责人的身份与原话。')
    if _kw(reason, '未见时间信息'):
        return ('keyinfo', '缺比赛/活动时间', 'hard',
                '整篇没有时间点。预告类的读者只关心三件事：什么时候、在哪里、怎么办；'
                '缺一项就一定有人在留言区问。把赛程日期补进「赛程安排」里。')
    if _kw(reason, '未见地点信息'):
        return ('keyinfo2', '缺地点', 'hard',
                '没有写在哪办。外地参赛者看预告第一眼找的就是地点，补上校区/场馆。')
    if _kw(reason, '关键信息缺'):
        nm = reason.split('缺「')[1].split('」')[0] if '缺「' in reason else '关键信息'
        return ('keyinfo', f'缺{nm}', 'hard',
                f'整篇没有{nm}。预告类的读者只关心三件事：什么时候、在哪里、怎么办；'
                '缺一项就一定有人在留言区问。补上再发。')
    if _kw(reason, '分条编号'):
        return ('numbered', '通知没分条', 'soft',
                '通知类要让人一眼找到「我要做什么」。用「一、二、三」或「1. 2. 3.」分条，一条一件事。')
    if _kw(reason, '咨询/联系方式'):
        return ('contact', '没有联系方式', 'soft',
                '通知发出去一定有人问，正文里留咨询电话或联系人，能省掉后台一半留言。')
    if _kw(reason, '画面感'):
        return ('scenery', '画面感不够', 'soft',
                '景物词偏少，读起来更像总结而不是散文。把颜色、光影、动作写具体——'
                '「银杏叶落在台阶上」永远比「秋色很美」有画面。')
    if _kw(reason, '散文类偏短'):
        return ('scenerylen', '篇幅偏短', 'soft',
                '风景稿字数偏少，情绪还没铺开就结束了。补一两个细节段，或用图注式短句延长节奏。')
    if _kw(reason, '缺人物引述'):
        return ('quote', '人物没开口', 'soft',
                '人物稿的灵魂是「他自己说」。补一句直接引语，比第三人称概括可信十倍。')
    if _kw(reason, '缺具体经历'):
        return ('detail', '人物立不住', 'soft',
                '没有年份、次数、成果这类具体信息。补关键节点：哪年入职、带过几届、拿过什么奖。')
    if _kw(reason, '绝对化'):
        words = reason.split('：')[1] if '：' in reason else '最/第一/唯一'
        return ('absolute', '措辞过满', 'hard',
                f'出现「{words}」。教育号用「最/第一/唯一」既容易被平台判违规，也不符合客观表述，'
                '换成具体事实支撑。')
    if _kw(reason, '占位符'):
        words = reason.split('：')[1] if '：' in reason else 'XXX'
        return ('placeholder', '占位符没换', 'hard',
                f'「{words}」还留在稿子里。这是发布事故——必须换成真实信息再发。')
    if _kw(reason, '整句重复'):
        return ('dup', '有重复句', 'soft',
                '同一句话出现了两次，读者会以为是复制粘贴没检查。删掉后一次。')
    if _kw(reason, '图文比'):
        return ('imgratio', '图文节奏偏干', 'soft',
                '段落多、配图少，长时间看纯文字会累。每 2–4 段插一张图，给眼睛留休息点。')
    if _kw(reason, '段落数'):
        return ('paracount', '段落密度不合适', 'soft',
                '段落数偏离常规区间。手机上每次划屏约 3 段，太多显得碎，太少显得闷。')
    if _kw(reason, '平均句长'):
        x = _n(reason, r'句长\s*([\d.]+)', str, '?')
        return ('sentlen', '句子太长', 'soft',
                f'平均句长 {x} 字，读起来要憋气。40 字以上就该断句，逗号改句号，一句一个意思。')
    if _kw(reason, '首屏'):
        return ('firstscreen', '首屏没抓住人', 'soft',
                '开头 120 字内没有时间、事件或画面，读者第一眼不知道这篇讲什么。'
                '把最有信息量的一句提到最前。')
    if _kw(reason, '连续空段'):
        return ('blank', '有多余空段', 'soft',
                '存在连续空段落，发出来是一大片空白。删掉多余空行，留白用段间距控制。')
    if _kw(reason, '敏感表述'):
        return ('sensitive', '有敏感表述', 'hard',
                '命中敏感词，公众号有被限流或删文的风险。能换就换，换不了就删。')
    if _kw(reason, '纯黑'):
        return ('black', '纯黑文字', 'soft',
                '#000 纯黑在手机上对比过强，久看刺眼。改成 #3e3e3e 这类深灰。')
    return ('other', '其他问题', 'soft', reason)


def critique(r):
    issues, goods = [], []
    for dim in r['dims']:
        for it in dim['items']:
            key, title, sev, text = _issue_text(it['reason'], r)
            issues.append({'key': key, 'title': title, 'sev': sev, 'text': text,
                           'deduct': it['deduct'], 'dim': dim['name'], 'reason': it['reason']})
    issues.sort(key=lambda x: (0 if x['sev'] == 'hard' else 1, -x['deduct']))
    seen, dedup = set(), []
    for it in issues:
        if it['key'] in seen:
            continue
        seen.add(it['key'])
        dedup.append(it)
    issues = dedup

    dmap = {d['name']: d for d in r['dims']}
    if dmap['格式规范']['score'] == 30:
        goods.append('格式 30/30：字号、行距、字距、缩进、对齐全在位，这块不用动。')
    if not any(i['key'] == 'sign' for i in issues) and not any(i['key'] == 'reviewer' for i in issues):
        goods.append('落款五件套齐全，三审署名也对。')
    if not any(i['key'] in ('nohead', 'deco', 'leadtime') for i in issues):
        goods.append('开头干净：头图之后直接进导语，没有多余标题装饰。')
    if (not any(i['key'] == 'imgratio' for i in issues) and 2 <= r['stats']['images'] <= MAX_IMAGES
            and r['stats']['paragraphs'] / max(1, r['stats']['images']) <= 3):
        goods.append(f"图文比 {r['stats']['paragraphs']} 段 : {r['stats']['images']} 图，节奏是舒服的。")
    if not any(i['key'] == 'absolute' for i in issues):
        goods.append('全篇没有绝对化表述，措辞稳。')
    if not any(i['key'] == 'section' for i in issues) and r['stats'].get('sections', 0) >= 2:
        goods.append(f"分节 {r['stats']['sections']} 处，读者能快速定位。")

    bad = [d for d in r['dims'] if d['items']]
    weak = min(bad, key=lambda d: d['score'] / d['weight']) if bad else None
    hard = [i for i in issues if i['sev'] == 'hard']
    tail = {
        'A+': '下面几处顺手改掉就能直发。',
        'A': '清单不长，修掉前面两三条就可以发。',
        'B': '问题集中在一两个维度，按顺序改一遍就顺了。',
        'C': '先把硬伤解决，再谈润色。',
        'D': '建议按结构重排一遍，逐段重写比打补丁快。',
    }[r['grade']]
    if not issues:
        summary = (f"{r['total']} 分 · {r['grade']}（{r['verdict']}）· 判为{r['genre_name']}。"
                   '五维全满，没有可挑的地方，可以直发。发布前只剩两件事：'
                   '确认「编 辑」署名、把图片传进素材库。')
    elif weak:
        wk = [i for i in issues if i['dim'] == weak['name']]
        top2 = '、'.join(i['title'] for i in wk[:2]) or '细节不够'
        summary = (f"{r['total']} 分 · {r['grade']}（{r['verdict']}）· 判为{r['genre_name']}。"
                   f"最短板在「{weak['name']}」，具体是{top2}。" + tail)
    else:
        summary = (f"{r['total']} 分 · {r['grade']}（{r['verdict']}）· 判为{r['genre_name']}。" + tail)
    if r['total'] >= BASELINE:
        summary += f"（历史已发布稿中位 {BASELINE} 分，这篇在其上。）"

    return {'summary': summary, 'issues': issues, 'goods': goods,
            'hard_count': len(hard), 'soft_count': len(issues) - len(hard)}


def render_review(r, c):
    L = ['─' * 60, '  编辑点评', '─' * 60, f"  {c['summary']}", '']
    hard = [i for i in c['issues'] if i['sev'] == 'hard']
    soft = [i for i in c['issues'] if i['sev'] == 'soft']
    if hard:
        L.append(f'  ❗ 必须改（{len(hard)} 项）')
        for k, i in enumerate(hard, 1):
            L.append(f"   {k}. {i['title']}（-{i['deduct']}）")
            for seg in _wrap(i['text'], 52):
                L.append('      ' + seg)
    if soft:
        L.append('' if hard else None)
        L.append(f'  💡 可以更好（{len(soft)} 项）')
        for k, i in enumerate(soft, len(hard) + 1):
            L.append(f"   {k}. {i['title']}（-{i['deduct']}）")
            for seg in _wrap(i['text'], 52):
                L.append('      ' + seg)
    if c['goods']:
        L.append('')
        L.append('  ✅ 做得好的')
        for g in c['goods']:
            L.append('   · ' + g)
    L.append('─' * 60)
    out = []
    for x in L:
        if x == '' and (not out or out[-1] == ''):
            continue
        out.append(x)
    return out


def _wrap(text, width):
    out, line = [], ''
    for ch in text:
        line += ch
        if len(line) >= width and ch in '。；，、！？':
            out.append(line)
            line = ''
    if line:
        out.append(line)
    return out


def bar(got, full, width=18):
    filled = int(round(width * got / full)) if full else 0
    return '█' * filled + '░' * (width - filled)


def render_text(r):
    L = [('=' * 60),
         f"浙东院推文质量评分  v{r['version']}",
         f"文件: {os.path.basename(r['file'])}",
         '=' * 60,
         f"  稿型  {r['genre_name']}",
         f"  总分  {r['total']} / 100      等级 {r['grade']}    {r['verdict']}",
         '-' * 60]
    for dim in r['dims']:
        L.append(f"  {dim['name']:<6}{bar(dim['score'], dim['weight'])}  {dim['score']:>3}/{dim['weight']:<3}")
        for it in dim['items']:
            L.append(f"        -{it['deduct']:<2} {it['reason']}")
    L.append('-' * 60)
    st = r['stats']
    fs_txt = st['body_font_size']
    fs_txt = fs_txt if fs_txt == '未声明' else f'{fs_txt}px'
    L.append(f"  段落 {st['paragraphs']} | 图片 {st['images']} | 正文 {st['chars']} 字 | "
             f"字号 {fs_txt} | 体检致命 {st['fatal']} / 建议 {st['warn']}")
    L.append('=' * 60)
    L.extend(render_review(r, r['critique']))
    L.append('=' * 60)
    return '\n'.join(L)


def render_html(r, title='推文质量评分卡'):
    color = {'A+': '#1f9d55', 'A': '#3a8f4a', 'B': '#c9821a', 'C': '#cf6a32', 'D': '#c0392b'}[r['grade']]
    rows = []
    for dim in r['dims']:
        p = dim['score'] / dim['weight'] * 100
        items = ''.join(
            f'<li><span class="d">-{it["deduct"]}</span>{htmlmod.escape(it["reason"])}</li>'
            for it in dim['items']) or '<li class="ok">无扣分</li>'
        rows.append(f'''
        <div class="dim">
          <div class="dimhead"><b>{dim['name']}</b><span>{dim['score']} / {dim['weight']}</span></div>
          <div class="track"><div class="fill" style="width:{p:.0f}%"></div></div>
          <ul>{items}</ul>
        </div>''')
    c = r.get('critique') or critique(r)

    def items_html(items, cls):
        if not items:
            return ''
        rows = ''.join(
            f'<li class="{cls}"><div class="it"><b>{htmlmod.escape(i["title"])}</b>'
            f'<span class="d">-{i["deduct"]}</span></div>'
            f'<p>{htmlmod.escape(i["text"])}</p></li>' for i in items)
        return f'<ul class="cr">{rows}</ul>'

    hard = [i for i in c['issues'] if i['sev'] == 'hard']
    soft = [i for i in c['issues'] if i['sev'] == 'soft']
    rev_html = (
        f'<p class="summary">{htmlmod.escape(c["summary"])}</p>'
        + (f'<div class="grp hard">必须改 · {len(hard)} 项</div>' + items_html(hard, 'hard') if hard else '')
        + (f'<div class="grp soft">可以更好 · {len(soft)} 项</div>' + items_html(soft, 'soft') if soft else '')
        + (('<div class="grp good">做得好的</div><ul class="cr">'
            + ''.join(f'<li class="good"><p>{htmlmod.escape(g)}</p></li>' for g in c['goods'])
            + '</ul>') if c['goods'] else '')
    )
    st = r['stats']
    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{htmlmod.escape(title)}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;padding:32px 18px;background:#f2f5f9;font-family:-apple-system,"Microsoft YaHei",sans-serif;color:#22303f}}
.card{{max-width:760px;margin:0 auto;background:#fff;border-radius:18px;padding:28px 30px 34px;box-shadow:0 8px 30px rgba(32,87,146,.09)}}
h1{{font-size:19px;margin:0 0 4px;color:#205792}}
.sub{{font-size:13px;color:#8b98a8;word-break:break-all}}
.hero{{display:flex;align-items:center;gap:22px;margin:20px 0 4px}}
.score{{font-size:58px;font-weight:800;line-height:1;color:{color}}}
.score small{{font-size:18px;color:#9aa6b5;font-weight:500}}
.badge{{display:inline-block;background:{color};color:#fff;border-radius:999px;padding:5px 16px;font-size:14px;font-weight:700}}
.verdict{{font-size:13px;color:#6b7a8c;margin-top:8px}}
.genre{{display:inline-block;margin-top:16px;background:#eef4fb;color:#205792;border-radius:8px;padding:5px 12px;font-size:12.5px}}
.dim{{margin-top:18px;padding-top:14px;border-top:1px solid #eef2f7}}
.dimhead{{display:flex;justify-content:space-between;font-size:15px;margin-bottom:8px}}
.dimhead span{{color:#5b6b7d;font-variant-numeric:tabular-nums}}
.track{{height:8px;background:#eef2f7;border-radius:99px;overflow:hidden}}
.fill{{height:100%;background:linear-gradient(90deg,#205792,#4c8fd0);border-radius:99px}}
ul{{margin:10px 0 0;padding-left:0;list-style:none;font-size:13.5px;color:#4a5a6c}}
ul li{{padding:4px 0;line-height:1.6}}
.d{{display:inline-block;min-width:34px;color:#c0392b;font-weight:700;font-variant-numeric:tabular-nums}}
.ok{{color:#1f9d55}}
.stats{{margin-top:22px;background:#f6f9fd;border-radius:12px;padding:14px 16px;font-size:13px;color:#5b6b7d}}
.stats b{{color:#205792}}
h2{{font-size:15px;margin:26px 0 8px;color:#22303f}}
.summary{{font-size:14px;line-height:1.8;color:#3d4e60;background:#f6f9fd;border-left:3px solid #205792;border-radius:0 10px 10px 0;padding:12px 14px;margin:0 0 6px}}
.grp{{font-size:12.5px;font-weight:700;letter-spacing:.5px;margin:18px 0 6px;padding-left:10px;border-left:3px solid #d9e2ec}}
.grp.hard{{color:#c0392b;border-color:#e0877c}}
.grp.soft{{color:#b8791a;border-color:#e6c48a}}
.grp.good{{color:#1f9d55;border-color:#9ad2b3}}
.cr li{{border-bottom:1px dashed #eef2f7;padding:10px 0 12px}}
.cr .it{{display:flex;justify-content:space-between;align-items:baseline;font-size:14px;color:#22303f}}
.cr p{{margin:6px 0 0;font-size:13px;line-height:1.75;color:#5b6b7d}}
.cr li.good p{{color:#2f7a52}}
.foot{{margin-top:24px;font-size:11.5px;color:#a3aebb;text-align:center}}
</style></head><body>
<div class="card">
  <h1>浙东院推文质量评分卡</h1>
  <div class="sub">{htmlmod.escape(os.path.basename(r['file']))}</div>
  <div class="hero">
    <div class="score">{r['total']}<small>/100</small></div>
    <div><span class="badge">{r['grade']}</span><div class="verdict">{r['verdict']}</div></div>
  </div>
  <div class="genre">稿型判定：{r['genre_name']}（按此稿型适用评价标准）</div>
  {''.join(rows)}
  <h2>编辑点评</h2>
  {rev_html}
  <div class="stats">段落 <b>{st['paragraphs']}</b> · 图片 <b>{st['images']}</b> · 正文 <b>{st['chars']}</b> 字 ·
  正文字号 <b>{st['body_font_size']}</b> · 体检致命 <b>{st['fatal']}</b> / 建议 <b>{st['warn']}</b></div>
  <div class="foot">评价引擎 v{r['version']} · 浙东院推文 skill · 100 分制五维评分</div>
</div></body></html>'''


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    path = args[0]
    r = score(path)
    if '--json' in args:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif '--brief' in args:
        print(f"{r['grade']}  {r['total']}/100  {r['verdict']}  [{r['genre_name']}]")
    else:
        print(render_text(r))
    if '--html' in args:
        i = args.index('--html')
        out = args[i + 1] if len(args) > i + 1 else os.path.splitext(path)[0] + '.score.html'
        io.open(out, 'w', encoding='utf-8').write(render_html(r))
        print('评分卡已生成:', out)
    sys.exit(0 if r['total'] >= 80 else (1 if r['total'] >= 70 else 2))


if __name__ == '__main__':
    main()
