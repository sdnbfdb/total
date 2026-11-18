import subprocess, time, os, re, json

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
UD = r"C:\Users\sanjin\AppData\Local\Microsoft\Edge\User Data"
NETLOG = r"C:\Users\sanjin\Desktop\find\exprice\data-samples\netlog_capture.json"
OUT = r"C:\Users\sanjin\Desktop\find\exprice\data-samples\cookies_by_domain.json"

URLS = [
    "https://www.bilibili.com/",
    "https://www.bilibili.cn/",
    "https://www.douyin.com/",
    "https://www.zhihu.com/",
    "https://www.xiaohongshu.com/",
    "https://weibo.com/",
    "https://weibo.cn/",
    "https://tieba.baidu.com/",
    "https://www.kuaishou.com/",
]

print("== 清理旧 Edge 进程 ==")
subprocess.run("taskkill /F /IM msedge.exe", shell=True, capture_output=True)
time.sleep(2)
if os.path.exists(NETLOG):
    os.remove(NETLOG)

print("== 启动 Edge 抓取 netlog ==")
args = [
    EDGE,
    f"--user-data-dir={UD}",
    f"--log-net-log={NETLOG}",
    "--net-log-capture-mode=IncludeSensitive",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    *URLS,
]
proc = subprocess.Popen(args)
print("已启动, 等待 35 秒让页面请求发出...")
time.sleep(35)

print("== 关闭 Edge ==")
subprocess.run("taskkill /F /IM msedge.exe", shell=True, capture_output=True)
time.sleep(3)

if not os.path.exists(NETLOG):
    print("netlog 文件不存在!"); raise SystemExit(1)
print(f"netlog 大小: {os.path.getsize(NETLOG)/1048576:.1f} MB")

print("== 解析 Cookie 头 ==")
text = open(NETLOG, encoding="utf-8", errors="replace").read()

def unesc(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s

collected = {}  # host -> {cookie_name: value}
for m in re.finditer(r'"headers":\[(.*?)\]', text, re.S):
    strs = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
    host = cookie = None
    for raw in strs:
        s = unesc(raw)
        low = s.lower()
        if low.startswith("host:") or low.startswith(":authority:"):
            host = s.split(":", 1)[1].strip() if low.startswith("host:") else s.split(":", 2)[2].strip()
        elif low.startswith("cookie:"):
            cookie = s.split(":", 1)[1].strip()
    if host and cookie:
        jar = collected.setdefault(host, {})
        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                jar[k.strip()] = v.strip()

print(f"命中 {len(collected)} 个域名:")
for h, jar in sorted(collected.items()):
    print(f"  {h}: {len(jar)} 个 cookie -> {', '.join(list(jar)[:8])}{'...' if len(jar)>8 else ''}")

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(collected, f, ensure_ascii=False, indent=1)
print("已保存:", OUT)
