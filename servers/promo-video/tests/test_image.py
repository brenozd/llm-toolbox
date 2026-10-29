from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_image_ships_a_c_compiler():
    """A CLI demo may have to compile its sample program inside the exec container (the mint promo
    types `gcc -O0 -o leak leak.c` and runs it through mint_loader): the image needs gcc + headers,
    otherwise that capture fails with `gcc: command not found` and the run cannot be honest."""
    df = (ROOT / "Dockerfile").read_text()
    apt = [ln for ln in df.splitlines() if "apt-get install" in ln or ln.strip().startswith(("chromium ", "curl ", "gcc "))]
    joined = "\n".join(apt)
    assert "gcc" in joined and "libc6-dev" in joined, "Dockerfile must install gcc and libc6-dev"
