#!/usr/bin/env python3
"""
Exemplo de ferramenta própria: scanner de portas TCP simples (connect scan).

Esta pasta é montada em /root/tools dentro da máquina atacante — edite aqui
no host e rode lá dentro:

    python3 portscan.py 172.30.0.2 1-1024

Substitua/crie os seus scanners, bruteforcers, fuzzers… da mesma forma.
"""
import socket
import sys
from concurrent.futures import ThreadPoolExecutor


def scan_port(host: str, port: int, timeout: float = 0.7) -> int | None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        if s.connect_ex((host, port)) == 0:
            return port
    return None


def main() -> int:
    if len(sys.argv) != 3:
        print(f"uso: {sys.argv[0]} <host> <faixa início-fim>")
        return 2
    host = sys.argv[1]
    start, end = map(int, sys.argv[2].split("-", 1))
    found: list[int] = []
    with ThreadPoolExecutor(max_workers=100) as pool:
        for port in pool.map(lambda p: scan_port(host, p), range(start, end + 1)):
            if port is not None:
                found.append(port)
                print(f"[+] {host}:{port} aberta")
    print(f"\n{len(found)} porta(s) aberta(s) em {host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
