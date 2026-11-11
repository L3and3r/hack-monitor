(() => {
  const SEV = ['Kritiek', 'Hoog', 'Middel', 'Laag'];
  const SEVCOL = { Kritiek: 'var(--bad)', Hoog: 'var(--warn)', Middel: 'var(--mid)', Laag: 'var(--low)' };
  const nl = d3.timeFormatLocale({ dateTime: '%a %e %B %Y %X', date: '%d-%m-%Y', time: '%H:%M', periods: ['', ''],
    days: ['zondag','maandag','dinsdag','woensdag','donderdag','vrijdag','zaterdag'], shortDays: ['zo','ma','di','wo','do','vr','za'],
    months: ['januari','februari','maart','april','mei','juni','juli','augustus','september','oktober','november','december'],
    shortMonths: ['jan','feb','mrt','apr','mei','jun','jul','aug','sep','okt','nov','dec'] });
  const fmt = {
    usd: (v) => v == null ? '—' : v >= 1e9 ? '$' + (v / 1e9).toLocaleString('nl-NL', { maximumFractionDigits: 2 }) + ' mld'
      : v >= 1e6 ? '$' + (v / 1e6).toLocaleString('nl-NL', { maximumFractionDigits: 1 }) + ' mln'
      : v >= 1e3 ? '$' + Math.round(v / 1e3).toLocaleString('nl-NL') + 'K' : '$' + v,
    num: (v) => v == null ? '—' : v >= 1e6 ? (v / 1e6).toLocaleString('nl-NL', { maximumFractionDigits: 1 }) + ' mln' : Math.round(v).toLocaleString('nl-NL'),
    dag: nl.utcFormat('%a %-d %b'),
    dagLang: nl.utcFormat('%A %-d %B'),
    tijd: nl.format('%-d %b %H:%M'),
    parse: d3.utcParse('%Y-%m-%d'),
  };
  const $ = (id) => document.getElementById(id);
  const setText = (id, t) => { const el = $(id); if (el) el.textContent = t; };
  let DATA = [];

  // ---------- Data ----------
  async function load() {
    const bust = '?t=' + Date.now();
    const [hacks, meta] = await Promise.all([
      fetch('data/hacks.json' + bust).then((r) => r.json()),
      fetch('data/meta.json' + bust).then((r) => r.ok ? r.json() : null).catch(() => null),
    ]);
    DATA = hacks;
    if (meta && meta.updated_at) setText('bijgewerkt', fmt.tijd(new Date(meta.updated_at)) + (meta.nieuw != null ? ` · ${meta.nieuw} nieuw` : ''));
    renderAll();
  }

  function stats() {
    const laatste = DATA.map((r) => r.datum).sort().at(-1);
    const eind = Date.parse(laatste), DAG = 86400000;
    const age = (r) => Math.round((eind - Date.parse(r.datum)) / DAG);
    const nu = DATA.filter((r) => age(r) < 7), vorig = DATA.filter((r) => age(r) >= 7 && age(r) < 14);
    const som = (rows, k) => rows.reduce((s, r) => s + (Number(r[k]) || 0), 0);
    const top = nu.filter((r) => r.schade_usd != null).sort((a, b) => b.schade_usd - a.schade_usd)[0];
    const dag = DATA.filter((r) => r.datum === laatste);
    const perDag = [];
    for (let i = 14; i >= 0; i--) {
      const datum = new Date(eind - i * DAG).toISOString().slice(0, 10);
      const rows = DATA.filter((r) => r.datum === datum);
      const o = { datum, totaal: rows.length };
      SEV.forEach((s) => (o[s] = rows.filter((r) => r.ernst === s).length));
      perDag.push(o);
    }
    const allUD = DATA.flatMap((r) => [r.toegevoegd, r.bijgewerkt]).filter(Boolean);
    const updateDatum = allUD.length ? allUD.sort().at(-1) : null;
    const nieuwRijen = updateDatum ? DATA.filter((r) => r.toegevoegd === updateDatum) : [];
    const bijgewerktRijen = updateDatum ? DATA.filter((r) => r.bijgewerkt === updateDatum) : [];
    return {
      laatste, dagAantal: dag.length, dagKritiek: dag.filter((r) => r.ernst === 'Kritiek').length,
      inc: nu.length, incV: vorig.length,
      krit: nu.filter((r) => r.ernst === 'Kritiek').length, kritV: vorig.filter((r) => r.ernst === 'Kritiek').length,
      usd: som(nu, 'schade_usd'), rec: som(nu.filter((r) => (r.status || 'Bevestigd') === 'Bevestigd'), 'records'),
      kev: nu.filter((r) => r.categorie === 'Kwetsbaarheid' && r.misbruikt !== false).length,
      top, perDag,
      updateDatum, nieuwAantal: nieuwRijen.length, nieuwKritiek: nieuwRijen.filter((r) => r.ernst === 'Kritiek').length,
      bijgewerktAantal: bijgewerktRijen.length,
    };
  }

  // ---------- Render ----------
  function renderAll() {
    if (!DATA.length) return;
    const s = stats();
    setText('ld-datum', fmt.dagLang(fmt.parse(s.laatste)));
    setText('ld-aantal', s.dagAantal);
    setText('ld-kritiek', s.dagKritiek);
    setText('top-titel', s.top ? s.top.doelwit : 'geen bedrag gemeld');
    setText('top-usd', s.top ? fmt.usd(s.top.schade_usd) : '—');
    const banner = $('update-banner');
    if (s.updateDatum && (s.nieuwAantal > 0 || s.bijgewerktAantal > 0)) {
      const d = fmt.dagLang(fmt.parse(s.updateDatum));
      let t = `Bij de laatste update (${d}) kwamen er ${s.nieuwAantal} incident${s.nieuwAantal === 1 ? '' : 'en'} bij`;
      if (s.nieuwKritiek) t += `, waarvan ${s.nieuwKritiek} kritiek`;
      t += `; ${s.bijgewerktAantal} bestaande melding${s.bijgewerktAantal === 1 ? '' : 'en'} bijgewerkt.`;
      banner.textContent = t;
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
    setText('k-inc', s.inc); setText('k-inc-v', s.incV);
    const d = s.inc - s.incV, el = $('k-inc-d');
    el.textContent = d === 0 ? '(gelijk)' : `(${d > 0 ? '+' : '−'}${Math.abs(d)})`;
    el.className = d > 0 ? 'up' : d < 0 ? 'down' : '';
    setText('k-krit', s.krit); setText('k-krit-v', s.kritV);
    setText('k-usd', fmt.usd(s.usd)); setText('k-rec', fmt.num(s.rec)); setText('k-kev', s.kev);
    drawDag(s.perDag); drawSchade(); drawTabel();
  }

  const tip = $('tip');
  function showTip(ev, lines) {
    tip.replaceChildren(...lines.map((l, i) => { const div = document.createElement('div'); if (i) div.className = 't'; div.textContent = l; return div; }));
    tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(Math.max(8, ev.clientX - w / 2), innerWidth - w - 8) + 'px';
    tip.style.top = Math.max(8, ev.clientY - h - 12) + 'px';
  }
  const hideTip = () => { tip.hidden = true; };

  function drawDag(rows) {
    const el = $('dag-chart'); el.replaceChildren();
    const W = el.clientWidth || 320, H = 240, m = { t: 8, r: 4, b: 26, l: 26 };
    const x = d3.scaleBand().domain(rows.map((r) => r.datum)).range([m.l, W - m.r]).padding(0.2);
    const y = d3.scaleLinear().domain([0, Math.max(1, d3.max(rows, (r) => r.totaal))]).nice().range([H - m.b, m.t]);
    const svg = d3.select(el).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img')
      .attr('aria-label', 'Gestapelde staafgrafiek van incidenten per dag over de laatste 15 dagen, naar ernst');
    svg.append('g').selectAll('line').data(y.ticks(4)).join('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y).attr('y2', y).style('stroke', 'var(--grid)');
    svg.append('g').selectAll('text').data(y.ticks(4)).join('text').attr('x', m.l - 6).attr('y', (v) => y(v) + 4).attr('text-anchor', 'end').text(d3.format('d'));
    svg.append('g').selectAll('g').data(d3.stack().keys(['Laag', 'Middel', 'Hoog', 'Kritiek'])(rows)).join('g').style('fill', (s) => SEVCOL[s.key])
      .selectAll('rect').data((s) => s).join('rect').attr('x', (p) => x(p.data.datum)).attr('width', x.bandwidth())
      .attr('y', (p) => y(p[1])).attr('height', (p) => Math.max(0, y(p[0]) - y(p[1]))).attr('rx', 1);
    const every = Math.ceil(rows.length / Math.max(1, Math.floor((W - m.l) / 52)));
    svg.append('g').selectAll('text').data(rows.filter((r, i) => (rows.length - 1 - i) % every === 0)).join('text')
      .attr('y', H - 8).attr('text-anchor', 'middle').text((r) => fmt.dag(fmt.parse(r.datum)))
      .each(function (r) { const w = this.getComputedTextLength(), cx = x(r.datum) + x.bandwidth() / 2; d3.select(this).attr('x', Math.min(Math.max(cx, w / 2 + 1), W - w / 2 - 1)); });
    svg.append('g').selectAll('rect').data(rows).join('rect').attr('x', (r) => x(r.datum) - x.step() * x.paddingInner() / 2).attr('width', x.step())
      .attr('y', m.t).attr('height', H - m.b - m.t).style('fill', 'transparent')
      .on('pointerenter pointermove', (ev, r) => showTip(ev, [fmt.dagLang(fmt.parse(r.datum)) + ' · ' + r.totaal + ' incidenten', ...SEV.filter((s) => r[s]).map((s) => `${s}: ${r[s]}`)]))
      .on('pointerleave', hideTip);
  }

  function drawSchade() {
    const el = $('schade-chart'); el.replaceChildren();
    const rows = DATA.filter((r) => r.schade_usd != null).sort((a, b) => b.schade_usd - a.schade_usd).slice(0, 8);
    if (!rows.length) { el.textContent = 'Geen bedragen gemeld'; return; }
    const W = el.clientWidth || 320, rowH = 28, m = { t: 4, r: 8, b: 4, l: 0 }, H = m.t + m.b + rows.length * rowH;
    const svg = d3.select(el).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img')
      .attr('aria-label', 'Staafgrafiek van de grootste gemelde schadebedragen in USD, logaritmische schaal');
    const labels = svg.append('g').selectAll('text').data(rows).join('text').attr('x', m.l).attr('y', (r, i) => m.t + i * rowH + rowH / 2 + 4).text((r) => r.doelwit);
    let lw = 0; labels.each(function () { lw = Math.max(lw, this.getComputedTextLength()); });
    lw = Math.min(lw, W * 0.4);
    labels.each(function (r) { let t = r.doelwit; while (this.getComputedTextLength() > lw && t.length > 4) { t = t.slice(0, -1); d3.select(this).text(t + '…'); } });
    const x0 = m.l + lw + 8, x = d3.scaleLog().domain([1e5, d3.max(rows, (r) => r.schade_usd)]).range([x0, W - m.r - 70]).clamp(true);
    svg.append('g').selectAll('rect').data(rows).join('rect').attr('x', x0).attr('y', (r, i) => m.t + i * rowH + 6).attr('height', rowH - 12)
      .attr('width', (r) => Math.max(2, x(r.schade_usd) - x0)).attr('rx', 2).style('fill', (r) => SEVCOL[r.ernst]);
    svg.append('g').selectAll('text').data(rows).join('text').attr('x', (r) => x(r.schade_usd) + 6).attr('y', (r, i) => m.t + i * rowH + rowH / 2 + 4)
      .style('font-variant-numeric', 'tabular-nums').text((r) => fmt.usd(r.schade_usd));
    svg.append('g').selectAll('rect').data(rows).join('rect').attr('x', 0).attr('width', W).attr('y', (r, i) => m.t + i * rowH).attr('height', rowH).style('fill', 'transparent')
      .on('pointerenter pointermove', (ev, r) => showTip(ev, [r.titel, `${fmt.usd(r.schade_usd)} · ${fmt.dag(fmt.parse(r.datum))} · ${r.ernst}`]))
      .on('pointerleave', hideTip);
  }

  const filter = { cat: '', min: 1, q: '', st: '', nieuw: false };
  function drawTabel() {
    const tb = $('tabel'); tb.replaceChildren();
    const q = filter.q.trim().toLowerCase();
    const st = (r) => r.status || 'Bevestigd';
    const allUD = DATA.flatMap((r) => [r.toegevoegd, r.bijgewerkt]).filter(Boolean);
    const updateDatum = allUD.length ? allUD.sort().at(-1) : null;
    const rows = DATA.filter((r) => (!filter.cat || r.categorie === filter.cat) && Number(r.ernst_score) >= filter.min
      && (!filter.st || (filter.st === 'bevestigd' ? st(r) !== 'Claim' : st(r) === 'Claim'))
      && (!q || [r.titel, r.doelwit, r.samenvatting, r.cve, r.land].join(' ').toLowerCase().includes(q))
      && (!filter.nieuw || (updateDatum && (r.toegevoegd === updateDatum || r.bijgewerkt === updateDatum))))
      .sort((a, b) => b.datum.localeCompare(a.datum) || b.ernst_score - a.ernst_score);
    if (!rows.length) { const td = tb.insertRow().insertCell(); td.colSpan = 7; td.className = 'empty'; td.textContent = 'Geen incidenten voor dit filter.'; return; }
    d3.groups(rows, (r) => r.datum).forEach(([datum, dag]) => {
      const kc = tb.insertRow(); kc.className = 'day';
      const c = kc.insertCell(); c.colSpan = 7;
      const krit = dag.filter((r) => r.ernst === 'Kritiek').length;
      c.textContent = `${fmt.dagLang(fmt.parse(datum))} · ${dag.length} incident${dag.length === 1 ? '' : 'en'}${krit ? ` · ${krit} kritiek` : ''}`;
      dag.forEach((r) => {
        const tr = tb.insertRow();
        const sev = document.createElement('span'); sev.className = 'sev ' + r.ernst; sev.textContent = r.ernst; tr.insertCell().append(sev);
        const inc = tr.insertCell();
        const t = document.createElement('div');
        t.textContent = r.titel + (r.cve && /^(CVE|GHSA)/.test(r.cve) ? ` (${r.cve}${r.cvss ? ', CVSS ' + r.cvss : ''})` : '');
        const s = document.createElement('div'); s.className = 'sum';
        if (updateDatum && r.toegevoegd === updateDatum) { const b = document.createElement('span'); b.className = 'badge nieuw'; b.textContent = 'nieuw'; s.append(b); }
        if (updateDatum && r.bijgewerkt === updateDatum) { const b = document.createElement('span'); b.className = 'badge upd'; b.textContent = 'bijgewerkt'; s.append(b); }
        if (st(r) !== 'Bevestigd') { const b = document.createElement('span'); b.className = 'badge ' + (st(r) === 'Claim' ? 'claim' : 'deels'); b.textContent = st(r) === 'Claim' ? 'claim van aanvallers, onbevestigd' : 'aanval bevestigd, omvang geclaimd'; s.append(b); }
        if (r.categorie === 'Kwetsbaarheid' && r.misbruikt === false) { const b = document.createElement('span'); b.className = 'badge'; b.textContent = 'nog geen misbruik gemeld'; s.append(b); }
        s.append(r.samenvatting || '');
        inc.append(t, s);
        tr.insertCell().textContent = r.categorie;
        tr.insertCell().textContent = r.land;
        const sc = tr.insertCell(); sc.className = 'num'; sc.textContent = r.schade_usd != null ? fmt.usd(r.schade_usd) : '';
        const rc = tr.insertCell(); rc.className = 'num'; rc.textContent = r.records != null ? fmt.num(r.records) : '';
        const a = document.createElement('a'); a.href = /^https:\/\//.test(r.bron_url) ? r.bron_url : '#'; a.target = '_blank'; a.rel = 'noopener'; a.textContent = r.bron;
        tr.insertCell().append(a);
      });
    });
  }
  $('f-cat').addEventListener('change', (e) => { filter.cat = e.target.value; drawTabel(); });
  $('f-ernst').addEventListener('change', (e) => { filter.min = Number(e.target.value); drawTabel(); });
  $('f-status').addEventListener('change', (e) => { filter.st = e.target.value; drawTabel(); });
  $('f-zoek').addEventListener('input', (e) => { filter.q = e.target.value; drawTabel(); });
  $('f-nieuw').addEventListener('change', (e) => { filter.nieuw = e.target.value === 'nieuw'; drawTabel(); });
  let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(renderAll, 150); });

  // Start
  load().catch(() => setText('bijgewerkt', 'data laden mislukt'));
})();
