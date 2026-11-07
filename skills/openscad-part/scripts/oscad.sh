#!/bin/sh
# Roda o OpenSCAD disponível no host, sem instalar nada.
# Uso: oscad.sh <argumentos do openscad...>   (ex.: oscad.sh -o out/p.stl part.scad)
set -u

usage_hint() {
	cat >&2 <<'EOF'
[oscad.sh] OpenSCAD não encontrado. Instale uma destas opções e rode de novo:
  flatpak install flathub org.openscad.OpenSCAD
  # ou um container distrobox com openscad (veja skills/distrobox/SKILL.md)
Nada foi instalado automaticamente.
EOF
	exit 127
}

# 1) binário no PATH
if command -v openscad >/dev/null 2>&1 && openscad --version >/dev/null 2>&1; then
	exec openscad "$@"
fi

# 2) flatpak (sandbox só enxerga $HOME — mantenha os arquivos dentro de $HOME)
if command -v flatpak >/dev/null 2>&1 && flatpak info org.openscad.OpenSCAD >/dev/null 2>&1; then
	exec flatpak run org.openscad.OpenSCAD "$@"
fi

# 3) container distrobox sbx-* já existente com openscad
if command -v distrobox >/dev/null 2>&1 && command -v distrobox-list >/dev/null 2>&1; then
	for c in $(distrobox list 2>/dev/null | awk -F'|' 'NR>1 {gsub(/ /,"",$2); if ($2 ~ /^sbx-/) print $2}'); do
		if distrobox enter --name "$c" -- sh -c 'command -v openscad' >/dev/null 2>&1; then
			exec distrobox enter --name "$c" -- openscad "$@"
		fi
	done
fi

usage_hint
