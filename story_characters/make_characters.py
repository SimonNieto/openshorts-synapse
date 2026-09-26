import os

OUT_DIR = r"C:\Users\mel&sim\Documents\OpenShorts\story_characters"
os.makedirs(OUT_DIR, exist_ok=True)

INK = "#151515"
S = f'stroke="{INK}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"'


def face(expr, cx=100, cy=72, spread=10, glasses=False):
    """Eyes + mouth for one expression."""
    out = []
    lx, rx = cx - spread, cx + spread
    if expr == "shocked" and not glasses:
        for x in (lx, rx):
            out.append(f'<circle cx="{x}" cy="{cy}" r="6.5" fill="#fff" stroke="{INK}" stroke-width="3"/>')
            out.append(f'<circle cx="{x}" cy="{cy}" r="2.6" fill="{INK}"/>')
    else:
        for x in (lx, rx):
            out.append(f'<circle cx="{x}" cy="{cy}" r="3.6" fill="{INK}"/>')
    my = cy + 16
    if expr == "shocked":
        out.append(f'<ellipse cx="{cx}" cy="{my + 2}" rx="6" ry="8" fill="{INK}"/>')
    elif expr == "point":
        out.append(f'<path d="M{cx - 10},{my - 2} Q{cx},{my + 9} {cx + 10},{my - 2}" fill="none" {S} stroke-width="4"/>')
    else:
        out.append(f'<path d="M{cx - 8},{my} Q{cx},{my + 4} {cx + 8},{my}" fill="none" {S} stroke-width="4"/>')
    return "".join(out)


def shock_marks(cx=100, top=30):
    return (f'<path d="M{cx + 42},{top + 8} l10,-12 M{cx + 50},{top + 22} l14,-4 M{cx - 42},{top + 8} l-10,-12" '
            f'fill="none" {S} stroke-width="4"/>')


def price_tag(x=178, y=104, text="$1.50", color="#151515"):
    return (f'<g transform="rotate(-6 {x} {y})"><rect x="{x - 30}" y="{y - 20}" width="62" height="32" rx="6" '
            f'fill="#fff" {S} stroke-width="3.5"/>'
            f'<text x="{x + 1}" y="{y + 3}" text-anchor="middle" font-family="Comic Neue, Comic Sans MS, cursive" '
            f'font-weight="700" font-size="19" fill="{color}">{text}</text></g>')


def stick_body(pose, sx=100, sy=108, hip=175):
    """Stick body from the neck (sx, sy): shoulders ~12px below."""
    sh = sy + 12
    parts = [f'<path d="M{sx},{sy} L{sx},{hip}" {S} fill="none"/>',
             f'<path d="M{sx},{hip} L{sx - 18},{hip + 50} M{sx},{hip} L{sx + 18},{hip + 50}" {S} fill="none"/>']
    if pose == "shocked":
        # Elbows out, hands up: straight-up arms disappear behind the head.
        parts.append(f'<path d="M{sx},{sh} L{sx - 36},{sh - 8} L{sx - 46},{sh - 40} '
                     f'M{sx},{sh} L{sx + 36},{sh - 8} L{sx + 46},{sh - 40}" {S} fill="none"/>')
    elif pose == "point":
        parts.append(f'<path d="M{sx},{sh} L{sx - 22},{sh + 36} M{sx},{sh} L{sx + 58},{sh - 10}" {S} fill="none"/>')
    else:
        parts.append(f'<path d="M{sx},{sh} L{sx - 24},{sh + 36} M{sx},{sh} L{sx + 24},{sh + 36}" {S} fill="none"/>')
    return "".join(parts)


# --- the four characters -----------------------------------------------------

def casey(pose):
    """Everyman consumer: round head, yellow cap."""
    cap = ('<path d="M68,66 A32,32 0 0 1 132,66 Z" fill="#F5B700" ' + S + ' stroke-width="4.5"/>'
           '<path d="M128,64 Q150,62 158,70 L128,70 Z" fill="#F5B700" ' + S + ' stroke-width="4.5"/>')
    head = f'<circle cx="100" cy="72" r="32" fill="#fff" {S}/>'
    extra = shock_marks() if pose == "shocked" else price_tag() if pose == "point" else ""
    return stick_body(pose, sy=104) + head + cap + face(pose, cy=80) + extra


