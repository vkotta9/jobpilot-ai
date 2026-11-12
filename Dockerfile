FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 JOBPILOT_DATA_DIR=/data
WORKDIR /app

# LaTeX, so resumes uploaded as .tex / Overleaf .zip are tailored in their own source and compiled with pdflatex.
# Covers common resume templates (titlesec, enumitem, marvosym, fullpage, hyperref, xcolor, fontenc T1 fonts).
RUN apt-get update \
 && apt-get install -y --no-install-recommends texlive-latex-base texlive-latex-recommended texlive-latex-extra \
    texlive-fonts-recommended lmodern cm-super-minimal \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/texmf/doc /usr/share/texlive/texmf-dist/doc

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY frontend frontend
COPY extension extension

RUN useradd --create-home --uid 1000 jobpilot && mkdir -p /data && chown jobpilot /data
USER jobpilot

WORKDIR /app/backend
EXPOSE 8000
ENV PORT=8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health')"
# --forwarded-allow-ips='*' so cookies are marked Secure behind the host's HTTPS proxy
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
