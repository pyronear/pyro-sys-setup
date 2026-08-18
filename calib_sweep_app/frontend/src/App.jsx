import { useEffect, useState } from 'react'

async function api(url, body) {
  const r = await fetch(url, body ? {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  } : undefined)
  const j = await r.json().catch(() => ({ detail: 'réponse invalide' }))
  if (!r.ok) throw new Error(j.detail || r.statusText)
  return j
}

function imgUrl(folder, name, w) {
  return `/api/image?path=${encodeURIComponent(folder)}&name=${encodeURIComponent(name)}&w=${w || ''}`
}

function parseLatLon(text) {
  const m = String(text).split(/[,;]/).map((s) => parseFloat(s.trim()))
  if (m.length !== 2 || m.some(Number.isNaN)) return null
  return { lat: m[0], lon: m[1] }
}

/** Image cliquable : pose un marqueur, renvoie des coordonnées normalisées. */
function ClickableImage({ folder, name, click, onClick, color = '#eb6834' }) {
  return (
    <div className="imgwrap">
      <img
        src={imgUrl(folder, name, 1280)}
        alt={name}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          onClick({ image: name, x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height })
        }}
      />
      {click && click.image === name && (
        <div className="marker" style={{ left: `${click.x * 100}%`, top: `${click.y * 100}%`, borderColor: color }}>
          <span style={{ background: color }} />
          <span style={{ background: color }} />
        </div>
      )}
    </div>
  )
}

/** Navigation par flèches ◀ ▶ dans la liste d'images. */
function Picker({ title, folder, images, defaultIdx, click, setClick, color }) {
  const [idx, setIdx] = useState(defaultIdx)
  useEffect(() => { setIdx(defaultIdx) }, [images])
  const go = (d) => {
    setIdx((i) => Math.min(images.length - 1, Math.max(0, i + d)))
    setClick(null)
  }
  return (
    <div className="picker">
      <h3>{title}</h3>
      <div className="nav">
        <button className="arrow" onClick={() => go(-1)} disabled={idx === 0}>◀</button>
        <span className="imgname">{images[idx]} <small>({idx + 1}/{images.length})</small></span>
        <button className="arrow" onClick={() => go(1)} disabled={idx === images.length - 1}>▶</button>
      </div>
      <ClickableImage folder={folder} name={images[idx]} click={click} color={color}
        onClick={setClick} />
      <div className="hint">
        {click ? `repère : (${(click.x * 100).toFixed(1)} %, ${(click.y * 100).toFixed(1)} %)` : 'clique le repère dans l’image'}
      </div>
    </div>
  )
}

