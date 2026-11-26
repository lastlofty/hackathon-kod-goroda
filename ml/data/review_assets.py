"""Generate local visual-review candidates; never assign physical asset IDs."""
import argparse
import csv
import hashlib
import html
import itertools
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageOps


def dhash(image):
    gray = ImageOps.grayscale(image).resize((9, 8), Image.Resampling.LANCZOS)
    pixels = gray.tobytes()
    bits = 0
    for y in range(8):
        for x in range(8):
            i = y * 9 + x
            bits = (bits << 1) | int(pixels[i] > pixels[i + 1])
    return bits


def distance(a, b):
    return bin(a ^ b).count('1')


def review(dataset, threshold=12, neighbors=2):
    dataset = Path(dataset).resolve()
    out = dataset / 'review'
    if out.exists():
        raise ValueError(f'Review already exists: {out}; preserve or rename it before rerunning')
    rows = json.loads((dataset / 'manifest.json').read_text(encoding='utf-8'))
    by_id = {r['image_id']: r for r in rows}
    if len(by_id) != len(rows):
        raise ValueError('Duplicate image ID')
    hashes, paths = {}, {}
    for key, row in by_id.items():
        if not key.startswith('mgts_') or not key[5:] or any(c not in '0123456789abcdef' for c in key[5:]):
            raise ValueError(f'Invalid image ID: {key}')
        path = (dataset / row['image_path']).resolve()
        if not path.is_relative_to(dataset / 'images'):
            raise ValueError(f'Image outside images/: {path}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError(f'Image integrity check failed: {key}')
        with Image.open(path) as im:
            hashes[key] = dhash(ImageOps.exif_transpose(im))
        paths[key] = path
    pairs, ranked = {}, defaultdict(list)
    for a, b in itertools.combinations(sorted(by_id), 2):
        d = distance(hashes[a], hashes[b])
        flags = []
        if d <= threshold:
            flags.append('dhash_threshold')
        if Path(by_id[a]['source_path']).name.casefold() == Path(by_id[b]['source_path']).name.casefold():
            flags.append('same_filename')
        if by_id[a]['sha256'] == by_id[b]['sha256']:
            flags.append('exact_bytes')
        pairs[(a, b)] = (d, flags)
        ranked[a].append((d, b))
        ranked[b].append((d, a))
    for key, items in ranked.items():
        for _, other in sorted(items)[:neighbors]:
            flags = pairs[tuple(sorted((key, other)))][1]
            if 'nearest_neighbor' not in flags:
                flags.append('nearest_neighbor')
    candidates = sorted((d, a, b, flags) for (a, b), (d, flags) in pairs.items() if flags)
    out.mkdir()
    (out / 'thumbs').mkdir()
    for key, path in paths.items():
        with Image.open(path) as im:
            thumb = ImageOps.exif_transpose(im).convert('RGB')
            thumb.thumbnail((480, 480), Image.Resampling.LANCZOS)
            thumb.save(out / 'thumbs' / f'{key}.jpg', quality=85)
    with (out / 'candidate_pairs.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['image_id_a', 'image_id_b', 'dhash_distance', 'reason', 'decision', 'notes'])
        for d, a, b, flags in candidates:
            writer.writerow([a, b, d, ';'.join(flags), '', ''])
    esc = lambda x: html.escape(str(x or ''), quote=True)
    def tile(key):
        r = by_id[key]
        return (f'<figure><img loading="lazy" src="thumbs/{key}.jpg" alt="{key}">'
                f'<figcaption><code>{key}</code><br>{esc(Path(r["source_path"]).name)}<br>'
                f'{esc(r["object_type"])} / {esc(r["condition_category"])}<br>'
                f'{esc(r["description_raw"])}</figcaption></figure>')
    parts = ['<!doctype html><html lang="ru"><meta charset="utf-8"><title>MGTS asset review</title>',
             '<style>body{font:16px system-ui,sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;color:#202124} '
             'section{border:1px solid #ccc;border-radius:8px;margin:16px 0;padding:12px} .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px} '
             'figure{margin:0;overflow-wrap:anywhere} img{width:100%;height:280px;object-fit:contain;background:#eee} figcaption{font-size:13px} code{font-size:12px}</style>',
             '<h1>MGTS: проверка физических объектов</h1><p>Кандидаты, не подтверждённые дубликаты. Сравните корпус, крепления, окружение и маркировку. '
             'В asset_review.csv присваивайте один ID только подтверждённым или консервативно связанным объектам; спорные случаи отметьте в review_notes. '
             'Этот HTML не редактирует CSV и не отправляет данные в сеть.</p>',
             '<p><a href="#gallery">Все фотографии</a></p><h2>Пары для проверки</h2>']
    for d, a, b, flags in candidates:
        parts.append(f'<section><strong>dHash: {d}/64 · {esc(", ".join(flags))}</strong><div class="tiles">{tile(a)}{tile(b)}</div></section>')
    parts.append('<h2 id="gallery">Все фотографии (по категории)</h2><div class="tiles">')
    for key in sorted(by_id, key=lambda k: (by_id[k]['object_type'] or '', by_id[k]['condition_category'] or '', k)):
        parts.append(tile(key))
    parts.append('</div></html>')
    (out / 'index.html').write_text('\n'.join(parts), encoding='utf-8')
    summary = {'images': len(rows), 'compared_pairs': len(pairs), 'candidate_pairs': len(candidates),
               'dhash_threshold': threshold, 'threshold_pairs': sum(d <= threshold for d, _, _, _ in candidates),
               'same_filename_pairs': sum('same_filename' in flags for _, _, _, flags in candidates),
               'exact_byte_pairs': sum('exact_bytes' in flags for _, _, _, flags in candidates),
               'nearest_neighbors_per_image': neighbors, 'asset_groups_assigned': 0}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('dataset', type=Path)
    p.add_argument('--threshold', type=int, default=12, choices=range(65), metavar='0..64')
    p.add_argument('--neighbors', type=int, default=2, choices=range(11), metavar='0..10')
    args = p.parse_args()
    print(json.dumps(review(args.dataset, args.threshold, args.neighbors), indent=2))
