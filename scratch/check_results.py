import json
from pathlib import Path

def check():
    path = Path("jobs/struggle_test/aligned.json")
    if not path.exists():
        print("File not found")
        return
    
    data = json.loads(path.read_text(encoding="utf-8"))
    targets = ["I", "a", "I'm", "Cause", "'Cause"]
    
    print(f"{'Word':<10} | {'Prob':<10} | {'Duration':<10} | {'Source':<15}")
    print("-" * 55)
    
    found = 0
    for w in data["words"]:
        if w["word"] in targets:
            dur = w["end"] - w["start"]
            print(f"{w['word']:<10} | {w.get('probability', 0):<10.4f} | {dur:<10.4f} | {w.get('source', 'unknown'):<15}")
            found += 1
            if found > 20: break

if __name__ == "__main__":
    check()
