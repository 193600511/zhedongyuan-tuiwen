# -*- coding: utf-8 -*-
"""全量归档的使用入口：查、看、渲染。

用法：
  python render_archive.py list [关键词] [题材]        # 检索（编号/标题/字数/图/日期）
  python render_archive.py cat <编号|关键词>           # 打印正文 HTML（看 inline style 用）
  python render_archive.py render <编号|关键词> [outdir] [--no-shot]
                                                      # 解压 + 渲染成公众号长图与逐屏截图

为什么这样设计：
  归档每篇只存正文（gzip，全 342 篇共 1.7 MB）；要看长什么样时现场组装成
  render_preview.py 认的 article.html，再渲染 —— 既不撑爆 skill 体积，
  又能真看到"当年这篇长什么样"。
"""
import os, io, re, sys, gzip, json, subprocess

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AR = os.path.join(SKILL, 'assets', 'archive')
MAN = os.path.join(AR, 'manifest.json')
PY = sys.executable


def load():
    return json.load(io.open(MAN, encoding='utf-8'))


def resolve(recs, key):
    if key.isdigit():
        for r in recs:
            if r['id'] == int(key):
                return [r]
        return []
    k = key.lower()
    hit = [r for r in recs if k in r['title'].lower()]
    hit.sort(key=lambda r: -r['chars'])
    return hit


def read_body(rec):
    p = os.path.join(AR, rec['file'])
    with gzip.open(p, 'rb') as f:
        return f.read().decode('utf-8')


def cmd_list(recs, args):
    kw = args[0] if args else ''
    genre = args[1] if len(args) > 1 else ''
    rs = recs
    if kw:
        rs = [r for r in rs if kw.lower() in r['title'].lower()]
    if genre:
        rs = [r for r in rs if genre in r['genre']]
    rs = sorted(rs, key=lambda r: -r['chars'])
    print('命中 %d 篇' % len(rs))
    print('%-4s %-6s %-6s %-5s %-6s %s' % ('编号', '字数', '图数', '题材', '年份', '标题'))
    for r in rs[:60]:
        print('%-4d %-6d %-6d %-5s %-6s %s' % (
            r['id'], r['chars'], r['imgs'], r['genre'][:4], r['date'], r['title'][:46]))
    if len(rs) > 60:
        print('... 还有 %d 篇，缩小关键词' % (len(rs) - 60))


def cmd_cat(recs, key):
    hit = resolve(recs, key)
    if not hit:
        print('未找到:', key)
        return 2
    r = hit[0]
    if len(hit) > 1:
        print('/* 另有 %d 篇也匹配，本次输出：%d %s */' % (len(hit) - 1, r['id'], r['title']))
    out = '<title>%s</title>\n<!-- id=%d 字数=%d 图=%d 日期=%s -->\n%s' % (
        r['title'], r['id'], r['chars'], r['imgs'], r['date'], read_body(r))
    print(out)
    return 0


def cmd_render(recs, key, outdir=None, shots=True):
    hit = resolve(recs, key)
    if not hit:
        print('未找到:', key)
        return 2
    r = hit[0]
    if len(hit) > 1:
        print('/* 另有 %d 篇也匹配（%s）— 要别的就传编号 */' % (
            len(hit) - 1, '、'.join(str(x['id']) for x in hit[1:6])))
    if not outdir:
        slug = re.sub(r'[\\/:*?"<>|\s\u3000]+', '', r['title'])[:20]
        outdir = os.path.join(os.getcwd(), '案例渲染', '%03d-%s' % (r['id'], slug))
    os.makedirs(outdir, exist_ok=True)
    art = os.path.join(outdir, '%03d.html' % r['id'])
    io.open(art, 'w', encoding='utf-8').write(read_body(r))
    print('案例: %d %s（%d 字 / %d 图 / %s）' % (r['id'], r['title'], r['chars'], r['imgs'], r['date']))
    print('正文:', art)
    if not shots:
        return 0
    rp = os.path.join(SKILL, 'scripts', 'render_preview.py')
    rc = subprocess.run([PY, rp, art, outdir, r['title'], '浙江东方职业技术学院',
                         r['date'] or '2026-11-05'], capture_output=True, text=True)
    print(rc.stdout.strip())
    if rc.returncode != 0:
        print('[渲染失败]', rc.stderr.strip()[-400:])
        return rc.returncode
    print('看图:', os.path.join(outdir, '整页.png'), '及 screen*.png')
    return 0


def main():
    if not os.path.exists(MAN):
        print('缺少 manifest.json，先跑 scripts/build_archive.py')
        return 1
    recs = load()
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    mode = sys.argv[1]
    args = [a for a in sys.argv[2:] if not a.startswith('--')]
    if mode == 'list':
        cmd_list(recs, args)
        return 0
    if mode == 'cat':
        return cmd_cat(recs, args[0]) if args else 2
    if mode == 'render':
        if not args:
            print('用法: render <编号|关键词> [outdir] [--no-shot]')
            return 2
        return cmd_render(recs, args[0], args[1] if len(args) > 1 else None,
                          shots='--no-shot' not in sys.argv)
    print('未知模式:', mode)
    return 2


if __name__ == '__main__':
    sys.exit(main())
