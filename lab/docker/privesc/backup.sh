#!/bin/sh
# Script de backup executado pelo root (cron) a cada minuto.
# É editável pelo usuário 'dev' -> vetor de escalação de privilégio.
echo "[backup] $(date) - nada a fazer" >> /tmp/backup.log