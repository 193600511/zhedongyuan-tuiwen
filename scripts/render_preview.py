# -*- coding: utf-8 -*-
"""读稿点评第一步：把推文渲染成模拟公众号文章页并逐屏截图。

用法：
  python render_preview.py <article.html> <outdir> [标题] [账号名]

产出：
  <outdir>/渲染页.html      模拟公众号文章页（375 逻辑宽、账号栏/标题/meta/正文/操作栏）
  <outdir>/整页.png         全文一张长图（窗口 500 宽，内容 375 居中）
  <outdir>/screen1..N.png   按手机一屏 812px 逐屏截图（点评时逐屏看）

要点（实测坑）：
  - Chrome 无头最小窗宽 500，window-size 给 375 会截掉右侧 125px（伪"右对齐溢出"）；
    所以窗口一律 500 宽，页面 .page 375px 居中。
  - 总高用页面内嵌 JS 写进 <title>，再 --dump-dom 抓出来，避免猜高度截断正文。
"""
import io, math, os, re, subprocess, sys

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCREEN_H = 812  # iPhone 逻辑视口高

TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HEIGHT</title>
<style>
  html,body{margin:0;padding:0;background:#ededed;}
  body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased;}
  .page{width:375px;margin:0 auto;background:#fff;min-height:100vh;}
  .navbar{height:44px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid #f0f0f0;position:sticky;top:0;background:#fff;z-index:9;}
  .navbar .ic{width:20px;height:20px;border-radius:50%;background:#f2f2f2;}
  .navbar .dots{letter-spacing:2px;color:#333;font-size:17px;line-height:1;}
  .acctbar{display:flex;align-items:center;gap:9px;padding:12px 16px 4px;}
  .avatar{width:32px;height:32px;border-radius:6px;background:linear-gradient(135deg,#7a5c52,#d8a13a);}
  .acctname{font-size:14px;color:#576b95;font-weight:500;}
  .follow{margin-left:auto;font-size:12px;color:#fff;background:#576b95;border-radius:3px;padding:3px 10px;}
  .h1{font-size:22px;line-height:1.4;font-weight:700;color:#1a1a1a;margin:14px 16px 8px;letter-spacing:.2px;}
  .meta{font-size:15px;color:#8f8f8f;margin:0 16px 6px;}
  .meta .author{color:#576b95;}
  .meta .time{margin-left:8px;}
  .content{padding:10px 16px 24px;}
  .content p{margin:0;}
  .content section p{margin:0;}
  .content img{max-width:100%;height:auto;}
  .bottombar{display:flex;gap:26px;padding:18px 16px 30px;border-top:1px solid #f0f0f0;color:#8f8f8f;font-size:13px;}
  .bottombar span::before{content:"";display:inline-block;width:15px;height:15px;margin-right:5px;vertical-align:-2px;border:1.4px solid #c8c8c8;border-radius:50%;}
</style></head>
<body>
<div class="page">
  <div class="navbar"><div class="ic"></div><div class="dots">···</div></div>
  <div class="acctbar"><div class="avatar"></div><div class="acctname">__ACCT__</div><div class="follow">关注</div></div>
  <div class="h1">__TITLE__</div>
  <div class="meta"><span class="author">__ACCT__</span><span class="time">__DATE__</span></div>
  <div class="content">
__BODY__
  </div>
  <div class="bottombar"><span>赞</span><span>分享</span><span>在看</span><span>留言</span></div>
</div>
<script>
window.addEventListener('load', function(){
  document.title = 'HEIGHT:' + document.querySelector('.page').scrollHeight;
});
</script>
</body></html>"""


def chrome(args):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--virtual-time-budget=9000"] + args,
                   capture_output=True, timeout=120)


def file_url(path):
    return "file:///" + path.replace("\\", "/")


def main():
    src = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(src)) or "."
    title = sys.argv[3] if len(sys.argv) > 3 else os.path.splitext(os.path.basename(src))[0]
    acct = sys.argv[4] if len(sys.argv) > 4 else "浙江东方职业技术学院"
    date = sys.argv[5] if len(sys.argv) > 5 else "2026-11-05"
    os.makedirs(outdir, exist_ok=True)

    raw = io.open(src, encoding="utf-8", errors="ignore").read()
    body = re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()
    page_html = (TPL.replace("__TITLE__", title).replace("__ACCT__", acct)
                 .replace("__DATE__", date).replace("__BODY__", body))
    page_path = os.path.join(outdir, "渲染页.html")
    io.open(page_path, "w", encoding="utf-8").write(page_html)
    url = file_url(os.path.abspath(page_path))

    # 1) 抓内容总高
    dom = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=9000",
                          "--dump-dom", url], capture_output=True, timeout=120).stdout.decode("utf-8", "ignore")
    m = re.search(r"<title>HEIGHT:(\d+)</title>", dom)
    total = int(m.group(1)) if m else 4200
    if not m:
        total = 4200  # dump 失败按经验值，宁长勿短

    # 2) 整页长图
    chrome(["--window-size=500,%d" % (total + 40), "--screenshot=%s" % os.path.abspath(os.path.join(outdir, "整页.png")), url])

    # 3) 逐屏截图
    n = max(1, math.ceil(total / SCREEN_H))
    for i in range(n):
        h = src_html = page_html  # noqa
        sliced = page_html.replace("<body>\n<div class=\"page\">",
                                   "<body style=\"overflow:hidden;height:%dpx\">\n<div style=\"margin-top:%dpx\">\n<div class=\"page\">" % (SCREEN_H, -SCREEN_H * i))
        tmp = os.path.join(outdir, "_screen_tmp.html")
        io.open(tmp, "w", encoding="utf-8").write(sliced)
        chrome(["--window-size=500,%d" % SCREEN_H, "--screenshot=%s" % os.path.abspath(os.path.join(outdir, "screen%d.png" % (i + 1))), file_url(os.path.abspath(tmp))])
        os.remove(tmp)

    print("渲染页:", page_path)
    print("整页:   整页.png  (高 %dpx)" % total)
    print("逐屏:   screen1..%d.png  (每屏 %dpx)" % (n, SCREEN_H))


if __name__ == "__main__":
    main()
