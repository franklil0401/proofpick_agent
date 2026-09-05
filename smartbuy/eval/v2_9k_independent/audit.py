"""Read-only audit; stdout only, no production or model writes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = "99c7bccc523addc7e8904571dbe8e20a24615c66"


def stable(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def manifest_audit():
    manifest = json.loads((ROOT / "smartbuy/docs/v2/rc4_semantic_runtime_manifest.json").read_text(encoding="utf8"))
    contract = manifest["semantic_contract"]
    tree = subprocess.check_output(["git", "rev-parse", PRODUCTION + "^{tree}"], cwd=ROOT, text=True).strip()
    assert tree == contract["production_tree"] == "6b6e98009cefe5aa13f64cf8fe1b24d001fbadb1"
    assert stable(contract) == manifest["payload_sha256"] == "7126740e9a893a18575f829aff78ef48b346eca0f622db73c952ece4cff8eb25"
    listed = set(subprocess.check_output(["git", "ls-tree", "-rz", "--name-only", PRODUCTION], cwd=ROOT).decode().split("\0"))
    members = {}
    for group in contract["file_groups"].values():
        assert group["aggregate_sha256"] == stable(group["members"])
        assert group["members"] == sorted(group["members"], key=lambda row: row["path"])
        for row in group["members"]:
            assert row["path"] in listed
            if row["path"] in members:
                assert members[row["path"]] == row["sha256"]
            members[row["path"]] = row["sha256"]
    # Batch reads preserve raw blob bytes and avoid hundreds of subprocess launches.
    paths = sorted(members)
    proc = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, input=(
        "\n".join(PRODUCTION + ":" + path for path in paths) + "\n").encode(), capture_output=True, check=True)
    payload = proc.stdout
    position = 0
    for path in paths:
        end = payload.index(b"\n", position)
        _, kind, size = payload[position:end].split()
        assert kind == b"blob"
        position = end + 1
        blob = payload[position:position + int(size)]
        position += int(size) + 1
        assert hashlib.sha256(blob).hexdigest() == members[path], path
        assert (ROOT / path).read_bytes().replace(b"\r\n", b"\n") == blob.replace(b"\r\n", b"\n"), path
    return {"production_commit": PRODUCTION, "tree": tree, "payload": stable(contract),
            "groups": len(contract["file_groups"]), "unique_members": len(members), "mismatches": 0}


def runtime_audit():
    import chromadb
    from chromadb.config import Settings
    from smartbuy.domain_packs import DomainPackRegistry
    from smartbuy.product_packs import DomainProductPackManager
    from smartbuy.retrieval.domain_index import DomainIndexManager

    runtime = Path("C:/ppv2rc3evalrun")
    contract = json.loads((ROOT / "smartbuy/docs/v2/rc4_semantic_runtime_manifest.json").read_text(encoding="utf8"))["semantic_contract"]
    records = []
    for expected in contract["domains"]:
        domain = expected["domain_id"]
        pack = DomainPackRegistry(ROOT / "smartbuy/domain_packs").load(domain)
        assert pack.version == expected["domain_pack_version"]
        if domain == "monitor":
            db = runtime / "monitor/smartbuy_monitors_v1.sqlite"
            index_path = runtime / "monitor/vector_store_text_embedding_v4_1024"
            actual = json.loads((runtime / "monitor/index_manifest.json").read_text(encoding="utf8"))
            assert actual["data_version"] == expected["data_version"]
            assert actual["collection_metadata"]["chunk_config_version"] == expected["index_version"]
        else:
            manager = DomainProductPackManager(runtime / "v2" / domain / "data", domain_pack_path=ROOT / "smartbuy/domain_packs" / domain)
            data = manager.current()
            assert data.data_version == expected["data_version"]
            assert data.manifest["logical_data_sha256"] == expected["data_logical_sha256"]
            index = DomainIndexManager(runtime / "v2" / domain / "index", data_manager=manager,
                                       domain_id=domain, domain_pack_version=pack.version).current()
            assert index.index_version == expected["index_version"]
            assert index.data_version == data.data_version
            assert index.collection_name == expected["collection_name"]
            db = data.database_path
            index_path = index.root / "chroma"
        with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
            count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        assert integrity == "ok" and not foreign and count == 12
        client = chromadb.PersistentClient(path=str(index_path), settings=Settings(anonymized_telemetry=False))
        collection = client.get_collection(expected["collection_name"])
        observed = collection.get(include=["embeddings", "metadatas"])
        dimensions = sorted({len(v) for v in observed["embeddings"]})
        assert collection.count() == expected["document_count"]
        assert dimensions == [1024]
        assert all(m["data_version"] == expected["data_version"] for m in observed["metadatas"])
        records.append({**expected, "sqlite_integrity": integrity, "foreign_key_violations": 0,
                        "products": count, "observed_chunks": collection.count(), "observed_dimensions": dimensions})
    return records


if __name__ == "__main__":
    print(json.dumps({"manifest": manifest_audit(), "runtime": runtime_audit(), "model_calls": 0}, ensure_ascii=False))
