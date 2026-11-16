"""Run price-demo integration against a real model and isolated temporary backend."""

import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from alfa_reco.search import SearchEngine
from alfa_reco.server import make_server

ROOT = Path(__file__).absolute().parent.parent
NODE_TEST = r"""
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {api,setAccessToken} from './src/shared/api/client.js';
import {rankDemoOffers} from './src/features/catalog/demoRecommendations.js';
const origin=process.env.DEMO_TEST_ORIGIN, originalFetch=globalThis.fetch;
globalThis.fetch=(path,options)=>originalFetch(new URL(path,origin),options);
const auth=await api.register('demo-paid-test','a-strong-temporary-password');
setAccessToken(auth.access_token);
try {
 const data=JSON.parse(readFileSync('../data/demo_catalog.json','utf8'));
 const answer=await api.search({q:'как управлять командой',top:50});
 const opts={query:'как управлять командой',modelResults:answer.results,maxPrice:3000};
 const baseline=rankDemoOffers(data.items,opts);
 const commercial=rankDemoOffers(data.items,{...opts,preferMargin:true});
 assert.ok(answer.results.length>0);
 assert.ok(baseline.length>0);
 assert.ok(baseline.some(x=>x.matchedModel));
 assert.ok(commercial.every(x=>x.item.demo_offer.price_rub<=3000));
 assert.ok(commercial.every((x,i)=>Math.abs(x.originalPosition-(i+1))<=1));
 assert.ok(commercial.every(x=>x.item.demo_offer.kind==='fictional_simulation'));
 assert.ok(commercial.some((x,i)=>x.item.id!==baseline[i].item.id));
 console.log(JSON.stringify({status:'passed',model_results:answer.results.length,
  under_budget:commercial.length,model_matched:commercial.filter(x=>x.matchedModel).length,
  reordered:commercial.filter((x,i)=>x.item.id!==baseline[i].item.id).length}));
} finally { await api.logout(); }
"""


def main():
    backend = ROOT / "backend"
    python = str(backend / ".venv/bin/python")
    engine = SearchEngine(ROOT / "models/runtime/catalog")
    engine.relevance_backend()
    model = make_server(engine, port=0, default_mode="relevance", host="127.0.0.1")
    thread = threading.Thread(target=model.serve_forever, daemon=True)
    thread.start()
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="alfa-priced-demo-") as temp:
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": ".",
                    "ALFA_CATALOG_SOURCE": "imported",
                    "ALFA_RECO_MODE": "http",
                    "ALFA_RECO_URL": f"http://127.0.0.1:{model.server_port}",
                    "ALFA_RECO_TIMEOUT": "120",
                    "ALFA_AUTO_CREATE_TABLES": "true",
                    "ALFA_DATABASE_URL": "sqlite:///" + str(Path(temp) / "db.sqlite3"),
                }
            )
            env.pop("ALFA_TEST_DATABASE_URL", None)
            subprocess.run(
                [
                    python,
                    "scripts/seed_model_sandbox.py",
                    "--catalog",
                    str(ROOT / "models/runtime/catalog"),
                    "--database",
                    str(Path(temp) / "db.sqlite3"),
                ],
                cwd=backend,
                env=env,
                check=True,
            )
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            with (Path(temp) / "backend.log").open("w+") as log:
                process = subprocess.Popen(
                    [
                        python,
                        "-m",
                        "uvicorn",
                        "app:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                        "--no-proxy-headers",
                    ],
                    cwd=backend,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError("Backend exited before readiness")
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/ready", timeout=2
                        ) as response:
                            if response.status == 200:
                                break
                    except (OSError, ValueError):
                        time.sleep(0.5)
                else:
                    raise RuntimeError("Backend did not become ready")
                env["DEMO_TEST_ORIGIN"] = f"http://127.0.0.1:{port}"
                subprocess.run(
                    ["node", "--input-type=module", "-e", NODE_TEST],
                    cwd=ROOT / "frontend",
                    env=env,
                    check=True,
                )
                process.terminate()
                process.wait(timeout=10)
                process = None
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        model.shutdown()
        model.server_close()
        thread.join()


if __name__ == "__main__":
    main()
