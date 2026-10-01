from pathlib import Path
import json
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from worker.core import Project


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        next_row = [i]
        for j, cb in enumerate(b, 1):
            next_row.append(min(row[j] + 1, next_row[-1] + 1, row[j - 1] + (ca != cb)))
        row = next_row
    return row[-1]


def evaluate(reference, actual):
    unmatched = set(range(len(actual)))
    rows = []
    for truth in reference:
        overlaps = [(min(truth["end"], actual[i]["end"]) - max(truth["start"], actual[i]["start"]), i) for i in unmatched]
        overlap, index = max(overlaps, default=(0, -1))
        found = overlap > 0
        cue = actual[index] if found else None
        if found:
            unmatched.remove(index)
        rows.append({"expected": truth, "actual": cue and {k: cue[k] for k in ("start", "end", "source")},
                     "start_error": abs(cue["start"] - truth["start"]) if found else None,
                     "end_error": abs(cue["end"] - truth["end"]) if found else None,
                     "errors": distance(normalized(truth["text"]), normalized(cue["source"]) if found else "")})
    total_chars = sum(len(normalized(row["expected"]["text"])) for row in rows)
    cer = (sum(row["errors"] for row in rows) + sum(len(normalized(actual[i]["source"])) for i in unmatched)) / total_chars
    boundary = sum(row["actual"] is not None and max(row["start_error"], row["end_error"]) <= .20001 for row in rows) / len(rows)
    recall = sum(row["actual"] is not None for row in rows) / len(rows)
    return {"recall": recall, "false_events": len(unmatched), "cer": cer, "boundary_within_200ms": boundary,
            "passed": recall == 1 and not unmatched and cer <= .02 and boundary >= .95, "rows": rows}


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "artifacts/ocr-project"
    if input_path.suffix == '.json':
        data = json.loads(input_path.read_text())
    else:
        project = Project(input_path)
        data = project.data
    reference = json.loads((root / "artifacts/fixtures/reference.json").read_text())
    result = evaluate(reference, data["cues"])
    result["scan"] = data["scan"]
    (root / "artifacts/ocr-evaluation.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({k: result[k] for k in ("recall", "false_events", "cer", "boundary_within_200ms", "passed")}, indent=2))
