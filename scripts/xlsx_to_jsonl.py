"""
Convert the tuning spreadsheet into the app's JSONL format.

    python scripts/xlsx_to_jsonl.py "tuning set.xlsx" data/tuning.jsonl

Spreadsheet columns map to the fields run_eval.py uses:
  Task -> category, Language -> lang, Source -> channel, Difficulty -> difficulty,
  Prompt -> prompt, Expected answer -> reference, Rubric -> rubric,
  Human review? -> expected_human_review (True/False), Scoring method, Max score,
  Pass mark -> kept for scoring.
Every row uses the BFSI tenant, since these are all banking prompts.
The .xlsx is read with the standard library (an .xlsx is a zip of XML files),
so openpyxl isn't needed.
"""
import json
import sys
import zipfile
import xml.etree.ElementTree as ET

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
LANG = {"english": "en", "hindi": "hi", "punjabi": "pa", "hinglish": "hinglish",
        "punjabi (romanized)": "rom_pa", "hindi (romanized)": "rom_hi"}
CHANNEL = {"text": "text", "voice_live": "voice_live", "voice_batch": "batch"}
SCRIPT = {"hi": "devanagari", "pa": "gurmukhi"}


def read_sheet(path, sheet="xl/worksheets/sheet1.xml"):
    z = zipfile.ZipFile(path)
    ss = [''.join(t.text or '' for t in si.iter(M + 't'))
          for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(M + 'si')]
    rows = []
    for row in ET.fromstring(z.read(sheet)).iter(M + 'row'):
        d = {}
        for c in row.findall(M + 'c'):
            v, t = c.find(M + 'v'), c.get('t')
            col = ''.join(ch for ch in c.get('r') if ch.isalpha())
            if t == 's' and v is not None:
                d[col] = ss[int(v.text)]
            elif t == 'inlineStr':
                d[col] = ''.join(x.text or '' for x in c.iter(M + 't'))
            else:
                d[col] = v.text if v is not None else ''
        rows.append(d)
    return rows


def main(src, dst):
    rows = read_sheet(src)
    header, body = rows[0], rows[1:]
    out = []
    for i, r in enumerate(body, start=1):
        lang = LANG[r["C"].strip().lower()]
        # Columns: A variant, B task, C language, D source, E difficulty,
        # F prompt, G expected answer, H human review, I scoring method,
        # J rubric, K max score, L pass mark
        out.append({
            "id": f"u{i:02d}", "tenant": "bfsi", "variant": r["A"], "category": r["B"],
            "lang": lang, "channel": CHANNEL[r["D"].strip()], "difficulty": r["E"].strip(),
            "prompt": r["F"], "reference": r["G"], "expected_human_review": r["H"].startswith("Yes"),
            "human_review_reason": r["H"], "scoring_method": r["I"], "rubric": r["J"],
            "max_score": float(r["K"]), "pass_mark": float(r["L"]),
            "expects_json": r["B"] == "extraction", "out_tokens": 120,
        })
    with open(dst, "w", encoding="utf8") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(f"wrote {len(out)} prompts to {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
