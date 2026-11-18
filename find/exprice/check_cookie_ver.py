import sqlite3
p = 'file:C:/Users/sanjin/AppData/Local/Microsoft/Edge/User Data/Default/Network/Cookies?mode=ro&immutable=1'
conn = sqlite3.connect(p, uri=True)
cur = conn.cursor()
cur.execute("SELECT host_key, name, length(encrypted_value), hex(substr(encrypted_value,1,3)) AS pref, expires_utc FROM cookies WHERE host_key LIKE '%douyin%' OR host_key LIKE '%bilibili%' OR host_key LIKE '%zhihu%' OR host_key LIKE '%tieba%' OR host_key LIKE '%xiaohongshu%' OR host_key LIKE '%weibo%' OR host_key LIKE '%kuaishou%' ORDER BY host_key, name")
rows = cur.fetchall()
from collections import Counter
pref_count = Counter()
key_names = {'SESSDATA', 'bili_jct', 'DedeUserID', 'sid_guard', 'sid_tt', 'uid_tt', 'sessionid', 'sessionid_ss', 'd_ticket', 'ttwid', 'passport_csrf_token', 'web_session', 'z_c0', 'SUB', 'SUBP', 'BDUSS', 'stoken', 'xiaohongshu.web_session'}
print(f'共 {len(rows)} 条目标平台 cookie:')
for h, n, ln, pref, exp in rows:
    ver = bytes.fromhex(pref).decode('ascii', errors='replace')
    pref_count[ver] += 1
    mark = ' <<<' if n in key_names else ''
    print(f'  {h:30s} {n:25s} v={ver} len={ln} exp={exp}{mark}')
print()
print('加密版本统计:', dict(pref_count))
conn.close()