export default function App() {
  const [path, setPath] = useState('/Users/mateo/pyronear/deploy/pyro-sys-setup/cam_calibration/captures/192.168.255.34/192.168.1.11/images_sweep')
  const [scan, setScan] = useState(null)
  const [err, setErr] = useState('')
  const [clickA, setClickA] = useState(null)
  const [clickB, setClickB] = useState(null)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState(null)
  const [sunIdx, setSunIdx] = useState(0)
  const [sunClick, setSunClick] = useState(null)
  const [latlon, setLatlon] = useState('')
  const [anchor, setAnchor] = useState(null)
  const [patrol, setPatrol] = useState(null)
  const [savedTo, setSavedTo] = useState(null)

  async function doScan() {
    setErr(''); setScan(null); setRes(null); setAnchor(null)
    setClickA(null); setClickB(null); setSunClick(null); setSunIdx(0)
    try {
      const j = await api(`/api/scan?path=${encodeURIComponent(path)}`)
      setScan(j)
      if (j.coords) setLatlon(`${j.coords.lat}, ${j.coords.lon}`)
    } catch (e) { setErr(e.message) }
  }

  async function doCalibrate() {
    setErr(''); setBusy(true); setRes(null); setAnchor(null)
    try {
      setRes(await api('/api/calibrate', { path: scan.folder, click_a: clickA, click_b: clickB }))
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function doAnchor() {
    const c = parseLatLon(latlon)
    if (!c) { setErr('coordonnées invalides — format attendu : 48.478, 2.424'); return }
    setErr(''); setBusy(true); setAnchor(null); setPatrol(null)
    try {
      setAnchor(await api('/api/anchor', { job: res.job, click_sun: sunClick, lat: c.lat, lon: c.lon }))
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function doPatrol() {
    setErr(''); setBusy(true); setPatrol(null)
    try {
      const j = await api('/api/patrol', { job: res.job })
      setPatrol(j.rows); setSavedTo(j.saved_to)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function doSave() {
    setErr('')
    try { setSavedTo((await api('/api/save', { job: res.job })).saved_to) }
    catch (e) { setErr(e.message) }
  }

  function downloadCsv() {
    const rows = anchor.images.map((n, i) => `sweep,${n},${anchor.abs_az[i]},${anchor.elevations[i]}`)
    if (patrol) {
      for (const p of patrol) {
        if (p.azimuth != null) rows.push(`patrol,${p.image},${p.azimuth},${p.elevation}`)
      }
    }
    const blob = new Blob([`kind,image,azimuth_deg,elevation_deg\n${rows.join('\n')}`], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'azimuts_sweep.csv'
    a.click()
  }

  const sunImage = scan ? scan.images[sunIdx] : null

  return (
    <main>
      <h1>🧭 Calibration du sweep</h1>

      <section>
        <h2>1 · Dossier d'images</h2>
        <div className="row">
          <input value={path} onChange={(e) => setPath(e.target.value)}
            placeholder="/chemin/vers/images_sweep" />
          <button onClick={doScan}>Scanner</button>
        </div>
        {scan && <div className="ok">{scan.images.length} images : {scan.images[0]} → {scan.images.at(-1)}</div>}
      </section>

      {scan && (
        <section>
          <h2>2 · Pointer le même repère au début et à la fin</h2>
          <p className="hint">Un repère <b>lointain</b> (crête, clocher — pas le pylône) visible dans une image
            du début ET une de la fin (le sweep dépasse 360°, la fin re-voit le paysage du début).
            Navigue avec ◀ ▶.</p>
          <div className="cols">
            <Picker title="Début du sweep" folder={scan.folder} images={scan.images}
              defaultIdx={0} click={clickA} setClick={setClickA} color="#2a78d6" />
            <Picker title="Fin du sweep" folder={scan.folder} images={scan.images}
              defaultIdx={scan.images.length - 1} click={clickB} setClick={setClickB} color="#eb6834" />
          </div>
        </section>
      )}

      {scan && (
        <section>
          <h2>3 · Paramètres du sweep</h2>
          <button disabled={!clickA || !clickB || busy} onClick={doCalibrate}>
            {busy && !res ? 'calcul en cours (~1 min)…' : 'Calculer FOV, pas et azimuts'}
          </button>
          {res && (
            <>
              <div className="metrics">
                <div><b>{res.hfov.toFixed(2)}°</b><span>HFOV auto-calibré</span></div>
                <div><b>{res.step_mean.toFixed(2)}° ± {res.step_std.toFixed(2)}</b><span>pas moyen</span></div>
                <div><b>{res.span_clicked_deg.toFixed(1)}°</b><span>angle entre les 2 clics</span></div>
                <div><b>{res.n_images}</b><span>images</span></div>
              </div>
              {res.warnings.map((w, i) => <div className="warn" key={i}>⚠ {w}</div>)}
            </>
          )}
        </section>
      )}

      {res && scan && (
        <section>
          <h2>4 · Pointer le soleil → azimuts absolus</h2>
          <p className="hint">Repère l'image où le disque solaire est le plus net dans la planche ci-dessous,
            puis <b>clique son centre</b> dans la grande image.</p>
          <div className="row">
            <label>Position du site (lat, lon)&nbsp;
              <input value={latlon} onChange={(e) => setLatlon(e.target.value)}
                placeholder="48.478, 2.424" size={22} />
            </label>
            {scan.coords && <span className="hint">(pré-remplie depuis la config du site)</span>}
          </div>

          <div className="thumbs">
            {scan.images.map((n, i) => (
              <div key={n} className={`thumb ${i === sunIdx ? 'sel' : ''}`}
                onClick={() => { setSunIdx(i); setSunClick(null) }}>
                <img src={imgUrl(scan.folder, n, 220)} alt={n} loading="lazy" />
                <div className="lbl">{n.replace(/^pose_/, '').replace(/_20\d{12}/, '')}</div>
              </div>
            ))}
          </div>

          <div className="cols">
            <div className="picker">
              <div className="nav">
                <button className="arrow" disabled={sunIdx === 0}
                  onClick={() => { setSunIdx(sunIdx - 1); setSunClick(null) }}>◀</button>
                <span className="imgname">{sunImage} <small>({sunIdx + 1}/{scan.images.length})</small></span>
                <button className="arrow" disabled={sunIdx === scan.images.length - 1}
                  onClick={() => { setSunIdx(sunIdx + 1); setSunClick(null) }}>▶</button>
              </div>
              <ClickableImage folder={scan.folder} name={sunImage} click={sunClick}
                color="#f5c518" onClick={setSunClick} />
              <div className="hint">heure de capture : {new Date(scan.times[sunImage]).toLocaleString('fr-FR')}</div>
            </div>
            <div>
              <button disabled={!sunClick || !latlon || busy} onClick={doAnchor}>
                Déduire les azimuts de toutes les images
              </button>
              {anchor && (
                <>
                  <div className="metrics">
                    <div><b>{anchor.sun_az.toFixed(2)}°</b><span>azimut soleil</span></div>
                    <div><b>{anchor.sun_alt.toFixed(2)}°</b><span>élévation soleil</span></div>
                    <div><b>{anchor.el_click.toFixed(2)}°</b><span>élévation du clic</span></div>
                    <div><b>{anchor.offset.toFixed(2)}°</b><span>offset d'ancrage</span></div>
                  </div>
                  {anchor.el_gap > 3 && (
                    <div className="warn">⚠ Écart d'élévation de {anchor.el_gap.toFixed(1)}° avec le soleil :
                      mauvais point, mauvaise heure ou mauvaises coordonnées ?</div>
                  )}
                  <button onClick={downloadCsv}>Télécharger CSV</button>
                </>
              )}
            </div>
          </div>
          {anchor && (
            <table>
              <thead><tr><th>image</th><th>azimut (°)</th><th>élévation (°)</th></tr></thead>
              <tbody>
                {anchor.images.map((n, i) => (
                  <tr key={n}><td>{n}</td><td>{anchor.abs_az[i].toFixed(2)}</td><td>{anchor.elevations[i].toFixed(2)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {anchor && (
        <section>
          <h2>5 · Azimuts des poses de patrouille</h2>
          <p className="hint">Chaque image de <code>images_patrol/</code> est matchée par keypoints contre le
            sweep : l'image la plus proche donne sa rotation, donc son azimut.</p>
          <button disabled={busy} onClick={doPatrol}>
            {busy && !patrol ? 'matching en cours…' : 'Déduire les azimuts des poses'}
          </button>
          {patrol && (
            <div className="row" style={{ margin: '.6rem 0' }}>
              <button onClick={doSave}>Sauvegarder le CSV à côté d'images_patrol</button>
              {savedTo && <span className="ok">✔ sauvegardé : {savedTo}</span>}
            </div>
          )}
          {patrol && (
            <table>
              <thead><tr><th>pose</th><th>image</th><th>image du sweep la plus proche</th>
                <th>inliers</th><th>azimut (°)</th><th>élévation (°)</th></tr></thead>
              <tbody>
                {patrol.map((p) => (
                  <tr key={p.image}>
                    <td>{p.pose}</td><td>{p.image}</td>
                    <td>{p.matched ?? '— aucun match —'}</td><td>{p.inliers}</td>
                    <td>{p.azimuth != null ? p.azimuth.toFixed(2) : '—'}</td>
                    <td>{p.elevation != null ? p.elevation.toFixed(2) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {err && <div className="err">Erreur : {err}</div>}
    </main>
  )
}
