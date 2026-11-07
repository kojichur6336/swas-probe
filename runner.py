#!/usr/bin/env python3
"""海外（GitHub runner）→ 国内轻量服务器（对照实验）：
- high 组：同时向每台持续以 8 Mbps 发送（端口 5202，单条连接），每分钟一段，每 10 秒记一次速率。kind=steady。
- low 组：只在偶数分钟第 10 秒以 8 Mbps 探测 3 秒，尽量少走流量。kind=probe。
结果报给那台服务器自己记。
目标地址和上报令牌来自 secrets，不打印；跑满 350 分钟后退出，由排队中的下一次运行接上。"""
import json, os, subprocess, threading, time, urllib.request

TARGETS = json.loads(os.environ['TARGETS'])
TOKEN = os.environ['TOKEN']
RUN = os.environ.get('GITHUB_RUN_ID', '')
DEADLINE = time.time() + 350 * 60
MBPS = 8
stats = {'ok': 0, 'fail': 0}


def iperf(ip, seconds=55):
    # 55 秒：跨境建连、收尾要一两秒，58 秒会超过一分钟，错过下一个整分钟、变成两分钟一段
    cmd = ['iperf3', '-c', ip, '-p', '5202', '-t', str(seconds), '-b', f'{MBPS}M', '-i', '10', '-J', '--connect-timeout', '3000']
    try:
        j = json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=80).stdout)
    except Exception as e:
        return {'err': type(e).__name__}
    if 'error' in j:
        return {'err': 'iperf'}
    end = j['end']
    streams = end.get('streams', [])
    rtts = [s['sender'].get('mean_rtt') for s in streams if s.get('sender', {}).get('mean_rtt')]
    ivs = [i['sum']['bits_per_second'] / 1e6 for i in j.get('intervals', []) if i['sum'].get('seconds', 0) > min(5, seconds / 2)]
    return {
        'mbps': round(end['sum_received']['bits_per_second'] / 1e6, 2),
        'min10': round(min(ivs), 2) if ivs else None,
        'retr': end['sum_sent'].get('retransmits'),
        'rtt_ms': round(sum(rtts) / len(rtts) / 1000, 1) if rtts else None,
    }


def report(ip, record):
    req = urllib.request.Request(f'http://{ip}:8080/r', data=json.dumps(record).encode(), headers={'X-Token': TOKEN}, method='POST')
    try:
        urllib.request.urlopen(req, timeout=10).read()
        stats['ok'] += 1
    except Exception:
        stats['fail'] += 1


def loop(t):
    low = t.get('group') == 'low'
    while time.time() < DEADLINE:
        # low 组：偶数分钟第 10 秒探测 3 秒，避开轻量之间的探测时间（第 30–57 秒）
        start = (time.time() // 120 + 1) * 120 + 10 if low else (time.time() // 60 + 1) * 60 + 1
        time.sleep(max(0, start - time.time()))
        r = iperf(t['ip'], 3 if low else 55)
        r.update(kind='probe' if low else 'steady', ts=int(start), src='github', dst=t['name'], run=RUN)
        report(t['ip'], r)


threads = [threading.Thread(target=loop, args=(t,), daemon=True) for t in TARGETS]
for th in threads:
    th.start()
while any(th.is_alive() for th in threads):
    time.sleep(600)
    print(f'{time.strftime("%H:%M")} 已上报 {stats["ok"]}，上报失败 {stats["fail"]}', flush=True)
