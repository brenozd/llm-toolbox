// Suporte em L com furo de fixação — esqueleto do padrão desta skill:
// inputs mínimos no topo, tudo derivável calculado, assert nos mínimos,
// echo CHK para a revisão conferir, base apoiada em z=0.

// --- inputs (só o que vem da spec; nada de números soltos depois daqui) ---
w      = 40;    // largura [mm]
d      = 25;    // profundidade da base [mm]
h      = 30;    // altura da parede [mm]
wall   = 3.2;   // espessura da base/parede [mm]
hole_d = 4.2;   // Ø do furo de fixação (M4 folgado) [mm]
nozzle = 0.4;   // Ø do bico [mm]

$fn = $preview ? 32 : 64;

// ATENÇÃO: `pi` não existe em OpenSCAD — use a constante PI.
// sin()/cos() recebem GRAUS: rad → graus multiplicando por 180 / PI.

// --- derivados (calculados; não viram input) ---
hole_x  = w / 2;
hole_y  = d / 2;
hole_r  = hole_d / 2;
clear   = min(hole_x - hole_r, hole_y - hole_r);   // material até a borda
hole_z  = -wall;                                   // furo atravessa a base
hole_h  = 3 * wall;

assert(wall >= 2 * nozzle, "parede < 2*nozzle");
assert(hole_d >= 2 * nozzle, "furo < 2*nozzle: não sai redondo");

echo(str("CHK|wall=", wall, "|hole=", hole_d, "@0|clear=", clear, "|h=", h));

module body() {
  cube([w, d, wall]);                  // base
  cube([w, wall, h]);                  // parede vertical em y = 0
}

difference() {
  body();
  translate([hole_x, hole_y, hole_z]) cylinder(h = hole_h, d = hole_d);
}
