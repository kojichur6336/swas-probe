#!/usr/bin/env python3
"""海外（GitHub runner）→ 国内轻量服务器测速：每分钟依次向每台发 3 秒，结果报给那台服务器自己记。
目标地址和上报令牌来自 secrets，不打印；跑满 350 分钟后退出，由排队中的下一次运行接上。"""
import json, os, subprocess, time, urllib.request

TARGETS = json.loads(os.environ['TARGETS'])
TOKEN = os.environ['TOKEN']
RUN = os.environ.get('GITHUB_RUN_ID', '')
DEADLINE = time.time() + 350 * 60


def iperf(ip):
    cmd = ['iperf3', '-c', ip, '-p', '5202', '-t', '3', '-P', '4', '-J', '--connect-timeout', '5000']
    try:
        j = json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=25).stdout)
    except Exception as e:
        return {'err': type(e).__name__}
    if 'error' in j:
        return {'err': 'iperf'}
    end = j['end']
    streams = end.get('streams', [])
    rtts = [s['sender'].get('mean_rtt') for s in streams if s.get('sender', {}).get('mean_rtt')]
    per = [s['receiver']['bits_per_second'] / 1e6 for s in streams if 'receiver' in s]
    return {
        'mbps': round(end['sum_received']['bits_per_second'] / 1e6, 2),
        'min1': round(min(per), 2) if per else None,
        'retr': end['sum_sent'].get('retransmits'),
        'rtt_ms': round(sum(rtts) / len(rtts) / 1000, 1) if rtts else None,
    }


def report(ip, record):
    req = urllib.request.Request(f'http://{ip}:8080/r', data=json.dumps(record).encode(), headers={'X-Token': TOKEN}, method='POST')
    try:
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception:
        return False


ok = fail = 0
while time.time() < DEADLINE:
    time.sleep(60 - time.time() % 60)
    for t in TARGETS:
        r = iperf(t['ip'])
        r.update(ts=int(time.time()), src='github', dst=t['name'], run=RUN)
        if report(t['ip'], r):
            ok += 1
        else:
            fail += 1
    print(f'{time.strftime("%H:%M")} 已上报 {ok}，上报失败 {fail}', flush=True)