def penny(pose):
    """The money mascot: head is a gold coin."""
    head = (f'<circle cx="100" cy="72" r="34" fill="#F2C230" {S}/>'
            f'<circle cx="100" cy="72" r="26" fill="none" stroke="{INK}" stroke-width="2.2" stroke-dasharray="3 5"/>')
    extra = shock_marks() if pose == "shocked" else price_tag() if pose == "point" else ""
    return stick_body(pose, sy=106) + head + face(pose, cy=70) + extra


def prof(pose):
    """The explainer: rounded-square head, round glasses, red scarf."""
    head = f'<rect x="66" y="38" width="68" height="66" rx="20" fill="#fff" {S}/>'
    glasses = (f'<circle cx="88" cy="70" r="11" fill="#fff" stroke="{INK}" stroke-width="3.2"/>'
               f'<circle cx="112" cy="70" r="11" fill="#fff" stroke="{INK}" stroke-width="3.2"/>'
               f'<path d="M99,70 L101,70" stroke="{INK}" stroke-width="3.2"/>')
    eyes = "".join(f'<circle cx="{x}" cy="70" r="{4.2 if pose == "shocked" else 3.3}" fill="{INK}"/>' for x in (88, 112))
    my = 90
    mouth = (f'<ellipse cx="100" cy="{my + 2}" rx="5" ry="7" fill="{INK}"/>' if pose == "shocked" else
             f'<path d="M91,{my - 1} Q100,{my + 8} 109,{my - 1}" fill="none" {S} stroke-width="4"/>' if pose == "point" else
             f'<path d="M93,{my} L107,{my}" fill="none" {S} stroke-width="4"/>')
    scarf = (f'<path d="M80,104 Q100,116 120,104 L120,114 Q100,126 80,114 Z" fill="#E4572E" {S} stroke-width="4"/>'
             f'<path d="M108,116 L116,146 L104,144 Z" fill="#E4572E" {S} stroke-width="4"/>')
    extra = shock_marks() if pose == "shocked" else price_tag() if pose == "point" else ""
    return stick_body(pose, sy=106) + head + glasses + eyes + mouth + scarf + extra


def benny(pose):
    """The office bean: one capsule body, big eyebrows, green tie."""
    body = f'<rect x="68" y="42" width="64" height="148" rx="32" fill="#fff" {S}/>'
    brow_y = 66 if pose != "shocked" else 60
    brows = (f'<path d="M83,{brow_y + 2} L95,{brow_y - 1} M105,{brow_y - 1} L117,{brow_y + 2}" {S} stroke-width="5" fill="none"/>'
             if pose != "point" else
             f'<path d="M83,{brow_y} L95,{brow_y + 2} M105,{brow_y - 3} L117,{brow_y - 6}" {S} stroke-width="5" fill="none"/>')
    tie = f'<polygon points="100,116 108,124 100,160 92,124" fill="#2FA84F" stroke="{INK}" stroke-width="3.5" stroke-linejoin="round"/>'
    legs = f'<path d="M88,190 L82,236 M112,190 L118,236" {S} fill="none"/>'
    if pose == "shocked":
        arms = f'<path d="M70,128 L46,92 M130,128 L154,92" {S} fill="none"/>'
        extra = shock_marks(top=26)
    elif pose == "point":
        arms = f'<path d="M70,130 L54,166 M130,128 L172,116" {S} fill="none"/>'
        extra = price_tag(x=196, y=110)
    else:
        arms = f'<path d="M70,130 L54,168 M130,130 L146,168" {S} fill="none"/>'
        extra = ""
    return legs + arms + body + brows + face(pose, cy=82) + tie + extra


