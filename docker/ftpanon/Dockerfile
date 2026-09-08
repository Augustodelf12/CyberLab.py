# Alvo 3: FTP com acesso anônimo e arquivos "sensíveis" expostos.
FROM alpine:3.20

RUN apk add --no-cache vsftpd \
    && mkdir -p /srv/ftp/pub \
    && printf 'admin:Sup3rS3cret!2024\nbackup:backup123\n' > /srv/ftp/passwords.txt \
    && printf 'CREATE TABLE users(id, username, password);\nINSERT INTO users VALUES(1, "admin", "Sup3rS3cret!2024");\n' > /srv/ftp/pub/backup.sql \
    && echo 'CYBERLAB{ftp_4n0nym0us_l00t}' > /srv/ftp/pub/flag.txt

COPY vsftpd.conf /etc/vsftpd/vsftpd.conf

EXPOSE 21
CMD ["/usr/sbin/vsftpd", "/etc/vsftpd/vsftpd.conf"]
