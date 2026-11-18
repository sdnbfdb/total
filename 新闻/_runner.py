# -*- coding: utf-8 -*-
"""新闻服务后台启动器：负责检查 5000 端口、停旧进程、用 pythonw 无窗口启动 app.py 并写日志"""
import os
import sys
import time
import subprocess
import re

PROJ    = os.path.dirname(os.path.abspath(__file__))
APP     = os.path.join(PROJ, "app.py")
LOG     = os.path.join(PROJ, "service.log")
PYTHON  = sys.executable                    # 本启动器所用 python -> C:\...python.exe
# pythonw.exe 与 python.exe 在同一目录
PYTHONW = os.path.join(os.path.dirname(PYTHON), "pythonw.exe")

def find_pid_on_port(port):
    try:
        out = subprocess.check_output(["netstat", "-ano"], stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[!] netstat 失败: {e}")
        return []
    pids = []
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            m = re.search(r"(\d+)\s*$", line.strip())
            if m:
                pid = int(m.group(1))
                if pid and pid not in pids:
                    pids.append(pid)
    return pids

def kill_pid(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        return True
    except Exception:
        return False

def append_log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line.strip())

def main():
    print("=" * 50)
    print(f"[*] 工作目录: {PROJ}")
    print(f"[*] pythonw:  {PYTHONW}")
    append_log(f"------ 服务启动器执行  PID={os.getpid()} ------")

    # 1) 停旧进程
    pids = find_pid_on_port(5000)
    if pids:
        for pid in pids:
            print(f"[!] 端口 5000 被 PID {pid} 占用，正在强制关闭...")
            ok = kill_pid(pid)
            append_log(f"终止旧进程 PID={pid} -> {'OK' if ok else 'FAIL'}")
        time.sleep(2)
        # 二次确认
        still = find_pid_on_port(5000)
        if still:
            print(f"[WARN] 仍有进程占用: {still}")
    else:
        print("[*] 5000 端口空闲。")

    # 2) 用 pythonw 启动 app.py，stdout/stderr 写到日志
    log_fd = open(LOG, "a", encoding="utf-8", buffering=1)
    try:
        print("[+] 启动 pythonw app.py （后台无窗口）...")
        # pythonw 本身无控制台，这里用 CREATE_NO_WINDOW + 重定向到日志文件
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        flags = CREATE_NO_WINDOW | DETACHED_PROCESS
        p = subprocess.Popen(
            [PYTHON if not os.path.exists(PYTHONW) else PYTHONW, APP],
            cwd=PROJ,
            stdout=log_fd,
            stderr=log_fd,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
        )
        append_log(f"已 spawn Flask 子进程 PID={p.pid}")
        time.sleep(3)
        # 检查子进程是否还活着 & 端口是否起来
        alive = (p.poll() is None)
        pids_after = find_pid_on_port(5000)
        if alive and pids_after:
            append_log(f"[OK] 服务启动成功。监听 PID={pids_after}")
            print(f"[√] 服务启动成功！PID={pids_after}")
            print("    访问 http://127.0.0.1:5000/")
            print(f"    日志: {LOG}")
        else:
            append_log(f"[FAIL] 服务可能启动失败。poll={p.poll()}  5000监听={pids_after}")
            print("[X] 启动失败。请查看日志尾部：")
            try:
                with open(LOG, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-12:]
                    for ln in lines:
                        print("   ", ln.rstrip())
            except Exception as e:
                print(f"   读日志失败: {e}")
    finally:
        try:
            log_fd.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
