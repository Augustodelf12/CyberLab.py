# Alvo 2: servidor SSH com credenciais fracas (treino de brute-force / password spraying).
FROM alpine:3.20

RUN apk add --no-cache openssh-server \
    && ssh-keygen -A \
    && echo 'root:toor' | chpasswd \
    && adduser -D admin   && echo 'admin:admin'       | chpasswd \
    && adduser -D user    && echo 'user:password'     | chpasswd \
    && adduser -D backup  && echo 'backup:backup123'  | chpasswd \
    && echo 'CYBERLAB{ssh_brut3_f0rc3_w1n}' > /root/flag.txt \
    && sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/'           /etc/ssh/sshd_config \
    && sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-e"]
