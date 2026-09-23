"""External probe harness for DeepNotes. Drives the HTTP API only.

This lives OUTSIDE the application package (../DeepNotes). It does not import
or modify application code; it is a black-box client.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

# The app returns arbitrary unicode (currency symbols, CJK, emoji); the Windows
# console defaults to cp1252 and would crash the probe, not the app.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.environ.get("DN_BASE", "http://127.0.0.1:8000")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from steps import PHASES  # noqa: E402

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http(method, path, data=None, ctype=None, headers=None, timeout=300.0):
    url = BASE + path
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if data is not None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        if ctype:
            hdrs["Content-Type"] = ctype
        elif "Content-Type" not in hdrs:
            hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    t0 = time.time()
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), raw.decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, dict(e.headers), raw.decode("utf-8", "replace"), time.time() - t0
    except Exception as e:
        return None, {}, "TRANSPORT ERROR: %r" % (e,), time.time() - t0


def brief(value, limit):
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", "\\n")
    if len(text) > limit:
        text = text[:limit] + "...<+%d chars>" % (len(text) - limit)
    return text


def fmt_response(ctype, text, show):
    if "json" in (ctype or "").lower():
        try:
            obj = json.loads(text)
        except Exception:
            return brief(text, show)
        return brief(obj, show)
    return brief(text, show)


def run_phase(phase, only=None, start=1):
    steps = PHASES[phase]
    print("=" * 100)
    print("PHASE %s  (%d steps)  base=%s" % (phase, len(steps), BASE))
    print("=" * 100, flush=True)
    tally = {}
    total = 0.0
    for i, step in enumerate(steps, 1):
        if only and i != only:
            continue
        if start and i < start:
            continue
        tag = "%s-%02d" % (phase, i)
        kind = step.get("kind", "req")
        desc = step["desc"]
        if kind == "wait":
            deadline = time.time() + step.get("timeout", 900)
            last = ""
            while time.time() < deadline:
                _, _, text, _ = http("GET", "/api/status", timeout=30)
                try:
                    st = json.loads(text)["jobs"]
                except Exception:
                    st = {}
                cur = "pending=%s running=%s completed=%s failed=%s" % (
                    st.get("pending"), st.get("running"), st.get("completed"), st.get("failed"))
                if cur != last:
                    print("[%s] WAIT  %s  -> %s" % (tag, desc, cur), flush=True)
                    last = cur
                if st and not st.get("pending") and not st.get("running"):
                    break
                time.sleep(5)
            print("[%s] WAIT  drained: %s" % (tag, last), flush=True)
            tally["wait"] = tally.get("wait", 0) + 1
            continue
        if kind == "sleep":
            time.sleep(step.get("seconds", 2))
            print("[%s] SLEEP %ss" % (tag, step.get("seconds", 2)), flush=True)
            continue
        if kind == "concurrent":
            import concurrent.futures
            reqs = step["requests"]
            print("\n[%s] %s  (%d parallel requests)" % (tag, desc, len(reqs)), flush=True)

            def one(idx_req):
                idx, rq = idx_req
                payload = json.dumps(rq["body"], ensure_ascii=False).encode("utf-8") if rq.get("body") is not None else None
                st, hd, tx, el = http(rq["method"], rq["path"], payload, None, None, step.get("timeout", 600.0))
                return idx, rq, st, tx, el

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(reqs)) as pool:
                results = list(pool.map(one, enumerate(reqs, 1)))
            for idx, rq, st, tx, el in results:
                key = str(st)
                tally[key] = tally.get(key, 0) + 1
                total += el
                print("   <- [%d] %s  %s  (%.2fs)  %s" % (
                    idx, st, brief(rq["body"]["question"], 60), el, fmt_response("application/json", tx, step.get("show", 260))), flush=True)
                with open(os.path.join(OUT, "%s_%d.json" % (tag, idx)), "w", encoding="utf-8") as fh:
                    json.dump({"tag": "%s_%d" % (tag, idx), "desc": desc, "body": rq["body"],
                               "status": st, "elapsed": el, "response": tx}, fh, ensure_ascii=False, indent=1)
            continue

        method = step["method"]
        path = step["path"]
        body = step.get("body")
        raw = step.get("raw")
        payload = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
        show = step.get("show", 400)
        print("\n[%s] %s" % (tag, desc), flush=True)
        print("   -> %s %s" % (method, path), flush=True)
        if payload is not None:
            print("      body: %s" % brief(payload, step.get("show_body", 160)), flush=True)
        if step.get("headers"):
            print("      hdrs: %s" % brief(step["headers"], 160), flush=True)
        status, hdrs, text, elapsed = http(
            method, path, payload, step.get("ctype"), step.get("headers"), step.get("timeout", 300.0))
        total += elapsed
        key = str(status)
        tally[key] = tally.get(key, 0) + 1
        print("   <- %s  (%.2fs)  %s" % (status, elapsed, fmt_response(hdrs.get("content-type", hdrs.get("Content-Type")), text, show)), flush=True)
        with open(os.path.join(OUT, "%s.json" % tag), "w", encoding="utf-8") as fh:
            json.dump({"tag": tag, "desc": desc, "method": method, "path": path,
                       "body": body, "raw": raw, "status": status, "elapsed": elapsed,
                       "response": text}, fh, ensure_ascii=False, indent=1)
    print("\n" + "-" * 100)
    print("PHASE %s SUMMARY: statuses=%s  wall=%.1fs" % (phase, tally, total), flush=True)
    print("-" * 100, flush=True)


if __name__ == "__main__":
    phase = sys.argv[1]
    only = int(sys.argv[2]) if len(sys.argv) > 2 else None
    start = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    run_phase(phase, only, start)
