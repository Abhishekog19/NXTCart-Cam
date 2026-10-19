"""Validate catalogue consistency and bibliography structure without network access."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent
catalogue = json.loads((root / 'resource_catalogue.json').read_text(encoding='utf-8'))
ieee = [r for r in catalogue if r['ieee_id']]
metadata = {}
for name in ('crossref_metadata.json', 'crossref_supplement.json',
             'crossref_corrections.json', 'crossref_additional.json'):
    for result in json.loads((root / name).read_text(encoding='utf-8')):
        for record in ([result['record']] if 'record' in result else result.get('candidates', [])):
            metadata[record['DOI'].lower()] = record

assert len(catalogue) == 85
assert len(ieee) == 41
assert len({r['ieee_id'] for r in ieee}) == 41
assert sum(bool(r['already_have']) for r in ieee) == 3
for r in ieee:
    record = metadata[r['doi'].lower()]
    url = record.get('resource', {}).get('primary', {}).get('URL', '')
    match = re.search(r'(?:document/|arnumber=)(\d+)', url)
    assert match and match.group(1) == r['ieee_id'], (r['ref'], url)

bib = (root / 'nxtcart_references.bib').read_text(encoding='utf-8')
keys = re.findall(r'^@\w+\{([^,]+),', bib, re.M)
assert len(keys) == len(set(keys)) == 85
assert set(keys) == {'NXTCart' + r['ref'] for r in catalogue}
depth = 0
for i, ch in enumerate(bib):
    if i and bib[i - 1] == '\\':
        continue
    depth += (ch == '{') - (ch == '}')
    assert depth >= 0
assert depth == 0

ids_text = (root / 'IEEE_DOCUMENT_IDS.txt').read_text(encoding='utf-8')
standalone = re.findall(r'^\d+$', ids_text, re.M)
assert len(standalone) == len(set(standalone)) == 41
assert set(standalone) == {r['ieee_id'] for r in ieee}
for name in ('README.md', 'IEEE_DOWNLOAD_QUEUE.md', 'ANNOTATED_CATALOGUE.md',
             'SUPPLIED_PAPER_AUDIT.md'):
    data = (root / name).read_text(encoding='utf-8')
    assert '\ufffd' not in data, name

print('Validated: 85 unique references; 41 IEEE IDs match publisher metadata; '
      '38 new downloads; 85 balanced BibTeX entries; identifier files agree.')
