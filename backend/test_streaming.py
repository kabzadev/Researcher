#!/usr/bin/env python3
"""Quick model test using streaming endpoint to avoid gateway timeout."""
import httpx, json, time, sys

API = "https://kaia-researcher-api.icyglacier-f068d1b2.eastus.azurecontainerapps.io"
PW = "KantarResearch"
Q = "Salience increased in Q4 2025 for Nike in China — what external events could explain it?"

def test(model):
    print(f"\n{'='*60}\nTESTING: {model}\n{'='*60}")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {PW}"}
    payload = {"question": Q, "provider": "openai", "model": model}
    
    start = time.time()
    hyps = {"market": 0, "brand": 0, "competitive": 0}
    vals = {"market": [], "brand": [], "competitive": []}
    broad = 0

    try:
        with httpx.stream("POST", f"{API}/research/stream", json=payload, headers=headers,
                          timeout=httpx.Timeout(600.0, connect=30.0)) as r:
            if r.status_code != 200:
                print(f"  ERROR: HTTP {r.status_code}")
                return None
            buf = ""
            for chunk in r.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    raw, buf = buf.split("\n\n", 1)
                    et = ds = None
                    for ln in raw.strip().split("\n"):
                        if ln.startswith("event: "): et = ln[7:]
                        elif ln.startswith("data: "): ds = ln[6:]
                    if not et or not ds: continue
                    try: d = json.loads(ds)
                    except: continue

                    if et == "hypotheses":
                        for c in ["market","brand","competitive"]:
                            hyps[c] = len(d.get(c, []))
                        print(f"  [{time.time()-start:.0f}s] Hypotheses: m={hyps['market']} b={hyps['brand']} c={hyps['competitive']}")

                    elif et == "hypothesis_result":
                        cat = d.get("category","?")
                        v = d.get("validated", False)
                        bp = d.get("second_pass_used", False)
                        ev = d.get("evidence","")[:60]
                        if v:
                            vals[cat].append({"h": d.get("hypothesis","")[:70], "e": ev, "bp": bp})
                        if bp: broad += 1
                        icon = "✅" if v else "❌"
                        bps = " [broad]" if bp else ""
                        print(f"  [{time.time()-start:.0f}s] {icon} {cat}: {ev}{bps}")

                    elif et == "complete":
                        pass

        elapsed = time.time() - start
        th = sum(hyps.values())
        tv = sum(len(v) for v in vals.values())
        rate = round(tv / max(th,1) * 100, 1)
        print(f"\n  RESULT: {tv}/{th} ({rate}%) in {elapsed:.0f}s | broad={broad}")
        print(f"  Market={len(vals['market'])}/{hyps['market']} Brand={len(vals['brand'])}/{hyps['brand']} Comp={len(vals['competitive'])}/{hyps['competitive']}")
        return {"model": model, "time": round(elapsed,1), "hyps": th, "validated": tv, "rate": rate,
                "m": f"{len(vals['market'])}/{hyps['market']}", "b": f"{len(vals['brand'])}/{hyps['brand']}",
                "c": f"{len(vals['competitive'])}/{hyps['competitive']}", "broad": broad, "items": vals}
    except Exception as e:
        print(f"  EXCEPTION after {time.time()-start:.0f}s: {e}")
        return None

if __name__ == "__main__":
    models = sys.argv[1:] if len(sys.argv) > 1 else ["gpt-4-1-mini", "gpt-4-1-nano", "gpt-5-nano"]
    results = []
    for i, m in enumerate(models):
        r = test(m)
        if r: results.append(r)
        if i < len(models) - 1:
            print(f"\n  ⏳ Waiting 90s...")
            time.sleep(90)

    print(f"\n\n{'='*60}\nSUMMARY\n{'='*60}")
    print(f"{'Model':<20} {'Valid':>8} {'Rate':>8} {'Time':>8} {'M':>6} {'B':>6} {'C':>6} {'Broad':>6}")
    print("-" * 80)
    for r in results:
        print(f"{r['model']:<20} {r['validated']:>5}/{r['hyps']:<2} {r['rate']:>6}% {r['time']:>6.0f}s {r['m']:>6} {r['b']:>6} {r['c']:>6} {r['broad']:>6}")
