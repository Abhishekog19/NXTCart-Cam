"""Check catalogue-to-reference wiring on the PC without a paid API request."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('catalog_json', help='same measured catalogue JSON imported on Pi')
    parser.add_argument('--backend', choices=['local', 'ai'], default='local')
    args = parser.parse_args()
    products = json.loads(Path(args.catalog_json).read_text(encoding='utf-8'))
    errors = []
    if args.backend == 'local':
        from ml.matcher import load_database
        from ml.verifier import load_colour_db
        appearances = load_database(str(ROOT/'embedding_db.pkl'))
        colours = load_colour_db(str(ROOT/'embedding_db.pkl'))
    for item in products:
        sku = item['sku']
        folder = ROOT/'references'/sku
        if folder.parent != ROOT/'references' or not folder.is_dir():
            errors.append(f'{sku}: reference folder absent or invalid'); continue
        images = [p for p in folder.iterdir() if p.suffix.lower() in ('.jpg', '.png', '.jpeg')]
        if len(images) < 3:
            errors.append(f'{sku}: fewer than three reference images')
        if args.backend == 'local' and (sku not in appearances or sku not in colours):
            errors.append(f'{sku}: appearance or colour evidence missing; rebuild database')
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'PASS: {len(products)} catalogue products have {args.backend} reference evidence')


if __name__ == '__main__':
    main()
