# Alvo médio 1: loja web realista ("TechVerse Shop") com múltiplas falhas.
FROM python:3.12-alpine

RUN pip install --no-cache-dir flask

WORKDIR /app
COPY app.py .

# Segredo do alvo (objetivo final do lab)
RUN echo 'CYBERLAB{sh0p_rce_m3dium}' > /flag.txt

EXPOSE 80
CMD ["python", "app.py"]