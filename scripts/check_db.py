"""
check_db.py — verify the embedding DB scores its own reference images correctly.
Run:  python scripts/check_db.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
from ml.embedding_extractor import extract_embedding
from ml.matcher import match

ref_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "references")

print("Self-match scores (each reference image vs the full DB)")
print("-" * 60)
all_correct = True
for product in sorted(os.listdir(ref_dir)):
    prod_dir = os.path.join(ref_dir, product)
    if not os.path.isdir(prod_dir):
        continue
    imgs = sorted(f for f in os.listdir(prod_dir) if f.lower().endswith((".jpg", ".png")))
    for img_name in imgs:
        img = cv2.imread(os.path.join(prod_dir, img_name))
        if img is None:
            continue
        emb = extract_embedding(img)
        result = match(emb)
        correct = result["top_name"] == product
        if not correct:
            all_correct = False
        flag = "OK  " if correct else "FAIL"
        print(f"  [{flag}] {product}/{img_name}  ->  {result['top_name']!r}  "
              f"score={result['top_score']:.4f}  margin={result['margin']:.4f}  confident={result['confident']}")

print("-" * 60)
if all_correct:
    print("All reference images match correctly. DB is healthy.")
else:
    print("WARNING: some images failed. DB may need rebuilding.")
    print("Run:  python build_db.py")
