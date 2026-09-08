"""
Caminhos do CyberLab: separa assets embutidos (dentro do pacote) de dados
do usuário (home), para o projeto funcionar instalado via pip/pipx.

- ``ASSETS_DIR``: Dockerfiles dos alvos/atacante (embutidos no pacote).
- ``user_data_dir()``: registry.json + ferramentas sincronizadas do usuário.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Dockerfiles embutidos no pacote (sobrevivem ao `pip install`)
ASSETS_DIR = Path(__file__).resolve().parent / "docker"

# Exemplos de ferramentas (copiados para o data dir no primeiro setup)
EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"


def user_data_dir() -> Path:
    """Diretório de dados do usuário (cross-platform, segue convenções)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "CyberLab"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "cyberlab"


def ensure_user_dirs() -> Path:
    data = user_data_dir()
    (data / "tools").mkdir(parents=True, exist_ok=True)
    return data