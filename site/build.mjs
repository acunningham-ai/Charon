#!/usr/bin/env node
/* Charon deep-dive site build.
 * Single source of chrome (nav/footer/scripts) + one stylesheet.
 * Assembles static HTML into ../docs/ (which GitHub Pages serves verbatim).
 * The one-pager index.html is standalone and is NOT touched by this build.
 *
 * Run:  node site/build.mjs
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE = dirname(fileURLToPath(import.meta.url));
const DOCS = join(SITE, '..', 'docs');
const PAGES_SRC = join(SITE, 'pages');

const PAGES = [
  { name: 'memory',    title: 'Charon — Memory',          active: 'memory'    },
  { name: 'capture',   title: 'Charon — Capture',         active: 'capture'   },
  { name: 'security',  title: 'Charon — Security',        active: 'security'  },
  { name: 'cerberus',  title: 'Charon — Cerberus',        active: 'cerberus'  },
  { name: 'skills',    title: 'Charon — Skills & Hooks',  active: 'skills'    },
  { name: 'agents',    title: 'Charon — Agents',          active: 'agents'    },
  { name: 'workflows', title: 'Charon — Workflows',       active: 'workflows' },
  { name: 'install',   title: 'Charon — Install',         active: ''          },
];

const read = (p) => readFileSync(p, 'utf8');
const navPartial    = read(join(SITE, 'partials', 'nav.html')).trim();
const footerPartial = read(join(SITE, 'partials', 'footer.html')).trim();
const scriptsPartial= read(join(SITE, 'partials', 'scripts.html')).trim();
const styleCss      = read(join(SITE, 'assets', 'style.css'));

// First run: extract each page's body (between </nav> and <footer>) from the
// current docs/ page and save it as the clean source in site/pages/.
// Subsequent runs: use site/pages/ as the source of truth.
function bodyFor(name) {
  const srcPath = join(PAGES_SRC, name + '.html');
  if (existsSync(srcPath)) return read(srcPath).trim();
  const cur = read(join(DOCS, name + '.html'));
  const start = cur.indexOf('</nav>');
  const end = cur.indexOf('<footer');
  if (start < 0 || end < 0) throw new Error(`cannot locate nav/footer boundaries in docs/${name}.html`);
  const body = cur.slice(start + '</nav>'.length, end).trim();
  mkdirSync(PAGES_SRC, { recursive: true });
  writeFileSync(srcPath, body + '\n', 'utf8');
  return body;
}

function navWith(active) {
  if (!active) return navPartial;
  return navPartial.replace(`data-nav="${active}"`, `data-nav="${active}" class="active"`);
}

function page({ title, active }, body) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
${navWith(active)}
${body}
${footerPartial}
${scriptsPartial}
</body>
</html>
`;
}

mkdirSync(join(DOCS, 'assets'), { recursive: true });
writeFileSync(join(DOCS, 'assets', 'style.css'), styleCss, 'utf8');
writeFileSync(join(DOCS, '.nojekyll'), '', 'utf8');

let n = 0;
for (const p of PAGES) {
  const body = bodyFor(p.name);
  writeFileSync(join(DOCS, p.name + '.html'), page(p, body), 'utf8');
  n++;
  console.log(`built docs/${p.name}.html  (active=${p.active || '-'}, body ${body.length}b)`);
}
console.log(`\n✓ ${n} pages built · assets/style.css written · .nojekyll written`);
console.log('  index.html left standalone (one-pager).');
