# Máquina atacante do CyberLab.
# Leve (debian-slim) mas com o essencial para pentest + suas ferramentas Python.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Ferramentas clássicas de recon/exploração
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash bash-completion \
        nmap hydra curl wget netcat-openbsd socat \
        dnsutils iputils-ping iproute2 net-tools \
        openssh-client ftp telnet tcpdump \
        vim nano htop \
        less procps file \
    && rm -rf /var/lib/apt/lists/*

# neofetch saiu dos repositórios do bookworm — baixa o script oficial
RUN curl -fsSL https://raw.githubusercontent.com/dylanaraps/neofetch/7.1.0/neofetch \
        -o /usr/local/bin/neofetch \
    && chmod +x /usr/local/bin/neofetch

# Bibliotecas Python úteis para suas próprias ferramentas
RUN pip install \
        requests scapy paramiko impacket \
        beautifulsoup4 colorama rich

# Suas ferramentas ficam em /root/tools (volume montado pelo lab)
WORKDIR /root/tools

CMD ["sleep", "infinity"]
