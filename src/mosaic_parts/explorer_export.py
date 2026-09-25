"""Self-contained comparison and atomic export of already validated plans."""
import base64
from contextlib import contextmanager
from html import escape
from io import BytesIO
import json
from pathlib import Path
import shutil
import signal
import tempfile
import zipfile

from .explorer import LABELS, SCOPE, budgets_checked, explore, selected_plan, validate_report
from .export import write_json
from .joint_export import load_problem, save_report
from .model import InputError, _unique_object, bounded_read
from .packing_inputs import read_json


@contextmanager
def staging_directory(output):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise InputError(f'output already exists: {output}; choose a new directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f'.{output.name}-', dir=output.parent))
    try:
        yield stage
        files = [p for p in stage.rglob('*') if p.is_file()]
        if any(p.stat().st_size > 10*1024**2 for p in files) or sum(p.stat().st_size for p in files) > 32*1024**2:
            raise InputError('explorer export exceeded size limits')
        if output.exists() or output.is_symlink():
            raise InputError('output appeared during exploration')
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def export_selected(report, plan_id, output):
    plan = selected_plan(report, plan_id)
    report = {k: plan[k] for k in ('generator', 'settings', 'result', 'problem', 'inventory', 'source')} | {'schema_version': 1}
    return save_report(report, plan, output)


def read_report(path):
    try:
        data = json.loads(bounded_read(Path(path), 10*1024**2, 'explorer JSON'), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InputError(f'invalid explorer JSON: {exc}') from exc
    return validate_report(data)


def comparison_html(report):
    validate_report(report)
    payload, options, cards = {}, [], []
    with tempfile.TemporaryDirectory(prefix='mosaic-downloads-') as temp:
        for entry in report['plans']:
            pid, plan = entry['id'], entry['plan']
            directory = Path(temp)/pid
            export_selected(report, pid, directory)
            archive = BytesIO()
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
                for path in sorted(directory.iterdir()):
                    info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(info, path.read_bytes())
            payload[pid] = {p.name: base64.b64encode(p.read_bytes()).decode('ascii')
                            for p in directory.iterdir() if p.name in ('instructions.html', 'parts.csv')}
            payload[pid]['bundle.zip'] = base64.b64encode(archive.getvalue()).decode('ascii')
            r = plan['result']
            associations = [o for o in report['outcomes'] if o['plan_id'] == pid]
            proof = '; '.join(f"budget {o['budget']}: {LABELS[o['result']['status']]}" for o in associations)
            text = f"{pid}: {r['piece_count']} pieces, error {r['image_error']}"
            options.append(f'<option value="{pid}">{text}</option>')
            image = base64.b64encode((directory/'preview.png').read_bytes()).decode('ascii')
            nd = 'Nondominated among returned plans' if entry['nondominated_among_returned'] else 'Dominated by another returned plan'
            cards.append(f'<section id="{pid}" class="plan"><h2>{text}</h2><p>{proof}</p><p>{nd}</p>'
                         f'<img alt="{pid}: sampled source on left, mosaic plan on right; asterisks mark recolored cells" '
                         f'src="data:image/png;base64,{image}"></section>')
    rows = ''.join(f'<tr><td>{i}</td><td>{o["budget"]}</td><td>{LABELS[o["result"]["status"]]}</td>'
                   f'<td>{escape(o["result"]["termination"])}</td><td>{o["result"]["image_error"] if o["plan_id"] else "—"}</td>'
                   f'<td>{o["result"]["piece_count"] if o["plan_id"] else "—"}</td><td>{o["plan_id"] or "—"}</td></tr>'
                   for i, o in enumerate(report['outcomes'], 1))
    controls = ('<label for="selection">Choose a validated plan</label> <select id="selection">' + ''.join(options) + '</select>'
                '<p id="selected" role="status" aria-live="polite"></p><p>'
                '<a id="bundle" download>Download assembly bundle (ZIP)</a> · '
                '<a id="instructions" download>Download printable instructions</a> · '
                '<a id="parts" download>Download parts CSV</a></p>' if options else '<p>No validated plans were returned. No assembly export is available.</p>')
    # Only base64 and generated IDs enter script data; user strings never enter JavaScript.
    return '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Mosaic budget comparison</title>
<style>body{font:16px system-ui;line-height:1.5;max-width:1100px;margin:32px auto;padding:0 20px;color:#182234;background:#fafaf8}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #888;padding:8px;text-align:left}img{max-width:100%;image-rendering:pixelated}
select{font:inherit;padding:8px}a{color:#0645ad}a:focus,select:focus{outline:3px solid #ac5100}.plan{padding:16px;border:1px solid #aaa;margin:20px 0}
[hidden]{display:none} @media print{select,a{display:none}}</style><h1>Mosaic budget comparison</h1>
<p>Compare piece counts against integer squared-RGB error on the same sampled image and inventory.</p>
<p>''' + SCOPE + '''</p><p>Numerical error does not establish perceptual fidelity or physical build quality.</p>
<table><caption>Every requested budget, in input order</caption><thead><tr><th scope="col">Request</th><th scope="col">Budget</th><th scope="col">Proof status</th><th scope="col">Termination</th><th scope="col">Achieved error</th><th scope="col">Pieces</th><th scope="col">Plan</th></tr></thead><tbody>''' + rows + '</tbody></table><h2>Export a plan</h2>' + controls + '<noscript>Selection and downloads require JavaScript. Use the export-plan CLI with comparison.json, or inspect the previews below.</noscript>' + ''.join(cards) + '''<script>
const data = ''' + json.dumps(payload) + ''';
const select = document.getElementById('selection');
const urls = [];
function update() {
  urls.splice(0).forEach(URL.revokeObjectURL);
  const id = select.value;
  for (const [element, file, type] of [['bundle','bundle.zip','application/zip'],['instructions','instructions.html','text/html'],['parts','parts.csv','text/csv']]) {
    const bytes = Uint8Array.from(atob(data[id][file]), c => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], {type})); urls.push(url);
    const link = document.getElementById(element); link.href=url; link.download=id+'-'+file;
  }
  document.querySelectorAll('.plan').forEach(card => card.hidden = card.id !== id);
  document.getElementById('selected').textContent = 'Selected '+select.selectedOptions[0].textContent;
}
if (select) {select.addEventListener('change', update); update();}
</script></html>'''


def export_comparison(report, output):
    validate_report(report)
    with staging_directory(output) as stage:
        write_json(stage/'comparison.json', report)
        (stage/'comparison.html').write_text(comparison_html(report), encoding='utf-8')
    return report


def explore_image(image, palette, inventory, output, width, height, budgets, *, fit='contain',
                  background=(255, 255, 255), **settings):
    budgets_checked(budgets)
    # Reject collision before image decoding or search.
    if Path(output).exists() or Path(output).is_symlink():
        raise InputError('output already exists; choose a new directory')
    problem, metadata = load_problem(image, palette, width, height, 0, fit, background)
    inv = read_json(inventory)
    report = explore(problem, inv, budgets, **settings)
    metadata.update(fit=fit, background=list(background), sampling='EXIF transpose; alpha matte; Pillow LANCZOS; 8-bit RGB')
    report['source'] = metadata
    for entry in report['plans']:
        entry['plan']['source'] = metadata
    return export_comparison(report, output)


@contextmanager
def cancellation_signals():
    """SIGINT/SIGTERM request cooperative cancellation; restore caller handlers."""
    stopped = [False]
    def request(signum, frame):
        stopped[0] = True
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        for s in previous:
            signal.signal(s, request)
        yield lambda: stopped[0]
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)
