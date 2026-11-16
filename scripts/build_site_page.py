"""生成 bbxx365 的站点页面。

上游站点有两种做法：
  1) `/list/xxx.list` 由前端 SPA 拉取 `/list/xxx.md` 再渲染；
  2) 页面内容来自服务端函数（本站是纯静态上传，没有函数）。

这里直接产出**独立的 HTML 文件** `list/bbxx365.list`，点开即渲染，不依赖
前端二次请求，也不依赖 CDN 上的 marked.js；同时保留 .md 供其他入口使用。
样式复用站点自己的 `/style.css`（`.file-item` `.ext` `.copy-btn` `.table-wrap`），
外观与原站点列表页一致。
"""

import os

OUT_DIR = "m3u/list"
PAGE = os.path.join(OUT_DIR, "bbxx365.list")
MD = os.path.join(OUT_DIR, "bbxx365.md")

FILES = [
    ("bbxx365_mini_home.m3u", "家用实测版（推荐）", "只留能播的源，每台最多 10 条，按实际起播速度排序"),
    ("bbxx365_mini.m3u", "云端精编版", "云端验活 + 按源类型排序，每台 5 条"),
    ("bbxx365_hotel.m3u", "央视 · 卫视 · 酒店合并版", "白名单合并，未验活"),
    ("bbxx365_lite.m3u", "上游瘦身版", "只保留优质组合，未验活"),
    ("bbxx365.m3u", "全集", "全部抓取结果，未验活、未测速"),
]

COPY_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/>'
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
)
CHECK_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>'
)


def count_entries(path):
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for ln in f if ln.startswith("#EXTINF"))
    except FileNotFoundError:
        return None


def chip(url, filename):
    """一个文件入口：扩展名胶囊 + 文件名 + 复制按钮（与站点渲染结果同构）。"""
    ext = filename.rsplit(".", 1)[-1]
    stem = filename[: -(len(ext) + 1)]
    return (
        f'<span class="file-item"><a href="{url}" title="{url}">'
        f'<span class="ext">{ext}</span>{stem}</a>'
        f'<button type="button" class="copy-btn" data-copy="{url}" '
        f'aria-label="复制链接" title="复制链接">{COPY_ICON}</button></span>'
    )


def build_rows():
    rows = []
    for filename, title, desc in FILES:
        n = count_entries(os.path.join("m3u", filename))
        count = str(n) if n else "—"
        cells = [chip(f"/{filename}", filename)]
        txt = filename[: -len(".m3u")] + ".txt"
        if os.path.exists(os.path.join("m3u", txt)):
            cells.append(chip(f"/{txt}", txt))
        rows.append(
            "<tr>"
            f'<td>{title}</td><td>{" ".join(cells)}</td><td>{desc}</td>'
            f'<td class="col-count">{count}</td></tr>'
        )
    return "\n".join(rows)


HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#4f46e5">
<title>bbxx365 · IPTV Sources</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#128250;</text></svg>">
<script>try{var t=localStorage.getItem('theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t;}catch(e){}</script>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="/">
      <span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="m17 2-5 5-5-5"/></svg></span>
      <span class="brand-text">IPTV Sources</span>
    </a>
    <nav class="nav" aria-label="主导航">
      <a href="/">首页</a>
      <a href="/list/iptv.list">运营商 IPTV</a>
      <a href="/list/bbxx365.list" class="is-active">bbxx365</a>
    </nav>
    <div class="header-actions">
      <button class="icon-btn" id="theme-toggle" type="button" aria-label="切换主题" title="切换主题"></button>
      <a class="icon-btn" href="https://github.com/yunnysunny/iptv-sources" target="_blank" rel="noopener" aria-label="GitHub 仓库" title="GitHub 仓库">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.36-3.88-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42-2.69 5.39-5.26 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z"/></svg>
      </a>
    </div>
  </div>
</header>
<div class="layout">
  <div class="panel">
    <main class="content">
      <h1>bbxx365</h1>
      <p>本站自建的直播源，与上游源并行生成。文件由 GitHub Actions 定时更新，家用实测版只在家庭网络生成时刷新。</p>
      <div class="table-block">
        <div class="table-wrap">
          <table>
            <thead><tr><th>名称</th><th>url</th><th>说明</th><th class="col-count">条数</th></tr></thead>
            <tbody>
__ROWS__
            </tbody>
          </table>
        </div>
      </div>
      <p><a href="/">返回首页</a> · <a href="/list/iptv.list">运营商 IPTV</a></p>
    </main>
  </div>
</div>
<footer class="site-footer">
  <div class="footer-inner">
    <span>直播源与 EPG 由 GitHub Actions 定时自动更新</span>
    <span>GPL-3.0 &copy; <a href="https://github.com/yunnysunny/iptv-sources" target="_blank" rel="noopener">yunnysunny/iptv-sources</a></span>
  </div>
</footer>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<script>
(function () {
  var CHECK = '__CHECK__';
  var COPY = document.querySelector('.copy-btn') ? document.querySelector('.copy-btn').innerHTML : '';
  function toast(msg) {
    var t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg; t.classList.add('show');
    clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove('show'); }, 1600);
  }
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('.copy-btn');
    if (!btn) return;
    var text = btn.getAttribute('data-copy');
    var done = function () {
      btn.classList.add('copied');
      var old = btn.innerHTML; btn.innerHTML = CHECK;
      setTimeout(function () { btn.classList.remove('copied'); btn.innerHTML = old; }, 1400);
      toast('链接已复制');
    };
    if (navigator.clipboard) { navigator.clipboard.writeText(text).then(done, done); }
    else {
      var a = document.createElement('textarea'); a.value = text; a.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(a); a.select();
      try { document.execCommand('copy'); done(); } catch (err) { toast('复制失败，请长按链接'); }
      a.remove();
    }
  });
  // 主题切换
  var btn = document.getElementById('theme-toggle');
  var root = document.documentElement;
  function sync() { btn.innerHTML = (root.dataset.theme === 'light') ? '__SUN__' : '__MOON__'; }
  btn.addEventListener('click', function () {
    root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('theme', root.dataset.theme); } catch (e) {}
    sync();
  });
  sync();
})();
</script>
</body>
</html>
"""

SUN = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
       'stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4'
       'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>')
MOON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>')


def main():
    rows = build_rows()
    html = (HTML.replace("__ROWS__", rows)
                .replace("__CHECK__", CHECK_ICON.replace("'", "\\'"))
                .replace("__SUN__", SUN)
                .replace("__MOON__", MOON))
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write(html)

    md_rows = []
    for filename, title, desc in FILES:
        n = count_entries(os.path.join("m3u", filename))
        links = f"[{filename}](/{filename})"
        txt = filename[: -len(".m3u")] + ".txt"
        if os.path.exists(os.path.join("m3u", txt)):
            links += f" <br> [{txt}](/{txt})"
        md_rows.append(f"| {title} | {links} | {desc} | {n if n else '—'} |")
    with open(MD, "w", encoding="utf-8") as f:
        f.write("\n".join([
            "# bbxx365 订阅地址", "",
            "| 名称 | url | 说明 | 条数 |", "| --- | --- | --- | --- |",
            *md_rows, "",
        ]))
    print(f"已生成 {PAGE} 和 {MD}")


if __name__ == "__main__":
    main()
