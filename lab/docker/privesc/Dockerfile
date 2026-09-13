# Alvo médio 2: Linux com escalação de privilégio (você entra como 'dev' via SSH
# e precisa virar root). Vias: sudo mal configurado, cron com script gravável e
# permissões no filesystem.
FROM alpine:3.20

RUN apk add --no-cache openssh-server bash sudo busybox-suid procps coreutils \
    && ssh-keygen -A \
    && adduser -D -s /bin/bash dev && echo 'dev:dev123' | chpasswd \
    && echo 'root:toor' | chpasswd \
    && echo 'dev ALL=(root) NOPASSWD: /usr/bin/find' >> /etc/sudoers \
    && sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config \
    && echo 'CYBERLAB{pr1v3sc_l1nux}' > /root/flag.txt \
    && echo 'base de dados interna: admin / S3nh4D0Banco' > /home/dev/notes.txt \
    && chown dev:dev /home/dev/notes.txt \
    && echo '* * * * * sh /home/dev/backup.sh' > /etc/crontabs/root

# Script de "backup" executado pelo root a cada minuto — o dev pode editá-lo
COPY backup.sh /home/dev/backup.sh
RUN chmod 777 /home/dev/backup.sh && chown dev:dev /home/dev/backup.sh

EXPOSE 22
CMD ["sh", "-c", "crond && exec /usr/sbin/sshd -D -e"]