CHARS = [
    ("casey", "Casey", "#F5B700", casey,
     "Le consommateur lambda. Tête ronde, casquette jaune.",
     "C'est « toi » face aux pièges : abonnements, soldes, loyers. Le public s'identifie tout de suite."),
    ("penny", "Penny", "#F2C230", penny,
     "La mascotte argent. Sa tête est une pièce d'or.",
     "Reconnaissable en une seconde sur une miniature, et collée à la niche."),
    ("prof", "Prof. Margin", "#E4572E", prof,
     "L'explicateur. Tête carrée arrondie, lunettes rondes, écharpe rouge.",
     "Le narrateur qui démonte les mécanismes. Peut former un duo avec Casey."),
    ("benny", "Benny", "#2FA84F", benny,
     "Le salarié-haricot. Un seul bloc, gros sourcils, cravate verte.",
     "Très expressif grâce aux sourcils. Idéal pour le travail, les impôts, la retraite."),
]
POSES = [("neutral", "neutre"), ("shocked", "choqué"), ("point", "explique")]


def _dedupe_attrs(markup):
    """Strict XML (librsvg) rejects a repeated attribute: keep the LAST
    stroke-width of each tag (the per-element override)."""
    import re

    def fix(m):
        tag = m.group(0)
        while tag.count('stroke-width=') > 1:
            tag = re.sub(r'\sstroke-width="[^"]*"', '', tag, count=1)
        return tag
    return re.sub(r'<[^<>]+>', fix, markup)


def svg(inner, w=240, h=260):
    inner = _dedupe_attrs(inner)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<rect width="{w}" height="{h}" fill="#FBFAF6"/>{inner}</svg>')


cards = []
for slug, name, color, fn, look, why in CHARS:
    tiles = []
    for pose, label in POSES:
        s = svg(fn(pose))
        with open(os.path.join(OUT_DIR, f"{slug}_{pose}.svg"), "w", encoding="utf-8") as f:
            f.write(s)
        tiles.append(f'<figure>{s}<figcaption>{label}</figcaption></figure>')
    cards.append(f'''
    <section class="card">
      <header><span class="dot" style="background:{color}"></span><h2>{name}</h2></header>
      <p class="look">{look}</p>
      <div class="poses">{"".join(tiles)}</div>
      <p class="why"><b>Pourquoi :</b> {why}</p>
    </section>''')

html = f'''<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mascottes · Hidden Economics</title>
<style>
  :root {{ --bg:#F4F1EA; --card:#fff; --ink:#151515; --muted:#6b6b6b; --rule:#e4dfd3; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font-family: system-ui, -apple-system, Segoe UI, sans-serif; }}
  main {{ max-width:1180px; margin:0 auto; padding:32px 16px 48px; }}
  h1 {{ font-size:26px; margin:0 0 6px; }}
  .intro {{ color:var(--muted); margin:0 0 24px; max-width:780px; line-height:1.5; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(520px,1fr)); gap:18px; }}
  @media (max-width:600px) {{ .grid {{ grid-template-columns:1fr; }} }}
  .card {{ background:var(--card); border:1px solid var(--rule); border-radius:14px; padding:18px; }}
  .card header {{ display:flex; align-items:center; gap:10px; }}
  .card h2 {{ margin:0; font-size:20px; }}
  .dot {{ width:14px; height:14px; border-radius:50%; border:2px solid var(--ink); }}
  .look {{ margin:6px 0 12px; color:var(--muted); }}
  .poses {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }}
  figure {{ margin:0; text-align:center; }}
  figure svg {{ width:100%; height:auto; border-radius:10px; border:1px solid var(--rule); }}
  figcaption {{ font-size:12px; color:var(--muted); margin-top:4px; text-transform:lowercase; }}
  .why {{ margin:12px 0 0; line-height:1.45; font-size:14px; }}
</style></head>
<body><main>
  <h1>4 mascottes pour « Hidden Economics of Everyday Things »</h1>
  <p class="intro">Croquis de départ en trait simple, une seule couleur d'accent chacun (facile à garder identique
  d'une scène à l'autre). Volontairement différents du style Paint Explainer. Le choisi servira d'image de référence
  pour Flux Kontext, qui le redessinera dans chaque scène. On peut mixer (ex. Casey + Prof. Margin en duo).</p>
  <div class="grid">{"".join(cards)}</div>
</main></body></html>'''

path = os.path.join(OUT_DIR, "mascottes.html")
with open(path, "w", encoding="utf-8") as f:
    f.write(html)
print(path)
