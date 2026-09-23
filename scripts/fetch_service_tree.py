#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Выгрузка услуги и всех связанных объектов МосИТСМ в один JSON.

Использование:
  python scripts/fetch_service_tree.py --service <ID или URL> [--env QA|PROD] [--out file.json]

Вывод: JSON-файл со структурой:
  {
    "meta": {"fetched_at", "env", "base_url", "web_base"},
    "service": {...},
    "service_instances": [ {поля, "slas": [id...]} ...],
    "service_offerings": [...],
    "slas": [...],
    "request_templates": [...]
  }
"""
import argparse
import base64
import datetime
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

ENV_FILE = os.path.join(os.path.dirname(__file__), "..", "skill_env.json")


def load_env():
    with open(ENV_FILE, encoding="utf-8-sig") as f:
        return json.load(f)


def ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def nodeid_to_id(node_id: str):
    """nodeID вида base64('itsm-qa.mos.ru/Service/22940') -> ('Service', '22940')."""
    try:
        raw = base64.b64decode(node_id).decode()
        parts = raw.split("/")
        return parts[-2], parts[-1]
    except Exception:
        return None, None


def parse_service_ref(ref: str):
    """ID или URL карточки (https://community.itsm-qa.mos.ru/services/123) -> '123'."""
    m = re.search(r"/services/(\d+)", ref)
    if m:
        return m.group(1)
    if ref.isdigit():
        return ref
    raise SystemExit(f"Не удалось извлечь ID услуги из: {ref}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", required=True, help="ID или URL услуги")
    ap.add_argument("--env", choices=["QA", "PROD"], default=None)
    ap.add_argument("--out", default=None, help="файл вывода (по умолчанию service_tree_<id>.json)")
    ap.add_argument("--token", default=None)
    args = ap.parse_args()

    env = load_env()
    stage = (args.env or env.get("MOSITSM_STAGE", "QA")).upper()
    base = env["MOSITSM_API_URL_PROD" if stage == "PROD" else "MOSITSM_API_URL_QA"].rstrip("/")
    token = args.token or env.get(f"MOSITSM_PERS_TOKEN_{stage}", "")
    account = env.get("MOSITSM_ACCOUNT", "community")
    web_base = "https://community.itsm.mos.ru" if stage == "PROD" else "https://community.itsm-qa.mos.ru"

    headers = {"Authorization": f"Bearer {token}", "X-4me-Account": account}

    def get(path):
        url = path if path.startswith("http") else f"{base}/{path}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx()) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise SystemExit(f"HTTP {e.code} на {url}: {e.read().decode('utf-8', 'replace')[:300]}")

    svc_id = parse_service_ref(args.service)
    out = {
        "meta": {
            "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "env": stage,
            "base_url": base,
            "web_base": web_base,
            "service_id": svc_id,
        }
    }

    out["service"] = get(f"services/{svc_id}")

    instances = get(f"services/{svc_id}/service_instances")
    sla_ids = set()
    for inst in instances:
        try:
            slas = get(f"service_instances/{inst['id']}/slas")
        except SystemExit:
            slas = []
        inst["slas"] = [s["id"] for s in slas]
        for s in slas:
            sla_ids.add(s["id"])
    out["service_instances"] = instances

    out["service_offerings"] = []
    for off in get(f"services/{svc_id}/service_offerings"):
        out["service_offerings"].append(get(f"service_offerings/{off['id']}"))

    out["slas"] = []
    for sla_id in sorted(sla_ids):
        out["slas"].append(get(f"slas/{sla_id}"))

    out["request_templates"] = []
    for rt in get(f"services/{svc_id}/request_templates"):
        out["request_templates"].append(get(f"request_templates/{rt['id']}"))

    outfile = args.out or f"service_tree_{svc_id}.json"
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # краткая сводка в stdout
    print(f"Услуга: {out['service'].get('name')} (id={svc_id}), среда {stage}")
    print(f"Компонентов услуг: {len(instances)}")
    print(f"Предложений: {len(out['service_offerings'])}")
    print(f"SLA: {len(out['slas'])}")
    print(f"Шаблонов запросов: {len(out['request_templates'])}")
    print(f"Файл: {os.path.abspath(outfile)}")
    print(f"Карточка: {web_base}/services/{svc_id}")


if __name__ == "__main__":
    main()
