# Alvo 1: aplicação web intencionalmente vulnerável (SQLi, XSS, LFI, command injection).
FROM python:3.12-alpine

RUN pip install --no-cache-dir flask

WORKDIR /app
COPY app.py .

# "Segredo" do alvo, para objetivos de CTF
RUN echo 'CYBERLAB{w3b_pwn3d_c0ngr4tz}' > /flag.txt

EXPOSE 80
CMD ["python", "app.py"]
